"""Prepare immutable audio and collect output ASR outside benchmark timing."""

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict

from ..audio import read_pcm, write_pcm
from ..infrastructure.runtime_client import RuntimeClient, RuntimeConnection
from ..infrastructure.background import BackgroundQueue
from ..artifacts import ArtifactStore
from .runs import RunService
from .studies import StudyService
from speech_contracts import SynthesisRequest
from ..infrastructure.preparation_trace import PreparationTrace


class PreparationService:
    def __init__(self, studies: StudyService, runs: RunService, artifacts: ArtifactStore, operations: BackgroundQueue, connection_provider: Callable[[], RuntimeConnection]):
        self.studies = studies
        self.runs = runs
        self.artifacts = artifacts
        self.operations = operations
        self.connection_provider = connection_provider
        operations.register("synthesis", self._synthesize)
        operations.register("transcription", self._transcribe)

    def prepare(self, study_id: str, case_id: str):
        details = self.studies.get(study_id)
        self.studies.require_editable(details.study)
        case = next((c for c in details.cases if c.id == case_id), None)
        if case is None:
            raise ValueError("Case not found in study")
        RuntimeClient(self.connection_provider()).health()
        return self.operations.submit("synthesis", {"study_id": study_id, "case_id": case_id,
                                                    "question": case.question, "settings": asdict(details.study.settings)})

    def _await_job(self, client, job):
        deadline = time.monotonic() + 3600
        while job["status"] in {"queued", "running"}:
            if time.monotonic() > deadline:
                raise TimeoutError("Preparation deadline exceeded")
            if self.operations.stopped.wait(0.8):
                raise RuntimeError("Platform shutting down")
            job = client.job(job["id"])
        if job["status"] != "complete":
            raise RuntimeError(job.get("error") or "Preparation failed")
        return job

    def _synthesize(self, payload):
        from speech_contracts import RunSettings
        settings = RunSettings.from_dict(payload["settings"])
        key = SynthesisRequest(payload["question"], settings).cache_key()
        directory = f"audio/synthesized/{key}"
        audio_path = f"{directory}/input.wav"
        manifest = self.artifacts.resolve(f"{directory}/manifest.json")
        if manifest.is_file() and self.artifacts.resolve(audio_path).is_file():
            result = json.loads(manifest.read_text())
        else:
            client = RuntimeClient(self.connection_provider())
            job = self._await_job(client, client.submit({"job_kind": "synthesis", "question": payload["question"], "settings": payload["settings"]}))
            result = job["result"]
            for name in ("input.wav", "original.wav", "telemetry.json"):
                self.artifacts.write(f"{directory}/{name}", client.artifact(job["id"], name))
            self.artifacts.write_json(f"{directory}/manifest.json", result)
        self.studies.attach_audio(payload["study_id"], payload["case_id"], path=audio_path,
                                  checksum=self.artifacts.checksum(audio_path), origin="synthesized",
                                  provenance=result["provenance"], trace_path=f"{directory}/telemetry.json",
                                  expected_question=payload["question"])

    def upload(self, study_id: str, case_id: str, content: bytes):
        details = self.studies.get(study_id)
        self.studies.require_editable(details.study)
        if not content or len(content) > 50 * 1024 * 1024:
            raise ValueError("Upload a PCM WAV file smaller than 50 MiB")
        key = hashlib.sha256(content).hexdigest()
        directory = f"audio/uploaded/{key}"
        trace = PreparationTrace()
        with trace.span("preparation.audio_upload"):
            original = self.artifacts.write(f"{directory}/original.wav", content)
            with trace.span("audio.normalize_to_16khz"):
                path = self.artifacts.resolve(f"{directory}/input.wav")
                write_pcm(path, read_pcm(self.artifacts.resolve(original)))
        trace.write(self.artifacts.resolve(f"{directory}/telemetry.json"))
        return self.studies.attach_audio(study_id, case_id, path=f"{directory}/input.wav",
                                         checksum=self.artifacts.checksum(f"{directory}/input.wav"), origin="uploaded",
                                         provenance={"original_sha256": key, "sample_rate": 16000}, trace_path=f"{directory}/telemetry.json")

    def transcribe(self, run_id: str):
        run = self.runs.get(run_id)
        if not run.result or not run.result.get("output_audio"):
            raise ValueError("This run has no generated audio to transcribe")
        return self.operations.submit("transcription", {"run_id": run_id})

    def _transcribe(self, payload):
        run = self.runs.get(payload["run_id"])
        client = self.runs.runtime_client(run)
        settings = run.request["settings"]
        audio = self.artifacts.resolve(f"{run.artifact_directory}/{run.result['output_audio']}")
        job = self._await_job(client, client.submit({"job_kind": "transcription", "settings": settings}, audio))
        directory = f"runs/{run.id}/analysis"
        self.artifacts.write(f"{directory}/telemetry.json", client.artifact(job["id"], "telemetry.json"))
        self.artifacts.write_json(f"{directory}/result.json", job["result"])
        self.runs.record_transcription(run.id, job["result"]["transcript"], job["result"]["segments"], f"{directory}/telemetry.json")
