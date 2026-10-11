"""Time platform-side audio uploads without depending on inference telemetry."""

import os
import platform
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

from ..artifacts import ArtifactStore


@dataclass(slots=True)
class PreparationSpan:
    name: str
    parent_id: str | None
    attributes: dict
    id: str = field(default_factory=lambda: uuid4().hex)
    start_ns: int = field(default_factory=time.perf_counter_ns)
    end_ns: int | None = None
    status: str = "running"
    thread_id: int = field(default_factory=threading.get_ident)
    process_id: int = field(default_factory=os.getpid)


class PreparationTrace:
    def __init__(self) -> None:
        self.origin_ns = time.perf_counter_ns()
        self.spans: list[PreparationSpan] = []
        self._parents: list[str] = []

    @contextmanager
    def span(self, name: str, **attributes):
        span = PreparationSpan(name, self._parents[-1] if self._parents else None, attributes)
        self.spans.append(span)
        self._parents.append(span.id)
        try:
            yield span
            span.status = "ok"
        except Exception as exc:
            span.status = "error"
            span.attributes["error"] = str(exc)
            raise
        finally:
            span.end_ns = time.perf_counter_ns()
            self._parents.pop()

    def write(self, path: Path) -> None:
        spans = [
            {**asdict(span), "duration_ns": None if span.end_ns is None else span.end_ns - span.start_ns}
            for span in self.spans
        ]
        ArtifactStore(path.parent).write_json(path.name, {
            "origin_ns": self.origin_ns,
            "clock_id": f"{platform.node()}:{os.getpid()}:perf_counter",
            "clock_resolution_ns": time.get_clock_info("perf_counter").resolution * 1e9,
            "scope": "platform_preparation",
            "spans": spans,
            "events": [],
            "memory": [],
            "dropped_records": 0,
        })
