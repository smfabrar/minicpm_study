"""Read operation evidence without joining the inference execution path."""

import json
from dataclasses import asdict

from ..infrastructure.runtime_client import RuntimeClient, RuntimeConnection
from ..domain.errors import RuntimeConnectionError


class OperationService:
    def __init__(self, operations, connection_provider, artifacts):
        self.operations = operations
        self.connection_provider = connection_provider
        self.artifacts = artifacts

    def get(self, operation_id):
        operation = self.operations.get(operation_id)
        if operation.status == "queued":
            operation.queue_position = next((o.queue_position for o in self.operations.list() if o.id == operation_id), None)
        details = {**asdict(operation), "log": self.operations.logs(operation_id), "runtime": None, "runtime_logs": {}}
        if operation.artifact_directory:
            directory = self.artifacts.resolve(operation.artifact_directory)
            if directory.is_dir():
                for path in sorted(directory.glob("*.log"))[:8]:
                    with path.open("rb") as stream:
                        stream.seek(max(0, path.stat().st_size - 32768))
                        details["runtime_logs"][path.name] = stream.read().decode(errors="replace")
                job_path = directory / "remote_job.json"
                if job_path.is_file():
                    details["runtime"] = json.loads(job_path.read_text())
        if operation.remote_job_id and operation.runtime_url and operation.status in {"queued", "running", "interrupted"}:
            connection = RuntimeConnection(operation.runtime_url, self.connection_provider().token)
            client = RuntimeClient(connection)
            try:
                details["runtime"] = client.job(operation.remote_job_id)
                details["runtime_logs"] = client.logs(operation.remote_job_id)
            except RuntimeConnectionError as exc:
                details["runtime_error"] = str(exc)
        return details
