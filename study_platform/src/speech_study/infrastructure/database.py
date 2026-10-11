import sqlite3
from pathlib import Path


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS studies(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY, study_id TEXT NOT NULL REFERENCES studies(id), payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tools(id TEXT PRIMARY KEY, study_id TEXT NOT NULL REFERENCES studies(id), name TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(study_id,name));
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, study_id TEXT NOT NULL REFERENCES studies(id), case_id TEXT NOT NULL REFERENCES cases(id), payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS cases_study ON cases(study_id);
                CREATE INDEX IF NOT EXISTS runs_study ON runs(study_id);
            """)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection
