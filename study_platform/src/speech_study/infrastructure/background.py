"""Serial background operations with persistent, observable status."""

import json
import queue
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..artifacts import ArtifactStore
from ..domain.models import new_id, utc_now


@dataclass(slots=True)
class Operation:
    id: str
    kind: str
    payload: dict
    status: str = "queued"
    message: str = "Waiting"
    created_at: str = field(default_factory=utc_now)
    finished_at: str | None = None


class BackgroundQueue:
    def __init__(self, root: Path):
        self.store = ArtifactStore(root)
        self.queue = queue.Queue()
        self.handlers = {}
        self.stopped = threading.Event()
        for path in self.store.root.glob("*.json"):
            operation = Operation(**json.loads(path.read_text()))
            if operation.status in {"queued", "running"}:
                operation.status = "interrupted"
                operation.message = "Platform restarted. Run attempts with remote job IDs can be resumed."
                self._save(operation)

    def register(self, kind, handler):
        self.handlers[kind] = handler

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True, name="platform-operations")
        self.thread.start()

    def submit(self, kind: str, payload: dict) -> Operation:
        operation = Operation(new_id(), kind, payload)
        self._save(operation)
        self.queue.put(operation)
        return operation

    def _save(self, operation):
        self.store.write_json(operation.id + ".json", asdict(operation))

    def list(self) -> list[Operation]:
        return sorted([Operation(**json.loads(p.read_text())) for p in self.store.root.glob("*.json")], key=lambda o: o.created_at, reverse=True)[:100]

    def _loop(self):
        while not self.stopped.is_set():
            try:
                operation = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            operation.status = "running"
            operation.message = "Working"
            self._save(operation)
            try:
                self.handlers[operation.kind](operation.payload)
                operation.status = "complete"
                operation.message = "Finished"
            except Exception as exc:
                operation.status = "failed"
                operation.message = f"{type(exc).__name__}: {exc}"
            operation.finished_at = utc_now()
            self._save(operation)
            self.queue.task_done()

    def close(self):
        self.stopped.set()
