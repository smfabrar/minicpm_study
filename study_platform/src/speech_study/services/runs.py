"""Freeze run requests, submit them, and collect independent runtime evidence."""

import json
import random
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from speech_contracts import RunRequest
from ..artifacts import ArtifactStore
from ..infrastructure.database import Database
from ..infrastructure.background import BackgroundQueue

from ..domain.errors import ConflictError, NotFoundError, RuntimeConnectionError
from ..domain.models import Condition, Review, Run, RunStatus, StudyStatus, new_id
from ..infrastructure.runtime_client import RuntimeClient, RuntimeConnection
from ..infrastructure.unit_of_work import UnitOfWork


class RunService:
    def __init__(self, database: Database, artifacts: ArtifactStore, operations: BackgroundQueue, connection_provider: Callable[[], RuntimeConnection]):
        self.database = database
        self.artifacts = artifacts
        self.operations = operations
        self.connection_provider = connection_provider
        operations.register("inference", self._execute)

    def get(self, run_id: str) -> Run:
        with UnitOfWork(self.database) as work:
            return work.runs.get(run_id)

    def _client(self, run: Run | None = None) -> RuntimeClient:
        current = self.connection_provider()
        return RuntimeClient(RuntimeConnection(run.runtime_url if run and run.runtime_url else current.url, current.token))

    def start(self, study_id: str, case_id: str, conditions: list[Condition]) -> list[Run]:
        if not conditions or len(set(conditions)) != len(conditions):
            raise ValueError("Select one or more distinct conditions")
        return self._enqueue(study_id, [(case_id, condition) for condition in conditions])

    def matrix(self, study_id: str) -> list[Run]:
        with UnitOfWork(self.database) as work:
            study = work.studies.get(study_id)
            if study.status != StudyStatus.FROZEN:
                raise ConflictError("Freeze the study before running the evaluation matrix")
            cases = [c for c in work.cases.list_for_study(study_id) if c.split == "evaluation"]
            order = [(case.id, condition) for _ in range(study.settings.repetitions) for case in cases for condition in Condition]
        random.Random(study.settings.seed).shuffle(order)
        return self._enqueue(study_id, order)

    def _enqueue(self, study_id: str, order: list[tuple[str, Condition]]) -> list[Run]:
        connection = self.connection_provider()
        RuntimeClient(connection).health()
        runs = []
        with UnitOfWork(self.database) as work:
            study = work.studies.get(study_id)
            cases = {case.id: case for case in work.cases.list_for_study(study_id)}
            tools = work.tools.list_for_study(study_id)
            snapshot = study.snapshot or {"settings": asdict(study.settings), "cases": [asdict(case) for case in cases.values()], "tools": [asdict(tool) for tool in tools]}
            checked = set()
            for case_id, condition in order:
                case = cases.get(case_id)
                if case is None:
                    raise NotFoundError("Case not found in this study")
                if case_id not in checked:
                    if not case.audio_path or not case.audio_sha256:
                        raise ValueError("Prepare audio before starting inference")
                    if self.artifacts.checksum(case.audio_path) != case.audio_sha256:
                        raise ValueError("Input audio changed since preparation")
                    checked.add(case_id)
                oracle = None
                if condition == Condition.REFERENCE:
                    oracle = case.oracle_result if case.category != "none" else None
                    if oracle is not None and not oracle.strip():
                        raise ValueError("Add a correct B2 reference result for this tool case")
                request = RunRequest(
                    condition=condition,
                    audio_path=case.audio_path,
                    audio_sha256=case.audio_sha256,
                    settings=study.settings,
                    tools=[asdict(tool) for tool in tools] if condition == Condition.PROPOSED else [],
                    oracle_result=oracle,
                ).to_payload()
                run = Run(new_id(), study_id, case_id, condition, request, snapshot, study.status, runtime_url=connection.url)
                work.runs.save(run)
                runs.append(run)
        for run in runs:
            self.operations.submit("inference", {"run_id": run.id})
        return runs

    def runtime_client(self, run: Run) -> RuntimeClient:
        return self._client(run)

    def record_transcription(self, run_id: str, transcript: str, segments: list[dict], trace_path: str) -> None:
        with UnitOfWork(self.database) as work:
            run = work.runs.get(run_id)
            run.output_transcript = transcript
            run.output_segments = segments
            run.analysis_trace = trace_path
            work.runs.save(run)

    def _save(self, run: Run) -> None:
        with UnitOfWork(self.database) as work:
            # Preserve reviews and output analysis added concurrently.
            current = work.runs.get(run.id)
            run.review = current.review
            run.output_transcript = current.output_transcript
            run.output_segments = current.output_segments
            run.analysis_trace = current.analysis_trace
            work.runs.save(run)

    def _execute(self, payload):
        run = self.get(payload["run_id"])
        client = self._client(run)
        directory = f"runs/{run.id}"
        self.artifacts.write_json(f"{directory}/request.json", run.request)
        try:
            if not run.runtime_job_id:
                checksum = self.artifacts.checksum(run.request["audio_path"])
                if checksum != run.request["audio_sha256"]:
                    raise ValueError("Input audio checksum changed before submission")
                job = client.submit({"job_kind": "inference", **run.request}, self.artifacts.resolve(run.request["audio_path"]))
                run.runtime_job_id = job["id"]
                run.status = RunStatus.RUNNING
                self._save(run)
            deadline = time.monotonic() + run.request["settings"]["timeout_seconds"] + 3600
            while True:
                job = client.job(run.runtime_job_id)
                if job["status"] not in {"queued", "running"}:
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError("Runtime polling deadline exceeded; the remote job ID is retained")
                if self.operations.stopped.wait(0.8):
                    return
            for name in job.get("artifacts", []):
                if Path(name).name != name or Path(name).suffix not in {".wav", ".json", ".log"}:
                    continue
                self.artifacts.write(f"{directory}/{name}", client.artifact(run.runtime_job_id, name))
            run.result = job.get("result")
            run.status = RunStatus(job["status"])
            run.error = job.get("error")
            run.artifact_directory = directory
            self.artifacts.write_json(f"{directory}/remote_job.json", job)
            self._save(run)
        except Exception as exc:
            run.status = RunStatus.INTERRUPTED if isinstance(exc, RuntimeConnectionError) and run.runtime_job_id else RunStatus.FAILED
            run.error = f"{type(exc).__name__}: {exc}"
            run.artifact_directory = directory
            self._save(run)
            raise

    def telemetry(self, run_id: str) -> dict:
        run = self.get(run_id)
        local = self.artifacts.resolve(f"runs/{run.id}/telemetry.json")
        if local.is_file():
            return json.loads(local.read_text())
        if run.runtime_job_id:
            return self._client(run).telemetry(run.runtime_job_id)
        return {"origin_ns": 0, "clock_id": "not_started", "clock_resolution_ns": None, "spans": [], "events": [], "memory": [], "dropped_records": 0}

    def review(self, run_id: str, review: Review) -> Run:
        if review.verdict not in {"correct", "incorrect", "partial", "silent", "unreviewed"}:
            raise ValueError("Unknown verdict")
        if review.relevant_fact_ms is not None and review.relevant_fact_ms < 0:
            raise ValueError("Relevant-fact time cannot be negative")
        with UnitOfWork(self.database) as work:
            run = work.runs.get(run_id)
            run.review = review
            work.runs.save(run)
        return run

    def resume(self, run_id: str):
        run = self.get(run_id)
        if not run.runtime_job_id or run.status not in {RunStatus.INTERRUPTED, RunStatus.RUNNING}:
            raise ConflictError("Only an interrupted attempt with a remote job ID can be resumed")
        if any(operation.kind == "inference" and operation.payload.get("run_id") == run_id and operation.status in {"queued", "running"} for operation in self.operations.list()):
            raise ConflictError("This run is already being collected")
        run.status = RunStatus.RUNNING
        self._save(run)
        return self.operations.submit("inference", {"run_id": run_id})

    def recover(self):
        with UnitOfWork(self.database) as work:
            active = work.runs.list_active()
            for run in active:
                run.status = RunStatus.INTERRUPTED
                run.error = "Platform restarted; resume this remote job or create a separate attempt"
                work.runs.save(run)
