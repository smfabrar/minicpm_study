from dataclasses import asdict, replace

from ..domain.errors import ConflictError, NotFoundError
from ..domain.models import Case, Study, StudyDetails, StudyStatus, ToolDefinition, new_id, utc_now
from speech_contracts import RunSettings
from ..artifacts import ArtifactStore
from ..infrastructure.database import Database
from ..infrastructure.unit_of_work import UnitOfWork
from speech_contracts import validate_definition
from .default_tools import default_tools
from .deletion import StudyDeletion, CaseAudioDeletion
from .callers import default_profiles, validate_profiles
from pathlib import PurePosixPath


class StudyService:
    def __init__(self, database: Database, artifacts: ArtifactStore, operations=None, input_imports=None):
        self.database = database
        self.artifacts = artifacts
        self.operations = operations
        self.input_imports = input_imports

    @staticmethod
    def require_editable(study: Study) -> None:
        if study.status == StudyStatus.FROZEN:
            raise ConflictError("This study is frozen. Clone it to make changes.")

    def list(self, *, deleted=False) -> list[dict]:
        with UnitOfWork(self.database) as work:
            return [{**asdict(study), "case_count": len(work.cases.list_for_study(study.id)), "run_count": len(work.runs.list_for_study(study.id))} for study in work.studies.list(deleted=deleted)]

    def get(self, study_id: str) -> StudyDetails:
        with UnitOfWork(self.database) as work:
            return StudyDetails(work.studies.get(study_id), work.cases.list_for_study(study_id), work.tools.list_for_study(study_id), work.runs.list_for_study(study_id))

    def create(self, name: str, description: str = "", settings: RunSettings | None = None, caller_profiles=None) -> Study:
        if not name.strip() or len(name) > 160:
            raise ValueError("Study name must contain 1–160 characters")
        study = Study(new_id(), name.strip(), description, settings=settings or RunSettings())
        study.caller_profiles = validate_profiles(
            default_profiles(study.settings) if caller_profiles is None else caller_profiles, study.settings)
        with UnitOfWork(self.database) as work:
            work.studies.save(study)
            for data in default_tools():
                work.tools.save(ToolDefinition(new_id(), study.id, **data))
        return study

    def update(self, study_id: str, changes: dict) -> Study:
        with UnitOfWork(self.database) as work:
            study = work.studies.get(study_id)
            self.require_editable(study)
            if "settings" in changes:
                changes["settings"] = RunSettings.from_dict({**asdict(study.settings), **changes["settings"]})
            if 'caller_profiles' in changes:
                changes['caller_profiles'] = validate_profiles(changes['caller_profiles'], changes.get('settings', study.settings))
            if "name" in changes and (not changes["name"].strip() or len(changes["name"]) > 160):
                raise ValueError("Study name must contain 1–160 characters")
            study = replace(study, **changes, updated_at=utc_now())
            work.studies.save(study)
        return study

    def save_case(self, study_id: str, changes: dict, case_id: str | None = None) -> Case:
        with UnitOfWork(self.database) as work:
            self.require_editable(work.studies.get(study_id))
            if case_id:
                case = work.cases.get(case_id)
                if case.study_id != study_id:
                    raise NotFoundError("Case not found in this study")
                if case.audio_deletion_pending:
                    raise ConflictError('Finish deleting this question\'s audio before editing it')
                if changes.get("question", case.question) != case.question:
                    case = replace(case, audio_path=None, audio_sha256=None, audio_origin=None, audio_provenance={}, preparation_trace=None)
                case = replace(case, **changes)
            else:
                case = Case(new_id(), study_id, **changes)
            if not case.question.strip() or len(case.question) > 4000:
                raise ValueError("Question must contain 1–4000 characters")
            if case.category not in {"room", "document", "datetime", "web", "calculator", "none", "custom"}:
                raise ValueError("Unknown case category")
            if case.oracle_mode not in {"fixed", "server_clock"}:
                raise ValueError("Unknown B2 reference mode")
            if case.oracle_mode == "server_clock" and (case.category != "datetime" or case.oracle_result.strip()):
                raise ValueError("Live clock references require the datetime category and an empty saved oracle fact")
            if case.split not in {"development", "evaluation"}:
                raise ValueError("Split must be development or evaluation")
            work.cases.save(case)
        return case

    def attach_audio(self, study_id: str, case_id: str, *, path: str, checksum: str, origin: str, provenance: dict, trace_path: str | None = None, expected_question: str | None = None) -> Case:
        with UnitOfWork(self.database) as work:
            self.require_editable(work.studies.get(study_id))
            case = work.cases.get(case_id)
            if case.study_id != study_id:
                raise NotFoundError("Case not found in this study")
            if case.audio_deletion_pending:
                raise ConflictError('Finish deleting this question\'s audio before replacing it')
            if expected_question is not None and case.question != expected_question:
                raise ConflictError("Question changed while audio was preparing; generate it again")
            case = replace(case, audio_path=path, audio_sha256=checksum, audio_origin=origin,
                           audio_provenance=provenance, preparation_trace=trace_path)
            work.cases.save(case)
            study = work.studies.get(study_id)
            directories = sorted(set(study.artifact_directories) | {str(PurePosixPath(path).parent)})
            work.studies.save(replace(study, artifact_directories=directories))
        return case

    def reserve_artifact_directory(self, study_id, directory):
        self.artifacts.resolve(directory)  # Validate managed path before registration.
        with UnitOfWork(self.database) as work:
            study = work.studies.get(study_id)
            self.require_editable(study)
            work.studies.save(replace(study, artifact_directories=sorted(set(study.artifact_directories) | {directory})))

    def delete_audio(self, study_id: str, case_id: str) -> Case:
        return CaseAudioDeletion(self).delete(study_id, case_id)

    def save_tool(self, study_id: str, changes: dict, tool_id: str | None = None) -> ToolDefinition:
        with UnitOfWork(self.database) as work:
            self.require_editable(work.studies.get(study_id))
            if tool_id:
                tool = work.tools.get(tool_id)
                if tool.study_id != study_id:
                    raise NotFoundError("Tool not found in this study")
                tool = replace(tool, **changes)
            else:
                tool = ToolDefinition(new_id(), study_id, **changes)
            validate_definition(asdict(tool))
            others = work.tools.list_for_study(study_id)
            if any(t.name == tool.name and t.id != tool.id for t in others):
                raise ConflictError("Tool names must be unique in a study")
            if len(others) >= 20 and all(t.id != tool.id for t in others):
                raise ValueError("A study supports at most 20 tools")
            work.tools.save(tool)
        return tool

    def delete_case(self, study_id: str, case_id: str) -> None:
        with self.database.lock:
            with UnitOfWork(self.database) as work:
                self.require_editable(work.studies.get(study_id))
                case = work.cases.get(case_id)
                if case.study_id != study_id:
                    raise NotFoundError("Case not found")
                if case.audio_deletion_pending:
                    raise ConflictError('Finish deleting this question\'s audio before deleting the case')
                if any(run.case_id == case_id for run in work.runs.list_for_study(study_id)):
                    raise ConflictError("Cases with run history cannot be deleted")
            self.delete_audio(study_id, case_id)
            with UnitOfWork(self.database) as work:
                work.cases.delete(case_id)

    def delete_tool(self, study_id: str, tool_id: str) -> None:
        with UnitOfWork(self.database) as work:
            self.require_editable(work.studies.get(study_id))
            tool = work.tools.get(tool_id)
            if tool.study_id != study_id:
                raise NotFoundError("Tool not found")
            work.tools.delete(tool_id)

    def freeze(self, study_id: str) -> Study:
        with UnitOfWork(self.database) as work:
            study = work.studies.get(study_id)
            self.require_editable(study)
            cases = work.cases.list_for_study(study_id)
            tools = work.tools.list_for_study(study_id)
            if any(case.audio_deletion_pending for case in cases):
                raise ConflictError('Finish pending audio deletions before freezing')
            evaluation = [case for case in cases if case.split == "evaluation"]
            if not evaluation:
                raise ValueError("Add at least one evaluation case before freezing")
            for case in evaluation:
                if not case.audio_path or not case.audio_sha256:
                    raise ValueError("Every evaluation case needs prepared audio")
                if not self.artifacts.resolve(case.audio_path).is_file() or self.artifacts.checksum(case.audio_path) != case.audio_sha256:
                    raise ValueError("Evaluation audio is missing or its checksum changed")
                if case.category != "none" and case.oracle_mode == "fixed" and not case.oracle_result.strip():
                    raise ValueError("Every tool case needs a correct B2 reference result")
            snapshot = {"settings": asdict(study.settings), "caller_profiles": study.caller_profiles, "cases": [asdict(c) for c in cases], "tools": [asdict(t) for t in tools], "frozen_at": utc_now()}
            study = replace(study, status=StudyStatus.FROZEN, snapshot=snapshot, updated_at=utc_now())
            work.studies.save(study)
        return study

    def clone(self, study_id: str) -> Study:
        with UnitOfWork(self.database) as work:
            original = work.studies.get(study_id)
            if any(case.audio_deletion_pending for case in work.cases.list_for_study(study_id)):
                raise ConflictError('Finish pending audio deletions before cloning')
            clone = replace(original, id=new_id(), name=original.name + " · copy", status=StudyStatus.DRAFT, snapshot=None, created_at=utc_now(), updated_at=utc_now(), artifact_directories=sorted({str(PurePosixPath(case.audio_path).parent) for case in work.cases.list_for_study(study_id) if case.audio_path}))
            work.studies.save(clone)
            for case in work.cases.list_for_study(study_id):
                work.cases.save(replace(case, id=new_id(), study_id=clone.id))
            for tool in work.tools.list_for_study(study_id):
                work.tools.save(replace(tool, id=new_id(), study_id=clone.id))
        return clone


    def delete(self, study_id: str) -> None:
        StudyDeletion(self.database, self.artifacts, self.operations, self.input_imports).delete(study_id)

    def restore(self, study_id: str) -> Study:
        with UnitOfWork(self.database) as work:
            study = work.studies.get(study_id, include_deleted=True)
            if study.purge_plan:
                raise ConflictError("Permanent deletion has started; retry deleting this study")
            study = replace(study, deleted_at=None, updated_at=utc_now())
            work.studies.save(study)
        return study
