from dataclasses import asdict, replace

from ..domain.errors import ConflictError, NotFoundError
from ..domain.models import Case, Study, StudyDetails, StudyStatus, ToolDefinition, new_id, utc_now
from speech_contracts import RunSettings
from ..artifacts import ArtifactStore
from ..infrastructure.database import Database
from ..infrastructure.unit_of_work import UnitOfWork
from speech_contracts import validate_definition
from .default_tools import default_tools


class StudyService:
    def __init__(self, database: Database, artifacts: ArtifactStore):
        self.database = database
        self.artifacts = artifacts

    @staticmethod
    def require_editable(study: Study) -> None:
        if study.status == StudyStatus.FROZEN:
            raise ConflictError("This study is frozen. Clone it to make changes.")

    def list(self) -> list[dict]:
        with UnitOfWork(self.database) as work:
            return [{**asdict(study), "case_count": len(work.cases.list_for_study(study.id)), "run_count": len(work.runs.list_for_study(study.id))} for study in work.studies.list()]

    def get(self, study_id: str) -> StudyDetails:
        with UnitOfWork(self.database) as work:
            return StudyDetails(work.studies.get(study_id), work.cases.list_for_study(study_id), work.tools.list_for_study(study_id), work.runs.list_for_study(study_id))

    def create(self, name: str, description: str = "", settings: RunSettings | None = None) -> Study:
        if not name.strip() or len(name) > 160:
            raise ValueError("Study name must contain 1–160 characters")
        study = Study(new_id(), name.strip(), description, settings=settings or RunSettings())
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
                if changes.get("question", case.question) != case.question:
                    case = replace(case, audio_path=None, audio_sha256=None, audio_origin=None, audio_provenance={}, preparation_trace=None)
                case = replace(case, **changes)
            else:
                case = Case(new_id(), study_id, **changes)
            if not case.question.strip() or len(case.question) > 4000:
                raise ValueError("Question must contain 1–4000 characters")
            if case.category not in {"room", "document", "calculator", "none", "custom"}:
                raise ValueError("Unknown case category")
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
            if expected_question is not None and case.question != expected_question:
                raise ConflictError("Question changed while audio was preparing; generate it again")
            case = replace(case, audio_path=path, audio_sha256=checksum, audio_origin=origin,
                           audio_provenance=provenance, preparation_trace=trace_path)
            work.cases.save(case)
        return case

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
            work.tools.save(tool)
        return tool

    def delete_case(self, study_id: str, case_id: str) -> None:
        with UnitOfWork(self.database) as work:
            self.require_editable(work.studies.get(study_id))
            case = work.cases.get(case_id)
            if case.study_id != study_id:
                raise NotFoundError("Case not found")
            if any(run.case_id == case_id for run in work.runs.list_for_study(study_id)):
                raise ConflictError("Cases with run history cannot be deleted")
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
            evaluation = [case for case in cases if case.split == "evaluation"]
            if not evaluation:
                raise ValueError("Add at least one evaluation case before freezing")
            for case in evaluation:
                if not case.audio_path or not case.audio_sha256:
                    raise ValueError("Every evaluation case needs prepared audio")
                if not self.artifacts.resolve(case.audio_path).is_file() or self.artifacts.checksum(case.audio_path) != case.audio_sha256:
                    raise ValueError("Evaluation audio is missing or its checksum changed")
                if case.category != "none" and not case.oracle_result.strip():
                    raise ValueError("Every tool case needs a correct B2 reference result")
            snapshot = {"settings": asdict(study.settings), "cases": [asdict(c) for c in cases], "tools": [asdict(t) for t in tools], "frozen_at": utc_now()}
            study = replace(study, status=StudyStatus.FROZEN, snapshot=snapshot, updated_at=utc_now())
            work.studies.save(study)
        return study

    def clone(self, study_id: str) -> Study:
        with UnitOfWork(self.database) as work:
            original = work.studies.get(study_id)
            clone = replace(original, id=new_id(), name=original.name + " · copy", status=StudyStatus.DRAFT, snapshot=None, created_at=utc_now(), updated_at=utc_now())
            work.studies.save(clone)
            for case in work.cases.list_for_study(study_id):
                work.cases.save(replace(case, id=new_id(), study_id=clone.id))
            for tool in work.tools.list_for_study(study_id):
                work.tools.save(replace(tool, id=new_id(), study_id=clone.id))
        return clone
