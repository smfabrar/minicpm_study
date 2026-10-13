"""One transaction groups repositories for an application operation."""

from .database import Database
from .repositories import CaseRepository, RunRepository, StudyRepository, ToolRepository, LibraryToolRepository


class UnitOfWork:
    def __init__(self, database: Database):
        self.database = database

    def __enter__(self):
        self.connection = self.database.connect()
        self.connection.execute("BEGIN IMMEDIATE")
        self.studies = StudyRepository(self.connection)
        self.cases = CaseRepository(self.connection)
        self.tools = ToolRepository(self.connection)
        self.runs = RunRepository(self.connection)
        self.library = LibraryToolRepository(self.connection)
        return self

    def __exit__(self, error_type, error, traceback):
        try:
            if error_type:
                self.connection.rollback()
            else:
                self.connection.commit()
        finally:
            self.connection.close()
