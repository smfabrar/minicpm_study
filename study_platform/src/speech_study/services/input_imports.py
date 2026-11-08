"""Preview dataset imports, then apply explicit per-question merge choices."""

import hashlib
import json
from dataclasses import asdict, replace
from uuid import UUID, uuid5
from pathlib import PurePosixPath

from ..domain.errors import ConflictError, NotFoundError
from ..domain.models import Case
from ..infrastructure.unit_of_work import UnitOfWork
from .input_archive import InputDatasetArchive
from .deletion import release_audio_bundle


def fingerprint(case, *, include_import=True):
    payload = asdict(case)
    if not include_import:
        payload.pop('input_import')
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class InputImportService:
    def __init__(self, studies, operations, repository):
        self.studies, self.operations, self.repository = studies, operations, repository

    def preview(self, study_id, content):
        self.studies.require_editable(self.studies.get(study_id).study)
        identifier = self.repository.create(study_id)
        try:
            items = InputDatasetArchive(self.repository.store).read(identifier, content)
            details = self.studies.get(study_id)
            self.studies.require_editable(details.study)
            stage = self.repository.get(identifier, study_id)
            stage.update(items=items, archive_sha256=hashlib.sha256(content).hexdigest(),
                         fingerprints={case.id: fingerprint(case) for case in details.cases})
            self.repository.save(stage)
            existing = {case.id: case for case in details.cases}
            previews = []
            for item in items:
                target = existing.get(item['source_case_id'])
                reason = 'case ID' if target else None
                if target is None and item['question']:
                    matches = [case for case in details.cases if case.question.strip().casefold() == item['question'].casefold()]
                    if len(matches) == 1:
                        target, reason = matches[0], 'question text'
                if target is None and int(item['number']) <= len(details.cases):
                    target, reason = details.cases[int(item['number']) - 1], 'folder number'
                previews.append({key: item[key] for key in ('number', 'question', 'category')} | {
                    'has_audio': bool(item['normalized']), 'has_original': bool(item['original']),
                    'suggested_case_id': target.id if target else None, 'match_reason': reason})
            return {'id': identifier, 'items': previews, 'existing_cases': [asdict(case) for case in details.cases]}
        except BaseException:
            self.repository.store.delete(identifier)
            raise

    def audio(self, study_id, identifier, number, kind):
        stage = self.repository.get(identifier, study_id)
        item = next((item for item in stage['items'] if item['number'] == number), None)
        if item is None or kind not in {'original', 'normalized'} or not item[kind]:
            raise NotFoundError('Imported audio not found')
        return self.repository.store.resolve(item[kind])

    def apply(self, study_id, identifier, mode, selections):
        with self.studies.database.lock:
            stage = self.repository.get(identifier, study_id)
            self.studies.require_editable(self.studies.get(study_id).study)
            items = {item['number']: item for item in stage['items']}
            numbers = [selection['number'] for selection in selections]
            targets = [selection.get('case_id') for selection in selections] if mode == 'replace' else []
            if len(set(numbers)) != len(numbers) or set(numbers) - set(items):
                raise ValueError('Select each imported folder once')
            if mode == 'replace' and (None in targets or len(set(targets)) != len(targets)):
                raise ValueError('Select a distinct existing question for each replacement')
            results = []
            for selection in selections:
                try:
                    case = self._apply_item(study_id, stage, mode, items[selection['number']], selection)
                    results.append({'number': selection['number'], 'status': 'applied', 'case_id': case.id})
                except (ValueError, ConflictError, NotFoundError) as exc:
                    results.append({'number': selection['number'], 'status': 'failed', 'error': str(exc)})
                except Exception as exc:
                    results.append({'number': selection['number'], 'status': 'failed',
                                    'error': f'Storage operation failed ({type(exc).__name__}); retry this row'})
            return {'results': results, 'applied': sum(row['status'] == 'applied' for row in results)}

    def _apply_item(self, study_id, stage, mode, item, selection):
        marker = {'id': stage['id'], 'number': item['number'], 'mode': mode,
                  'selection': selection, 'archive_sha256': stage['archive_sha256']}
        case_id = selection.get('case_id') if mode == 'replace' else uuid5(UUID(stage['id']), item['number']).hex
        with UnitOfWork(self.studies.database) as work:
            work.studies.get(study_id)
            try:
                current = work.cases.get(case_id)
            except NotFoundError:
                if mode == 'replace':
                    raise ConflictError('The selected question no longer exists')
                current = None
            if current and current.study_id != study_id:
                raise NotFoundError('Question not found in this study')
        if current and all(current.input_import.get(key) == value for key, value in marker.items()):
            if current.input_import.get('saved_fingerprint') != fingerprint(current, include_import=False):
                raise ConflictError('This imported question was edited afterward; upload the ZIP again to review changes')
            saved_marker = {key: value for key, value in current.input_import.items() if key != 'cleanup_directory'}
            return self._finish_cleanup(current, saved_marker)  # Committed retries do not append twice.
        if mode == 'replace' and fingerprint(current) != stage['fingerprints'].get(case_id):
            raise ConflictError('This question changed after preview; upload the ZIP again before replacing it')
        if current and current.input_import.get('cleanup_directory'):
            previous_marker = {key: value for key, value in current.input_import.items() if key != 'cleanup_directory'}
            current = self._finish_cleanup(current, previous_marker)
        if current and current.audio_deletion_pending:
            raise ConflictError('Finish deleting the selected question\'s audio before importing')
        if mode == 'append' and any(selection[key] != 'imported' for key in ('text', 'audio', 'category')):
            raise ValueError('Appended questions must use imported fields')
        if current and any(operation.status in {'queued', 'running'}
            and operation.payload.get('study_id') == study_id and operation.payload.get('case_id') == case_id
            for operation in self.operations.list(limit=None)):
            raise ConflictError('Wait for this question\'s active work before replacing it')
        if mode == 'append' and current:
            raise ConflictError('This row was already appended with different choices; upload again to import another copy')
        question = current.question if selection['text'] == 'existing' and current else item['question']
        category = current.category if selection['category'] == 'existing' and current else item['category']
        if not question:
            raise ValueError('This folder has no question.txt; keep an existing question or skip the row')
        category = category or (current.category if current else 'custom')
        case = current or Case(case_id, study_id, question)
        changed_text = question != case.question or category != case.category
        case = replace(case, question=question, category=category, input_import=marker)
        if changed_text:
            case = replace(case, expected_answer='', oracle_result='', expected_tool='', expected_arguments={},
                           oracle_mode='server_clock' if category == 'datetime' else 'fixed')
        if selection['audio'] == 'imported':
            if item['normalized']:
                case = self._attach_imported_audio(study_id, case, stage, item)
            elif mode == 'replace':
                raise ValueError('This folder has no audio; choose existing audio or skip the row')
        elif current is None:
            raise ValueError('New questions cannot use existing audio')
        if current and current.audio_path and current.audio_path != case.audio_path:
            case = replace(case, input_import=marker | {
                'cleanup_directory': str(PurePosixPath(current.audio_path).parent)})
        marker = marker | {'saved_fingerprint': fingerprint(case, include_import=False)}
        case = replace(case, input_import=case.input_import | {'saved_fingerprint': marker['saved_fingerprint']})
        with UnitOfWork(self.studies.database) as work:
            work.cases.save(case)
        return self._finish_cleanup(case, marker)

    def _finish_cleanup(self, case, marker):
        directory = case.input_import.get('cleanup_directory')
        if directory:
            try:
                release_audio_bundle(self.studies, case.study_id, case.id, directory)
            except Exception as exc:
                raise ConflictError('New input saved, but previous audio cleanup is incomplete. Retry this row') from exc
            case = replace(case, input_import=marker)
            with UnitOfWork(self.studies.database) as work:
                work.cases.save(case)
        return case

    def _attach_imported_audio(self, study_id, case, stage, item):
        store = self.studies.artifacts
        normalized = self.repository.store.resolve(item['normalized']).read_bytes()
        original = self.repository.store.resolve(item['original']).read_bytes() if item['original'] else None
        provenance = {'import_id': stage['id'], 'source_folder': item['number'],
                      'source_origin': item['source_origin'], 'sample_rate': 16000,
                      'original_present': original is not None, 'archive_sha256': stage['archive_sha256']}
        digest = hashlib.sha256(normalized).hexdigest()
        with UnitOfWork(self.studies.database) as work:
            candidates = [candidate for candidate in work.cases.list_for_study(study_id)
                          if candidate.audio_sha256 == digest and candidate.audio_path
                          and not candidate.audio_deletion_pending]
        for candidate in candidates:
            path = store.resolve(candidate.audio_path)
            source = store.resolve(str(PurePosixPath(candidate.audio_path).with_name('original.wav')))
            same_original = source.read_bytes() == original if source.is_file() else original is None
            if same_original and path.is_file() and path.read_bytes() == normalized:
                self.studies.reserve_artifact_directory(study_id, str(PurePosixPath(candidate.audio_path).parent))
                store.write(candidate.audio_path, normalized)
                if original is not None:
                    store.write(str(PurePosixPath(candidate.audio_path).with_name('original.wav')), original)
                return replace(case, audio_path=candidate.audio_path, audio_sha256=digest,
                               audio_origin='imported', audio_provenance=provenance, preparation_trace=None)
        identity = hashlib.sha256((hashlib.sha256(original).hexdigest() if original else 'no-original').encode() + normalized).hexdigest()
        directory = f'audio/imported/{identity}'
        self.studies.reserve_artifact_directory(study_id, directory)
        if original is not None:
            store.write(directory + '/original.wav', original)
        path = store.write(directory + '/input.wav', normalized)
        store.write_json(directory + '/input_import.json', provenance)
        return replace(case, audio_path=path, audio_sha256=digest,
                       audio_origin='imported', audio_provenance=provenance, preparation_trace=None)
