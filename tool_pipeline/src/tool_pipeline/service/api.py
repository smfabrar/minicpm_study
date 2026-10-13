"""FastAPI service for independently executable GPU jobs."""

import argparse
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse

from .jobs import JobManager


def create_app(root: Path | None = None, token: str | None = None) -> FastAPI:
    jobs = JobManager(root or Path(os.environ.get("SPEECH_RUNTIME_DATA", "data/runtime")))
    expected_token = token if token is not None else os.environ.get("SPEECH_RUNTIME_TOKEN", "")

    @asynccontextmanager
    async def lifespan(app):
        yield
        jobs.close()

    app = FastAPI(title="Speech inference runtime", version="0.1.0", lifespan=lifespan)

    def authenticate(authorization: str = Header(default="")):
        if expected_token and not hmac.compare_digest(authorization, "Bearer " + expected_token):
            raise HTTPException(403, "Invalid runtime token")

    @app.get("/health", dependencies=[Depends(authenticate)])
    def health():
        return jobs.health()

    @app.post("/jobs", status_code=202, dependencies=[Depends(authenticate)])
    def create_job(payload: dict):
        try:
            return jobs.create(payload)
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    def get_job(job_id):
        try:
            return jobs.get(job_id)
        except KeyError as exc:
            raise HTTPException(404, "Job not found") from exc

    @app.get("/jobs/{job_id}", dependencies=[Depends(authenticate)])
    def job(job_id: str):
        return get_job(job_id)

    @app.get("/jobs/{job_id}/telemetry", dependencies=[Depends(authenticate)])
    def telemetry(job_id: str):
        get_job(job_id)
        path = jobs.store.resolve(f"{job_id}/telemetry.json")
        return json.loads(path.read_text()) if path.is_file() else {"origin_ns": 0, "clock_id": "not_started", "clock_resolution_ns": None, "spans": [], "events": [], "memory": [], "dropped_records": 0}

    @app.get("/jobs/{job_id}/logs", dependencies=[Depends(authenticate)])
    def logs(job_id: str):
        job = get_job(job_id)
        output = {}
        for name in sorted(job["artifacts"]):
            if name.endswith(".log") and len(output) < 8:
                path = jobs.store.resolve(f"{job_id}/{name}")
                with path.open("rb") as stream:
                    stream.seek(max(0, path.stat().st_size - 32768))
                    output[name] = stream.read().decode(errors="replace")
        return output

    @app.get("/jobs/{job_id}/artifacts/{name}", dependencies=[Depends(authenticate)])
    def artifact(job_id: str, name: str):
        job = get_job(job_id)
        if name not in job["artifacts"] or Path(name).name != name:
            raise HTTPException(404, "Artifact not found")
        return FileResponse(jobs.store.resolve(f"{job_id}/{name}"))

    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description="GPU inference runtime")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--data", type=Path, default=Path("data/runtime"))
    args = parser.parse_args()
    uvicorn.run(create_app(args.data), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
