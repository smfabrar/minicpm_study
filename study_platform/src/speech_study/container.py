"""Composition root: construct concrete adapters and application services."""

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from .artifacts import ArtifactStore
from .infrastructure.background import BackgroundQueue
from .infrastructure.database import Database
from .infrastructure.runtime_client import RuntimeConnection
from .services.analysis import AnalysisService
from .services.preparation import PreparationService
from .services.runs import RunService
from .services.studies import StudyService


class ConnectionSettings:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        saved = json.loads(path.read_text()) if path.is_file() else {}
        self.connection = RuntimeConnection(os.environ.get("SPEECH_RUNTIME_URL", saved.get("url", "http://127.0.0.1:8766")), os.environ.get("SPEECH_RUNTIME_TOKEN", ""))

    def get(self) -> RuntimeConnection:
        with self.lock:
            return self.connection

    def set_url(self, url: str) -> RuntimeConnection:
        connection = RuntimeConnection(url.rstrip("/"), self.connection.token)
        with self.lock:
            self.connection = connection
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"url": connection.url}))
        return connection


@dataclass(slots=True)
class ApplicationServices:
    studies: StudyService
    runs: RunService
    preparation: PreparationService
    analysis: AnalysisService
    operations: BackgroundQueue
    connection: ConnectionSettings
    artifacts: ArtifactStore

    @classmethod
    def create(cls, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        database = Database(root / "studies.sqlite")
        artifacts = ArtifactStore(root / "artifacts")
        operations = BackgroundQueue(root / "operations")
        connection = ConnectionSettings(root / "connection.json")
        studies = StudyService(database, artifacts)
        runs = RunService(database, artifacts, operations, connection.get)
        preparation = PreparationService(studies, runs, artifacts, operations, connection.get)
        return cls(studies, runs, preparation, AnalysisService(studies, artifacts), operations, connection, artifacts)
