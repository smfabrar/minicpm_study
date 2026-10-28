"""Portable study archives with historical inputs and verifiable file inventory."""

import csv
import hashlib
import io
import json
import zipfile
from dataclasses import asdict

from ..domain.models import utc_now


class ExportService:
    def __init__(self, studies, analysis, artifacts, operations):
        self.studies = studies
        self.analysis = analysis
        self.artifacts = artifacts
        self.operations = operations

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
            writer.writerow(["run_id", "case_id", "condition", "status", "verdict", "first_audio_ms", "error"])
            inputs = {c.audio_path for c in details.cases if c.audio_path}
            for run in details.runs:
                writer.writerow([run.id, run.case_id, run.condition, run.status,
                                 run.review.verdict if run.review else "unreviewed",
                                 (run.result or {}).get("metrics", {}).get("input_start_to_first_audio_ms"), run.error])
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
