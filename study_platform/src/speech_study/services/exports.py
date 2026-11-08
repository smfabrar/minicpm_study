"""Portable study archives with historical inputs and verifiable file inventory."""

import csv
import hashlib
import io
import json
import re
import wave
import zipfile
from dataclasses import asdict
from pathlib import PurePosixPath

from ..domain.models import utc_now
from ..domain.errors import ConflictError
from .callers import run_caller


class ExportService:
    def __init__(self, studies, analysis, artifacts, operations):
        self.studies = studies
        self.analysis = analysis
        self.artifacts = artifacts
        self.operations = operations

    def export_inputs(self, study_id: str) -> bytes:
        """Export current question/audio pairs without inference or run artifacts."""
        # Keep attachments stable while reading both versions of each recording.
        with self.studies.database.lock:
            details = self.studies.get(study_id)
            if not details.cases:
                raise ValueError('Add questions before exporting the input dataset')
            if any(case.audio_deletion_pending for case in details.cases):
                raise ConflictError('Finish pending audio deletions before exporting inputs')
            folder = re.sub(r'[^\w-]+', '_', details.study.name).strip('_-')[:100]
            folder = folder or f'study-{study_id[:8]}'
            manifest = {'format_version': 1, 'kind': 'study-inputs',
                        'study_id': study_id, 'study_name': details.study.name,
                        'exported_at': utc_now(), 'cases': [], 'missing_audio': []}
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
                for number, case in enumerate(details.cases, 1):
                    directory = f'{folder}/{number}'
                    archive.writestr(f'{directory}/question.txt', case.question.encode('utf-8'))
                    archive.writestr(f'{directory}/category.txt', case.category.encode('utf-8'))
                    entry = {'number': number, 'case_id': case.id, 'category': case.category,
                             'audio_origin': case.audio_origin, 'split': case.split, 'audio_files': []}
                    paths = {
                        f'input{number}.wav': str(PurePosixPath(case.audio_path).with_name('original.wav')) if case.audio_path else None,
                        f'input{number}_16khz.wav': case.audio_path,
                    }
                    for filename, source in paths.items():
                        path = self.artifacts.resolve(source) if source else None
                        destination = f'{directory}/{filename}'
                        if path is None or not path.is_file():
                            manifest['missing_audio'].append({'number': number, 'path': destination,
                                'reason': 'not_prepared' if source is None else 'missing_file'})
                            continue
                        content = path.read_bytes()
                        digest = hashlib.sha256(content).hexdigest()
                        if filename.endswith('_16khz.wav'):
                            if case.audio_sha256 and digest != case.audio_sha256:
                                raise ConflictError(f'Input audio checksum changed for question {number}')
                            try:
                                with wave.open(io.BytesIO(content), 'rb') as audio:
                                    valid = (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (16000, 1, 2)
                            except (wave.Error, EOFError):
                                valid = False
                            if not valid:
                                raise ValueError(f'Question {number} has no valid normalized 16 kHz mono PCM16 input')
                        archive.writestr(destination, content)
                        entry['audio_files'].append({'path': destination, 'size_bytes': len(content), 'sha256': digest})
                    manifest['cases'].append(entry)
                archive.writestr(f'{folder}/manifest.json', json.dumps(manifest, indent=2, ensure_ascii=False).encode('utf-8'))
            return output.getvalue()

    def export(self, study_id: str) -> bytes:
        details = self.studies.get(study_id)
        run_ids = {run.id for run in details.runs}
        operations = [o for o in self.operations.list(limit=None)
                      if o.payload.get("study_id") == study_id or o.payload.get("run_id") in run_ids]
        manifest = {"format_version": 1, "exported_at": utc_now(), "study_id": study_id,
                    "files": [], "missing_artifacts": [],
                    "pending_runs": [r.id for r in details.runs if r.status in {"queued", "running"}],
                    "notes": ["Archive contains artifacts available at export time; pending runs may be incomplete.",
                              "Model weights, external tool files, credentials and the global tool library are not bundled."]}
        output = io.BytesIO()
        included = set()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            def write(name, content):
                if name in included:
                    return
                data = content.encode() if isinstance(content, str) else content
                archive.writestr(name, data)
                included.add(name)
                manifest["files"].append({"path": name, "size_bytes": len(data),
                                          "sha256": hashlib.sha256(data).hexdigest()})

            def write_json(name, value):
                write(name, json.dumps(value, indent=2, ensure_ascii=False))

            def collect(directory):
                directory = self.artifacts.resolve(directory.relative_to(self.artifacts.root).as_posix())
                if not directory.is_dir():
                    return
                for path in sorted(directory.rglob("*")):
                    if path.is_file():
                        # Resolve each entry to reject links that escape managed storage.
                        relative = path.relative_to(self.artifacts.root).as_posix()
                        managed = self.artifacts.resolve(relative)
                        write(relative, managed.read_bytes())

            write_json("study.json", asdict(details))
            write_json("settings.json", asdict(details.study.settings))
            write_json("caller_profiles.json", details.study.caller_profiles)
            write_json("tools.json", [asdict(t) for t in details.tools])
            write_json("analysis.json", self.analysis.summarize_details(details))
            write_json("operations.json", [asdict(o) for o in operations])
            if details.study.snapshot:
                write_json("frozen_snapshot.json", details.study.snapshot)
            for tool in details.tools:
                if tool.python_code:
                    write(f"tool_sources/{tool.id}-{tool.name}.py", tool.python_code)

            csv_buffer = io.StringIO()
            writer = csv.writer(csv_buffer)
            writer.writerow(["run_id", "case_id", "condition", "status", "verdict", "first_audio_ms", "error",
                             "caller_backend", "caller_model", "caller_revision", "caller_device", "caller_quantization", "comparison_id", "repetition"])
            inputs = {c.audio_path for c in details.cases if c.audio_path}
            for run in details.runs:
                writer.writerow([run.id, run.case_id, run.condition, run.status,
                                 run.review.verdict if run.review else "unreviewed",
                                 (run.result or {}).get("metrics", {}).get("input_start_to_first_audio_ms"), run.error,
                                 *[run_caller(run)[key] for key in ("backend", "model", "revision", "device", "quantization")],
                                 run.comparison_id, run.repetition])
                write_json(f"run_metadata/{run.id}.json", asdict(run))
                collect(self.artifacts.resolve(f"runs/{run.id}"))
                if run.request.get("audio_path"):
                    inputs.add(run.request["audio_path"])
                inputs.update(c["audio_path"] for c in run.snapshot.get("cases", []) if c.get("audio_path"))
                if run.status not in {"queued", "running"}:
                    expected = {"remote_job.json", "telemetry.json", "reference.wav"}
                    if (run.result or {}).get("output_audio"):
                        expected.add(run.result["output_audio"])
                    remote = self.artifacts.resolve(f"runs/{run.id}/remote_job.json")
                    if remote.is_file():
                        expected.update(json.loads(remote.read_text()).get("artifacts", []))
                    for name in sorted(expected):
                        relative = f"runs/{run.id}/{name}"
                        if relative not in included:
                            manifest["missing_artifacts"].append(relative)
            write("runs.csv", csv_buffer.getvalue())
            if details.study.snapshot:
                inputs.update(c["audio_path"] for c in details.study.snapshot.get("cases", []) if c.get("audio_path"))
            for relative in sorted(inputs):
                audio = self.artifacts.resolve(relative)
                if audio.is_file():
                    collect(audio.parent)
                else:
                    manifest["missing_artifacts"].append(relative)
            for operation in operations:
                write_json(f"operations/{operation.id}.json", asdict(operation))
                log = self.operations.store.resolve(operation.id + ".log")
                if log.is_file():
                    write(f"operations/{operation.id}.log", log.read_bytes())
                if operation.artifact_directory:
                    collect(self.artifacts.resolve(operation.artifact_directory))
            # Manifest excludes its own hash to avoid a circular digest.
            archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        return output.getvalue()
