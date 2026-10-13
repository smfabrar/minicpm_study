from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .dependencies import ServiceContainer
from .schemas import RuntimeInput
from ..domain.errors import RuntimeConnectionError
from ..infrastructure.runtime_client import RuntimeClient

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health():
    return {"status": "ready", "version": "0.1.0"}


@router.get("/runtime")
def runtime(container: ServiceContainer):
    connection = container.connection.get()
    try:
        return {"url": connection.url, "online": True, **RuntimeClient(connection).health()}
    except RuntimeConnectionError as exc:
        return {"url": connection.url, "online": False, "error": str(exc)}


@router.put("/runtime")
def update_runtime(body: RuntimeInput, container: ServiceContainer):
    connection = container.connection.set_url(body.url)
    return {"url": connection.url}


@router.get("/operations")
def operations(container: ServiceContainer):
    return container.operations.list()


@router.get("/operations/{operation_id}")
def operation(operation_id: str, container: ServiceContainer):
    return container.operation_details.get(operation_id)


@router.get("/artifacts/{path:path}")
def artifact(path: str, container: ServiceContainer):
    file = container.artifacts.resolve(path)
    if not file.is_file():
        raise HTTPException(404, "Artifact not found")
    return FileResponse(file)
