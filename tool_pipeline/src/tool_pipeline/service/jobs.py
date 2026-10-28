"""Persistent runtime jobs, executed serially in separate worker processes."""

import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict

from speech_contracts import RunRequest, RunSettings

from .storage import ArtifactStore
from .storage import utc_now as now


class JobManager:
    def __init__(self, root):
        self.store = ArtifactStore(root)
        self.worker_lock = threading.Lock()
        self.stopped = threading.Event()
        self.processes = set()
        self.state_lock = threading.RLock()
        for path in self.store.root.glob("*/job.json"):
            job = json.loads(path.read_text())
            if job["status"] in {"queued", "running"}:
                job.update(status="interrupted", error="Runtime restarted before this worker finished")
                self.store.write_json(str(path.relative_to(self.store.root)), job)

    def health(self):
        dependencies = (
            "kokoro", "torch", "transformers", "bitsandbytes", "faster_whisper", "websockets", "psutil", "pynvml"
        )
        return {
            "status": "ready",
            "version": "0.1.0",
            "boundary": "independent audio-in/audio-out worker",
            "dependencies": {
                name: importlib.util.find_spec(name) is not None for name in dependencies
            },
            "active_jobs": len(self.processes),
            "host": os.uname().nodename,
        }

    def create(self, payload):
        payload = dict(payload)
        kind = payload.get("job_kind", "inference")
        if kind not in {"inference", "synthesis", "transcription"}:
            raise ValueError("Unknown job kind")
        payload["settings"] = asdict(RunSettings.from_dict(payload.get("settings", {})))
        job_id = uuid.uuid4().hex
        directory = self.store.resolve(job_id)
        directory.mkdir()
        try:
            if kind in {"inference", "transcription"}:
                audio = base64.b64decode(payload.pop("audio_base64", ""), validate=True)
                if not audio or len(audio) > 50 * 1024 * 1024:
                    raise ValueError("Audio must contain 1 byte to 50 MiB")
                checksum = hashlib.sha256(audio).hexdigest()
                if payload.get("audio_sha256") and checksum != payload["audio_sha256"]:
                    raise ValueError("Transferred audio checksum does not match")
                self.store.write(f"{job_id}/input.wav", audio)
                payload["audio_path"] = str(directory / "input.wav")
                payload["audio_sha256"] = checksum
            elif (
                not isinstance(payload.get("question"), str)
                or not 0 < len(payload["question"].strip()) <= 4000
            ):
                raise ValueError("Question must contain 1–4000 characters")
            if kind == "inference":
                RunRequest.from_dict(payload)
            self.store.write_json(f"{job_id}/request.json", payload)
            job = {
                "id": job_id, "kind": kind, "status": "queued", "created_at": now(),
                "result": None, "error": None,
            }
            self.store.write_json(f"{job_id}/job.json", job)
        except Exception:
            import shutil
            shutil.rmtree(directory)
            raise
        threading.Thread(
            target=self._execute, args=(job_id,), daemon=True, name=f"job-{job_id[:8]}"
        ).start()
        return job

    def _execute(self, job_id):
        with self.worker_lock:
            if self.stopped.is_set():
                return
            job = self.get(job_id)
            job.update(status="running", started_at=now())
            self.store.write_json(f"{job_id}/job.json", job)
            directory = self.store.resolve(job_id)
            started = time.perf_counter_ns()
            try:
                payload = json.loads((directory / "request.json").read_text())
                timeout = payload.get("settings", {}).get("timeout_seconds", 240) + 300
                with (directory / "worker.log").open("w") as log:
                    command = [
                        sys.executable, "-m", "tool_pipeline.service.worker",
                        "--request", str(directory / "request.json"),
                        "--output", str(directory),
                    ]
                    with self.state_lock:
                        if self.stopped.is_set():
                            raise RuntimeError("Runtime is shutting down")
                        process = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
                        self.processes.add(process)
                    try:
                        process.wait(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        self._stop_worker(process)
                        raise TimeoutError("Worker exceeded the job deadline; partial artifacts retained")
                    finally:
                        with self.state_lock:
                            self.processes.discard(process)
                if not (directory / "result.json").is_file():
                    raise RuntimeError("Worker exited without a result; inspect worker.log")
                result = json.loads((directory / "result.json").read_text())
                job.update(status=result["status"], result=result, error=result.get("error"))
            except Exception as exc:
                job.update(status="failed", error=str(exc))
            job.update(finished_at=now(), worker_elapsed_ms=(time.perf_counter_ns() - started) / 1e6)
            self.store.write_json(f"{job_id}/job.json", job)

    def get(self, job_id):
        if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
            raise KeyError("Unknown job")
        path = self.store.resolve(f"{job_id}/job.json")
        if not path.is_file():
            raise KeyError("Unknown job")
        job = json.loads(path.read_text())
        job["artifacts"] = [
            file.name for file in path.parent.iterdir()
            if file.is_file()
            and file.suffix in {".wav", ".json", ".log"}
            and file.name not in {"request.json", "job.json"}
        ]
        return job

    @staticmethod
    def _stop_worker(process):
        """Capture ownership before stopping the parent, then reap its tool workers."""
        import signal
        import psutil

        try:
            children = psutil.Process(process.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            children = []
        for child in reversed(children):
            try:
                # Python tools own a process group; include descendants they spawned.
                if os.getpgid(child.pid) == child.pid:
                    os.killpg(child.pid, signal.SIGKILL)
                else:
                    child.kill()
            except (ProcessLookupError, psutil.NoSuchProcess):
                pass
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def close(self):
        with self.state_lock:
            self.stopped.set()
            processes = list(self.processes)
        for process in processes:
            self._stop_worker(process)
