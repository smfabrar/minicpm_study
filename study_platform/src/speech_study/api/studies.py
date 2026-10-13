from dataclasses import asdict
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import Response
from .dependencies import ServiceContainer
from .schemas import CaseInput, RunCreate, StudyCreate, StudyUpdate, ToolInput, LibraryAttach
from ..services.templates import add_proposal_cases

router = APIRouter(prefix="/api/studies", tags=["studies"])


@router.get("")
def list_studies(container: ServiceContainer, deleted: bool = False):
    return container.studies.list(deleted=deleted)


@router.post("", status_code=201)
def create_study(body: StudyCreate, container: ServiceContainer):
    return container.studies.create(body.name, body.description, body.settings)


@router.get("/{study_id}")
def get_study(study_id: str, container: ServiceContainer):
    detail = container.studies.get(study_id)
    return {**asdict(detail.study), "cases": detail.cases, "tools": detail.tools, "runs": detail.runs}


@router.put("/{study_id}")
def update_study(study_id: str, body: StudyUpdate, container: ServiceContainer):
    return container.studies.update(study_id, body.model_dump(exclude_none=True, exclude_unset=True))


@router.post("/{study_id}/freeze")
def freeze(study_id: str, container: ServiceContainer):
    return container.studies.freeze(study_id)


@router.post("/{study_id}/clone", status_code=201)
def clone(study_id: str, container: ServiceContainer):
    return container.studies.clone(study_id)


@router.post("/{study_id}/template")
def template(study_id: str, container: ServiceContainer):
    return {"case_count": add_proposal_cases(container.studies, study_id)}


@router.post("/{study_id}/cases", status_code=201)
def create_case(study_id: str, body: CaseInput, container: ServiceContainer):
    return container.studies.save_case(study_id, body.model_dump())


@router.put("/{study_id}/cases/{case_id}")
def update_case(study_id: str, case_id: str, body: CaseInput, container: ServiceContainer):
    return container.studies.save_case(study_id, body.model_dump(), case_id)


@router.delete("/{study_id}/cases/{case_id}", status_code=204)
def delete_case(study_id: str, case_id: str, container: ServiceContainer):
    container.studies.delete_case(study_id, case_id)


@router.post("/{study_id}/cases/{case_id}/prepare", status_code=202)
def prepare(study_id: str, case_id: str, container: ServiceContainer):
    return container.preparation.prepare(study_id, case_id)


@router.post("/{study_id}/cases/{case_id}/audio")
async def upload(study_id: str, case_id: str, container: ServiceContainer, audio: UploadFile = File()):
    import asyncio
    content = await audio.read(50 * 1024 * 1024 + 1)
    return await asyncio.to_thread(container.preparation.upload, study_id, case_id, content)


@router.post("/{study_id}/tools", status_code=201)
def create_tool(study_id: str, body: ToolInput, container: ServiceContainer):
    return container.studies.save_tool(study_id, body.model_dump())


@router.put("/{study_id}/tools/{tool_id}")
def update_tool(study_id: str, tool_id: str, body: ToolInput, container: ServiceContainer):
    return container.studies.save_tool(study_id, body.model_dump(), tool_id)


@router.delete("/{study_id}/tools/{tool_id}", status_code=204)
def delete_tool(study_id: str, tool_id: str, container: ServiceContainer):
    container.studies.delete_tool(study_id, tool_id)


@router.post("/{study_id}/runs", status_code=202)
def start_run(study_id: str, body: RunCreate, container: ServiceContainer):
    return container.runs.start(study_id, body.case_id, body.conditions)


@router.post("/{study_id}/matrix", status_code=202)
def matrix(study_id: str, container: ServiceContainer):
    return container.runs.matrix(study_id)


@router.get("/{study_id}/analysis")
def analysis(study_id: str, container: ServiceContainer):
    return container.analysis.summarize(study_id)


@router.get("/{study_id}/export")
def export(study_id: str, container: ServiceContainer):
    return Response(container.exports.export(study_id), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="study-{study_id[:8]}.zip"'})


@router.delete("/{study_id}", status_code=204)
def delete_study(study_id: str, container: ServiceContainer):
    container.studies.delete(study_id)


@router.post("/{study_id}/restore")
def restore_study(study_id: str, container: ServiceContainer):
    return container.studies.restore(study_id)


@router.post("/{study_id}/tools/attach", status_code=201)
def attach_tool(study_id: str, body: LibraryAttach, container: ServiceContainer):
    return container.library.attach(study_id, body.library_id)
