"""Serial background work with persistent status and per-operation logs."""

import contextvars
import json
import queue
import threading
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..artifacts import ArtifactStore
from ..domain.errors import NotFoundError
from ..domain.models import new_id, utc_now

_current = contextvars.ContextVar("current_operation", default=None)


@dataclass(slots=True)
class Operation:
    id: str
    kind: str
    payload: dict
    status: str = "queued"
    message: str = "Waiting"
    created_at: str = field(default_factory=utc_now)
    finished_at: str | None = None
    started_at: str | None = None
    remote_job_id: str | None = None
    runtime_url: str = ""
    remote_status: str | None = None
    artifact_directory: str | None = None
    queue_position: int | None = None


class BackgroundQueue:
    def __init__(self, root: Path, *, store=None):
        self.store = store or ArtifactStore(root)
        self.queue = queue.Queue()
        self.handlers = {}
        self.stopped = threading.Event()
        self.lock = threading.RLock()
        for operation in self.list(limit=None):
            if operation.status in {"queued", "running"}:
                operation.status = "interrupted"
                operation.message = "Platform restarted. Run attempts with remote job IDs can be resumed."
                operation.finished_at = utc_now()
                self._save(operation)
                self._log(operation, operation.message)

    def register(self, kind, handler):
        self.handlers[kind] = handler

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True, name="platform-operations")
        self.thread.start()

    def submit(self, kind: str, payload: dict) -> Operation:
        if kind not in self.handlers:
            raise ValueError(f"Unknown operation: {kind}")
        with self.lock:
            operation = Operation(new_id(), kind, payload)
            self._save(operation)
            self._log(operation, "Queued", payload)
            self.queue.put(operation)
        return operation

    def _save(self, operation):
        with self.lock:
            self.store.write_json(operation.id + ".json", asdict(operation))

    def _log(self, operation, message, details=None):
        with self.lock:
            relative = operation.id + ".log"
            path = self.store.resolve(relative)
            previous = path.read_bytes() if path.is_file() else b""
            line = json.dumps({"at": utc_now(), "message": message, "details": details}, ensure_ascii=False) + "\n"
            self.store.write(relative, previous + line.encode())

    def report(self, message, *, details=None, **changes):
        operation = _current.get()
        if operation is None:
            return
        with self.lock:
            operation.message = message
            for key, value in changes.items():
                setattr(operation, key, value)
            self._save(operation)
            self._log(operation, message, details)

    def get(self, identifier: str) -> Operation:
        if len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier):
            raise NotFoundError("Operation not found")
        with self.lock:
            path = self.store.resolve(identifier + ".json")
            if not path.is_file():
                raise NotFoundError("Operation not found")
            return Operation(**json.loads(path.read_text()))

    def logs(self, identifier: str) -> str:
        self.get(identifier)
        path = self.store.resolve(identifier + ".log")
        if not path.is_file():
            return ""
        with self.lock, path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 65536))
            return stream.read().decode(errors="replace")

    def list(self, limit=100) -> list[Operation]:
        with self.lock:
            operations = [Operation(**json.loads(p.read_text())) for p in self.store.root.glob("*.json")]
        queued = sorted((o for o in operations if o.status == "queued"), key=lambda o: o.created_at)
        for position, operation in enumerate(queued, 1):
            operation.queue_position = position
        ordered = sorted(operations, key=lambda o: o.created_at, reverse=True)
        if limit is None:
            return ordered
        active = [o for o in ordered if o.status in {"queued", "running"}]
        history = [o for o in ordered if o.status not in {"queued", "running"}][:limit]
        return active + history

    def _loop(self):
        while not self.stopped.is_set():
            try:
                operation = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            operation.status = "running"
            operation.started_at = utc_now()
            operation.message = "Starting"
            self._save(operation)
            self._log(operation, "Started")
            token = _current.set(operation)
            try:
                self.handlers[operation.kind](operation.payload)
                operation.status = "interrupted" if self.stopped.is_set() else "complete"
                operation.message = "Platform stopping" if self.stopped.is_set() else "Finished"
            except Exception as exc:
                operation.status = "failed"
                operation.message = f"{type(exc).__name__}: {exc}"
                self._log(operation, operation.message, {"traceback": traceback.format_exc()})
            finally:
                _current.reset(token)
                operation.finished_at = utc_now()
                self._save(operation)
                self._log(operation, operation.message)
                self.queue.task_done()

    def close(self):
        self.stopped.set()
