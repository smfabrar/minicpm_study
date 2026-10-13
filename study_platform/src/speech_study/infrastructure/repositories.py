"""Repositories map rows to entities; business rules live in services."""

import json
import sqlite3
from dataclasses import asdict

from ..domain.errors import NotFoundError
from ..domain.models import Case, Condition, Review, Run, RunStatus, Study, StudyStatus, ToolDefinition, LibraryTool
from speech_contracts import RunSettings


def encode(entity) -> str:
    return json.dumps(asdict(entity), ensure_ascii=False)


class StudyRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def get(self, identifier: str, *, include_deleted=False) -> Study:
        row = self.connection.execute("SELECT payload FROM studies WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise NotFoundError("Study not found")
        study = self._decode(row)
        if study.deleted_at and not include_deleted:
            raise NotFoundError("Study is in Trash; restore it first")
        return study

    def list(self, *, deleted=False) -> list[Study]:
        studies = [self._decode(row) for row in self.connection.execute("SELECT payload FROM studies ORDER BY rowid DESC")]
        return [study for study in studies if bool(study.deleted_at) == deleted]

    def save(self, entity: Study) -> None:
        self.connection.execute("INSERT INTO studies VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (entity.id, encode(entity)))

    @staticmethod
    def _decode(row) -> Study:
        data = json.loads(row["payload"])
        data["settings"] = RunSettings.from_dict(data["settings"])
        data["status"] = StudyStatus(data["status"])
        return Study(**data)


class CaseRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def get(self, identifier: str) -> Case:
        row = self.connection.execute("SELECT payload FROM cases WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise NotFoundError("Case not found")
        return Case(**json.loads(row["payload"]))

    def list_for_study(self, study_id: str) -> list[Case]:
        return [Case(**json.loads(row["payload"])) for row in self.connection.execute("SELECT payload FROM cases WHERE study_id=? ORDER BY rowid", (study_id,))]

    def save(self, entity: Case) -> None:
        self.connection.execute("INSERT INTO cases VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (entity.id, entity.study_id, encode(entity)))

    def delete(self, identifier: str) -> None:
        self.connection.execute("DELETE FROM cases WHERE id=?", (identifier,))


class ToolRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def get(self, identifier: str) -> ToolDefinition:
        row = self.connection.execute("SELECT payload FROM tools WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise NotFoundError("Tool not found")
        return ToolDefinition(**json.loads(row["payload"]))

    def list_for_study(self, study_id: str) -> list[ToolDefinition]:
        return [ToolDefinition(**json.loads(row["payload"])) for row in self.connection.execute("SELECT payload FROM tools WHERE study_id=? ORDER BY rowid", (study_id,))]

    def save(self, entity: ToolDefinition) -> None:
        self.connection.execute("INSERT INTO tools VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,payload=excluded.payload", (entity.id, entity.study_id, entity.name, encode(entity)))

    def delete(self, identifier: str) -> None:
        self.connection.execute("DELETE FROM tools WHERE id=?", (identifier,))


class RunRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def get(self, identifier: str) -> Run:
        row = self.connection.execute("SELECT payload FROM runs WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise NotFoundError("Run not found")
        return self._decode(row)

    def list_for_study(self, study_id: str) -> list[Run]:
        return [self._decode(row) for row in self.connection.execute("SELECT payload FROM runs WHERE study_id=? ORDER BY rowid DESC", (study_id,))]

    def list_active(self) -> list[Run]:
        return [run for row in self.connection.execute("SELECT payload FROM runs") if (run := self._decode(row)).status in {RunStatus.QUEUED, RunStatus.RUNNING}]

    def save(self, entity: Run) -> None:
        self.connection.execute("INSERT INTO runs VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (entity.id, entity.study_id, entity.case_id, encode(entity)))

    @staticmethod
    def _decode(row) -> Run:
        data = json.loads(row["payload"])
        data["condition"] = Condition(data["condition"])
        data["status"] = RunStatus(data["status"])
        data["study_status"] = StudyStatus(data["study_status"])
        if data.get("review"):
            data["review"] = Review(**data["review"])
        return Run(**data)


class LibraryToolRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def get(self, identifier: str) -> LibraryTool:
        row = self.connection.execute("SELECT payload FROM tool_library WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise NotFoundError("Library tool not found")
        return LibraryTool(**json.loads(row["payload"]))

    def list(self) -> list[LibraryTool]:
        return [LibraryTool(**json.loads(row["payload"])) for row in
                self.connection.execute("SELECT payload FROM tool_library ORDER BY rowid DESC")]

    def save(self, entity: LibraryTool) -> None:
        self.connection.execute("INSERT INTO tool_library VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (entity.id, encode(entity)))

    def delete(self, identifier: str) -> None:
        self.get(identifier)
        self.connection.execute("DELETE FROM tool_library WHERE id=?", (identifier,))
