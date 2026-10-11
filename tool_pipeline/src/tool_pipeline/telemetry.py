"""Buffered operation traces and explicitly qualified memory observations."""

import contextvars
import json
import os
import platform
import resource
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

_parent = contextvars.ContextVar("trace_parent", default=None)


@dataclass
class Span:
    id: str
    name: str
    parent_id: str | None
    start_ns: int
    thread_id: int
    attributes: dict
    end_ns: int | None = None
    status: str = "running"

    def to_dict(self):
        return {**self.__dict__, "duration_ns": None if self.end_ns is None else self.end_ns - self.start_ns,
                "process_id": os.getpid()}


class TraceRecorder:
    def __init__(self, maximum_records=100000):
        self.origin_ns = time.perf_counter_ns()
        self.clock_id = f"{platform.node()}:{os.getpid()}:perf_counter"
        self.spans = []
        self.events = []
        self.memory = []
        self.dropped_records = 0
        self.maximum_records = maximum_records
        self.lock = threading.RLock()

    @contextmanager
    def span(self, name, **attributes):
        span = Span(uuid.uuid4().hex, name, _parent.get(), time.perf_counter_ns(), threading.get_ident(), attributes)
        with self.lock:
            if len(self.spans) < self.maximum_records:
                self.spans.append(span)
            else:
                self.dropped_records += 1
        token = _parent.set(span.id)
        try:
            yield span
            span.status = "ok"
        except BaseException as exc:
            span.status = "error"
            span.attributes["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            span.end_ns = time.perf_counter_ns()
            _parent.reset(token)

    def event(self, name, **attributes):
        with self.lock:
            if len(self.events) < self.maximum_records:
                self.events.append({"name": name, "at_ns": time.perf_counter_ns(), "parent_id": _parent.get(), "attributes": attributes})
            else:
                self.dropped_records += 1

    def sample(self, sample):
        with self.lock:
            if len(self.memory) < self.maximum_records:
                self.memory.append(sample)
            else:
                self.dropped_records += 1

    def snapshot(self):
        with self.lock:
            return {"origin_ns": self.origin_ns, "clock_id": self.clock_id,
                    "clock_resolution_ns": time.get_clock_info("perf_counter").resolution * 1e9,
                    "spans": [s.to_dict() for s in self.spans], "events": list(self.events),
                    "memory": list(self.memory), "dropped_records": self.dropped_records}

    def write(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.snapshot(), ensure_ascii=False))
        os.replace(temporary, path)

    def chrome_trace(self):
        snapshot = self.snapshot()
        return {"traceEvents": [{"name": s["name"], "cat": "inference", "ph": "X", "pid": s["process_id"], "tid": s["thread_id"], "ts": (s["start_ns"] - self.origin_ns) / 1000, "dur": (s["duration_ns"] or 0) / 1000, "args": s["attributes"]} for s in snapshot["spans"] if s["end_ns"] is not None]}


class MemorySampler:
    def __init__(self, trace, interval_ms=20, telemetry_path=None):
        self.trace = trace
        self.interval = interval_ms / 1000
        self.telemetry_path = telemetry_path
        self.stop_event = threading.Event()
        self.thread = None
        self.sample_cost_ns = 0
        self.flush_cost_ns = 0
        self.psutil = None
        self.nvml = None
        self.reason = {}
        self.devices = []
        try:
            import psutil
            self.psutil = psutil.Process()
        except ImportError:
            self.reason["rss_bytes"] = "psutil is not installed; only OS lifetime peak RSS is available"
        try:
            import pynvml
            pynvml.nvmlInit()
            self.nvml = pynvml
            for index in range(pynvml.nvmlDeviceGetCount()):
                handle = pynvml.nvmlDeviceGetHandleByIndex(index)
                self.devices.append({"nvml_device_index": index, "name": pynvml.nvmlDeviceGetName(handle), "uuid": pynvml.nvmlDeviceGetUUID(handle), "total_bytes": pynvml.nvmlDeviceGetMemoryInfo(handle).total})
        except Exception as exc:
            self.reason["gpu_memory"] = str(exc)

    def __enter__(self):
        self.thread = threading.Thread(target=self._loop, daemon=True, name="memory-sampler")
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop_event.set()
        self.thread.join(timeout=5)
        if self.nvml:
            self.nvml.nvmlShutdown()

    def _observe(self):
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        record = {"at_ns": time.perf_counter_ns(), "process_id": os.getpid(),
                  "rss_bytes": None, "os_lifetime_peak_rss_bytes": int(peak * (1 if platform.system() == "Darwin" else 1024)),
                  "gpus": []}
        if self.psutil:
            record["rss_bytes"] = self.psutil.memory_info().rss
            record["cpu_percent"] = self.psutil.cpu_percent()
        if self.nvml:
            for i in range(self.nvml.nvmlDeviceGetCount()):
                handle = self.nvml.nvmlDeviceGetHandleByIndex(i)
                info = self.nvml.nvmlDeviceGetMemoryInfo(handle)
                own = None
                try:
                    values = [process.usedGpuMemory for process in self.nvml.nvmlDeviceGetComputeRunningProcesses(handle) if process.pid == os.getpid()]
                    if any(value is None or value > info.total for value in values):
                        self.reason["process_gpu_memory"] = "NVML returned an unavailable process allocation"
                    else:
                        own = sum(values)
                except Exception as exc:
                    self.reason["process_gpu_memory"] = str(exc)
                record["gpus"].append({"device": i, "device_used_bytes": info.used, "process_used_bytes": own})
        self.trace.sample(record)

    def _loop(self):
        last_flush = 0
        while not self.stop_event.is_set():
            started = time.perf_counter_ns()
            try:
                self._observe()
            except Exception as exc:
                self.reason["sampler"] = str(exc)
            self.sample_cost_ns += time.perf_counter_ns() - started
            if self.telemetry_path and time.monotonic() - last_flush >= 0.5:
                started = time.perf_counter_ns()
                try:
                    self.trace.write(self.telemetry_path)
                except OSError as exc:
                    self.reason["trace_flush"] = str(exc)
                self.flush_cost_ns += time.perf_counter_ns() - started
                last_flush = time.monotonic()
            self.stop_event.wait(self.interval)

    def report(self):
        samples = self.trace.snapshot()["memory"]
        rss = [s["rss_bytes"] for s in samples if s["rss_bytes"] is not None]
        gpu = [sum(g["process_used_bytes"] for g in sample["gpus"] if g["process_used_bytes"] is not None) for sample in samples if any(g["process_used_bytes"] is not None for g in sample["gpus"])]
        return {"devices": self.devices, "requested_interval_ms": self.interval * 1000, "sample_count": len(samples),
                "observed_peak_rss_bytes": max(rss) if rss else None,
                "observed_peak_process_gpu_bytes": max(gpu) if gpu else None,
                "sampler_cpu_elapsed_ns": self.sample_cost_ns, "trace_flush_elapsed_ns": self.flush_cost_ns,
                "unavailable": self.reason, "peak_kind": "sampled; transient allocations may be missed",
                "native_memory": "Native MiniCPM is a separate process; requires native-host telemetry"}
