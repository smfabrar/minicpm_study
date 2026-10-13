"""Execute a frozen, user-authored Python tool outside the inference process."""

import asyncio
import hashlib
import json
import os
import signal
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4


class PythonToolExecutor:
    def __init__(self, output_dir: Path | None, trace):
        self.output_dir = output_dir
        self.trace = trace

    async def execute(self, tool: dict, arguments: dict) -> dict:
        if self.output_dir is None:
            with tempfile.TemporaryDirectory(prefix="python-tool-") as directory:
                return await self._execute(tool, arguments, Path(directory))
        return await self._execute(tool, arguments, self.output_dir)

    async def _execute(self, tool, arguments, directory):
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"tool-{tool['name']}-{uuid4().hex[:8]}"
        request_path = directory / f"{stem}-request.json"
        result_path = directory / f"{stem}-result.json"
        log_path = directory / f"{stem}.log"
        source_hash = hashlib.sha256(tool["python_code"].encode()).hexdigest()
        request_path.write_text(json.dumps({"source": tool["python_code"], "arguments": arguments,
                                           "source_sha256": source_hash}, indent=2))
        record = {"tool": tool["name"], "arguments": arguments, "source_sha256": source_hash,
                  "request_file": request_path.name, "log_file": log_path.name,
                  "timeout_seconds": tool.get("timeout_seconds", 10), "status": "running"}
        started = time.perf_counter_ns()
        process = None
        result = None
        try:
            with log_path.open("wb") as log:
                with self.trace.span("tool.python_process", tool=tool["name"], source_sha256=source_hash):
                    process = await asyncio.create_subprocess_exec(
                        sys.executable, "-u", "-m", "tool_pipeline.python_worker",
                        str(request_path), str(result_path), stdout=log, stderr=log,
                        start_new_session=True,
                    )
                    await asyncio.wait_for(process.wait(), timeout=record["timeout_seconds"])
                if not result_path.is_file() or result_path.stat().st_size > 1024 * 1024:
                    raise RuntimeError("Python tool returned no usable result; inspect its log")
                result = json.loads(result_path.read_text())
                if process.returncode or result.get("error"):
                    raise RuntimeError(result.get("error") or f"Python tool exited with code {process.returncode}")
                record["status"] = "complete"
                return {**result, "source_sha256": source_hash, "execution_file": f"{stem}-execution.json"}
        except asyncio.TimeoutError as exc:
            record.update(status="failed", error="Python tool exceeded its execution timeout")
            raise TimeoutError(record["error"]) from exc
        except BaseException as exc:
            record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            # Reap the tool process and any children even on cancellation or timeout.
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
            record.update(elapsed_ms=(time.perf_counter_ns() - started) / 1e6, result=result)
            (directory / f"{stem}-execution.json").write_text(json.dumps(record, indent=2))
            self.trace.event("tool.python_finished", **record)
