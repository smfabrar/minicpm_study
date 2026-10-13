"""HTTP adapter for a remote runtime; inference has no platform callbacks."""

import base64
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ..domain.errors import RuntimeConnectionError


@dataclass(frozen=True, slots=True)
class RuntimeConnection:
    url: str = "http://127.0.0.1:8766"
    token: str = ""

    def __post_init__(self):
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Runtime URL must be an HTTP(S) origin without credentials")


class RuntimeClient:
    def __init__(self, connection: RuntimeConnection):
        self.connection = connection

    def _request(self, method: str, path: str, payload=None, *, binary=False):
        headers = {"Authorization": "Bearer " + self.connection.token} if self.connection.token else {}
        try:
            with httpx.Client(timeout=60 if method == "POST" else 10, trust_env=False) as client:
                response = client.request(method, self.connection.url.rstrip("/") + path, json=payload, headers=headers)
                response.raise_for_status()
                return response.content if binary else response.json()
        except httpx.HTTPStatusError as exc:
            try:
                reason = exc.response.json().get("detail", exc.response.text)
            except ValueError:
                reason = exc.response.text
            raise RuntimeConnectionError(f"Runtime returned {exc.response.status_code}: {reason}") from exc
        except httpx.HTTPError as exc:
            raise RuntimeConnectionError(f"Cannot reach the GPU runtime at {self.connection.url}. Start it or connect the SSH tunnel. ({type(exc).__name__})") from exc

    def health(self) -> dict:
        return self._request("GET", "/health")

    def submit(self, request: dict, audio: Path | None = None) -> dict:
        payload = dict(request)
        if audio:
            payload["audio_base64"] = base64.b64encode(audio.read_bytes()).decode()
            payload.pop("audio_path", None)
        return self._request("POST", "/jobs", payload)

    def job(self, job_id: str) -> dict:
        return self._request("GET", f"/jobs/{job_id}")

    def telemetry(self, job_id: str) -> dict:
        return self._request("GET", f"/jobs/{job_id}/telemetry")

    def artifact(self, job_id: str, name: str) -> bytes:
        if Path(name).name != name:
            raise ValueError("Artifact names cannot include directories")
        return self._request("GET", f"/jobs/{job_id}/artifacts/{name}", binary=True)


    def logs(self, job_id: str) -> dict:
        return self._request("GET", f"/jobs/{job_id}/logs")
