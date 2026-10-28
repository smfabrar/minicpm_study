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
from .services.exports import ExportService
from .services.preparation import PreparationService
from .services.runs import RunService
from .services.studies import StudyService
from .services.tool_library import ToolLibraryService
from .services.operations import OperationService


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
    library: ToolLibraryService
    operation_details: OperationService
    exports: ExportService

    @classmethod
    def create(cls, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        uri = os.environ.get("SPEECH_MONGODB_URI", "")
        if uri:
            from .infrastructure.mongo import MongoDatabase
            from .infrastructure.gridfs_store import GridFSArtifactStore
            database = MongoDatabase(uri, os.environ.get("SPEECH_MONGODB_DATABASE", "minicpm_study"))
            artifacts = GridFSArtifactStore(root / "artifacts", database.db)
            operation_store = GridFSArtifactStore(root / "operations", database.db, "operations")
            operation_store.resolve(".")  # Recover operation history on a fresh machine.
        else:
            database = Database(root / "studies.sqlite")
            artifacts = ArtifactStore(root / "artifacts")
            operation_store = ArtifactStore(root / "operations")
        operations = BackgroundQueue(root / "operations", store=operation_store)
        connection = ConnectionSettings(root / "connection.json")
        studies = StudyService(database, artifacts, operations)
        runs = RunService(database, artifacts, operations, connection.get)
        preparation = PreparationService(studies, runs, artifacts, operations, connection.get)
        analysis = AnalysisService(studies, artifacts)
        return cls(studies, runs, preparation, analysis, operations, connection, artifacts,
                   ToolLibraryService(database, studies), OperationService(operations, connection.get, artifacts),
                   ExportService(studies, analysis, artifacts, operations))
