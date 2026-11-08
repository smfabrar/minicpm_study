from fastapi import APIRouter

from .dependencies import ServiceContainer
from .schemas import ToolInput
from ..services.default_tools import default_tools

router = APIRouter(prefix="/api/tools", tags=["tool library"])


@router.get("")
def list_tools(container: ServiceContainer):
    return container.library.list()


@router.get("/presets")
def tool_presets():
    return [ToolInput(**definition) for definition in default_tools()]


@router.post("", status_code=201)
def create_tool(body: ToolInput, container: ServiceContainer):
    return container.library.save(body.model_dump())


@router.put("/{tool_id}")
def update_tool(tool_id: str, body: ToolInput, container: ServiceContainer):
    return container.library.save(body.model_dump(), tool_id)


@router.delete("/{tool_id}", status_code=204)
def delete_tool(tool_id: str, container: ServiceContainer):
    container.library.delete(tool_id)
