"""Permanent study cleanup, preserving files still referenced by another study."""

from dataclasses import replace
from pathlib import PurePosixPath

from ..domain.errors import ConflictError, NotFoundError
from ..domain.models import utc_now
from ..infrastructure.unit_of_work import UnitOfWork


def paths_overlap(left, right):
    left, right = PurePosixPath(left), PurePosixPath(right)
    return left == right or left in right.parents or right in left.parents


def run_audio_directories(runs):
    paths = []
    for run in runs:
        paths.append(run.request.get('audio_path'))
        paths.extend(case.get('audio_path') for case in run.snapshot.get('cases', []))
    return {str(PurePosixPath(path).parent) for path in paths if path}


def artifact_directories(study, cases, runs, operations):
    directories = set(study.artifact_directories)
    inputs = [case.audio_path for case in cases]
    inputs += [case.get('audio_path') for case in (study.snapshot or {}).get('cases', [])]
    for run in runs:
        directories.add(f'runs/{run.id}')
        if run.artifact_directory:
            directories.add(run.artifact_directory)
        inputs.append(run.request.get('audio_path'))
        inputs += [case.get('audio_path') for case in run.snapshot.get('cases', [])]
    directories.update(str(PurePosixPath(path).parent) for path in inputs if path)
    directories.update(operation.artifact_directory for operation in operations if operation.artifact_directory)
    if study.purge_plan:
        directories.update(study.purge_plan['artifacts'])
    return directories


def related_operations(operations, study_id, runs):
    run_ids = {run.id for run in runs}
    return [operation for operation in operations
            if operation.payload.get('study_id') == study_id or operation.payload.get('run_id') in run_ids]


class StudyDeletion:
    def __init__(self, database, artifacts, operations, input_imports=None):
        self.database, self.artifacts, self.operations = database, artifacts, operations
        self.input_imports = input_imports

    def delete(self, study_id):
        # Hold the metadata lock through cleanup so new references cannot appear
        # between checking shared ownership and removing the bytes.
        with self.database.lock:
            with UnitOfWork(self.database) as work:
                study = work.studies.get(study_id, include_deleted=True)
                cases = work.cases.list_for_study(study_id)
                runs = work.runs.list_for_study(study_id)
                all_operations = self.operations.list(limit=None) if self.operations else []
                owned_operations = related_operations(all_operations, study_id, runs)
                if any(run.status in {'queued', 'running'} for run in runs) or any(
                    operation.status in {'queued', 'running'} for operation in owned_operations
                ):
                    raise ConflictError("Wait for this study's queued and running operations before deleting it")
                protected = set()
                for other in work.studies.list() + work.studies.list(deleted=True):
                    if other.id != study_id:
                        other_runs = work.runs.list_for_study(other.id)
                        protected.update(artifact_directories(
                            other, work.cases.list_for_study(other.id), other_runs,
                            related_operations(all_operations, other.id, other_runs)))
                plan = study.purge_plan or {
                    'artifacts': sorted(artifact_directories(study, cases, runs, owned_operations)),
                    'operations': [operation.id for operation in owned_operations],
                }
                # Persist the plan before deleting bytes. If cleanup fails, DELETE
                # can retry, including after restart, without losing artifact paths.
                work.studies.save(replace(study, deleted_at=utc_now(), purge_plan=plan))

            for directory in plan['artifacts']:
                if not any(paths_overlap(directory, reference) for reference in protected):
                    self.artifacts.delete(directory)
            if self.operations:
                for identifier in plan['operations']:
                    self.operations.delete(identifier)
            if self.input_imports:
                self.input_imports.delete_for_study(study_id)
            with UnitOfWork(self.database) as work:
                for run in runs:
                    work.runs.delete(run.id)
                for case in cases:
                    work.cases.delete(case.id)
                for tool in work.tools.list_for_study(study_id):
                    work.tools.delete(tool.id)
                work.studies.delete(study_id)


class CaseAudioDeletion:
    def __init__(self, studies):
        self.studies = studies
        self.database = studies.database
        self.artifacts = studies.artifacts
        self.operations = studies.operations

    def delete(self, study_id, case_id):
        with self.database.lock:
            with UnitOfWork(self.database) as work:
                study = work.studies.get(study_id)
                self.studies.require_editable(study)
                case = work.cases.get(case_id)
                if case.study_id != study_id:
                    raise NotFoundError('Case not found in this study')
                operations = self.operations.list(limit=None) if self.operations else []
                case_operations = [operation for operation in operations
                                   if operation.payload.get('study_id') == study_id
                                   and operation.payload.get('case_id') == case_id]
                if any(operation.status in {'queued', 'running'} for operation in case_operations):
                    raise ConflictError('Wait for this question\'s queued or running work before deleting audio')
                if not case.audio_path:
                    return case
                directory = str(PurePosixPath(case.audio_path).parent)
                runs = work.runs.list_for_study(study_id)
                if any(paths_overlap(directory, reference) for reference in run_audio_directories(runs)):
                    raise ConflictError('Saved runs reference this audio. Delete the study to remove its run history and recordings')
                # Keep the path until all deletes succeed so a retry after an
                # interrupted cloud cleanup knows exactly which bundle to remove.
                case = replace(case, audio_deletion_pending=True)
                work.cases.save(case)

            release_audio_bundle(self.studies, study_id, case_id, directory, ignore_current_case=True)
            with UnitOfWork(self.database) as work:
                case = replace(case, audio_path=None, audio_sha256=None, audio_origin=None,
                               audio_provenance={}, preparation_trace=None, audio_deletion_pending=False)
                work.cases.save(case)
            return case


def release_audio_bundle(studies, study_id, case_id, directory, *, ignore_current_case=False):
    """Release an attachment or replaced input, retaining all other live references."""
    with studies.database.lock:
        with UnitOfWork(studies.database) as work:
            study = work.studies.get(study_id)
            runs = work.runs.list_for_study(study_id)
            if any(paths_overlap(directory, path) for path in run_audio_directories(runs)):
                return  # Historical run evidence remains owned by this study.
            operations = studies.operations.list(limit=None) if studies.operations else []
            owned = [operation for operation in operations
                     if operation.payload.get('study_id') == study_id
                     and operation.payload.get('case_id') == case_id
                     and operation.kind == 'synthesis' and operation.artifact_directory == directory]
            if any(operation.status in {'queued', 'running'} for operation in owned):
                raise ConflictError('Wait for audio preparation to finish before cleanup')
            owned_ids = {operation.id for operation in owned}
            cases = work.cases.list_for_study(study_id)
            own_refs = {str(PurePosixPath(case.audio_path).parent) for case in cases
                        if case.audio_path and not (ignore_current_case and case.id == case_id)}
            own_refs.update(operation.artifact_directory for operation in operations
                            if operation.id not in owned_ids and operation.artifact_directory
                            and operation.payload.get('study_id') == study_id)
            protected = set(own_refs)
            for other in work.studies.list() + work.studies.list(deleted=True):
                if other.id != study_id:
                    other_runs = work.runs.list_for_study(other.id)
                    protected.update(artifact_directories(other, work.cases.list_for_study(other.id),
                        other_runs, related_operations(operations, other.id, other_runs)))
        if not any(paths_overlap(directory, reference) for reference in protected):
            studies.artifacts.delete(directory)
        for operation in owned:
            studies.operations.delete(operation.id)
        if not any(paths_overlap(directory, reference) for reference in own_refs):
            with UnitOfWork(studies.database) as work:
                current = work.studies.get(study_id)
                work.studies.save(replace(current, artifact_directories=[
                    path for path in current.artifact_directories if path != directory]))
