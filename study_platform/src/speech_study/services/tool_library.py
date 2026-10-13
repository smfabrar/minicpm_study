"""Reusable definitions are templates; study tools are independent copies."""

from dataclasses import replace

from speech_contracts import validate_definition
from ..domain.models import LibraryTool, new_id, utc_now
from ..infrastructure.unit_of_work import UnitOfWork


class ToolLibraryService:
    def __init__(self, database, studies):
        self.database = database
        self.studies = studies

    def list(self):
        with UnitOfWork(self.database) as work:
            return work.library.list()

    def save(self, definition: dict, tool_id: str | None = None):
        validate_definition(definition)
        with UnitOfWork(self.database) as work:
            tool = (replace(work.library.get(tool_id), definition=definition, updated_at=utc_now())
                    if tool_id else LibraryTool(new_id(), definition))
            work.library.save(tool)
        return tool

    def delete(self, tool_id):
        with UnitOfWork(self.database) as work:
            work.library.delete(tool_id)

    def attach(self, study_id, tool_id):
        with UnitOfWork(self.database) as work:
            template = work.library.get(tool_id)
        return self.studies.save_tool(study_id, {**template.definition, "library_id": template.id})
