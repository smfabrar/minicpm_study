"""FastAPI application factory and HTTP error mapping."""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .api import runs, studies, system
from .container import ApplicationServices
from .domain.errors import ConflictError, NotFoundError, RuntimeConnectionError


def create_app(data_root: Path | None = None, frontend: Path | None = None) -> FastAPI:
    container = ApplicationServices.create(data_root or Path(os.environ.get("SPEECH_STUDY_DATA", "data/platform")))

    @asynccontextmanager
    async def lifespan(app):
        container.runs.recover()
        container.operations.start()
        yield
        container.operations.close()

    app = FastAPI(title="Speech Study", version="0.1.0", lifespan=lifespan)
    app.state.services = container

    @app.middleware("http")
    async def same_origin_writes(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-origin writes are not allowed"}, status_code=403)
        return await call_next(request)

    for exception, status in ((NotFoundError, 404), (ConflictError, 409), (RuntimeConnectionError, 503), (ValueError, 400)):
        def handler(request, exc, status_code=status):
            return JSONResponse({"detail": str(exc)}, status_code=status_code)
        app.add_exception_handler(exception, handler)

    app.include_router(studies.router)
    app.include_router(runs.router)
    app.include_router(system.router)
    directory = frontend or Path(os.environ.get("SPEECH_STUDY_FRONTEND", str(Path(__file__).resolve().parents[2] / "frontend" / "dist")))
    if (directory / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=directory / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def index(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Route not found"}, status_code=404)
        file = directory / "index.html"
        if file.is_file():
            return FileResponse(file)
        return HTMLResponse("<html><head><title>Speech Study</title></head><body style='font-family:system-ui;max-width:700px;margin:80px auto'><h1>Speech Study backend is running</h1><p>Build the React frontend: <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>.</p><p><a href='/docs'>API documentation</a></p></body></html>")

    return app
