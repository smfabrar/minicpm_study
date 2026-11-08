"""The inference boundary contains audio and executable configuration only."""

from dataclasses import asdict, dataclass, field
from typing import Any
from .settings import RunSettings


@dataclass(frozen=True)
class RunRequest:
    condition: str
    audio_path: str
    audio_sha256: str = ""
    settings: RunSettings = field(default_factory=RunSettings)
    tools: list[dict[str, Any]] = field(default_factory=list)
    oracle_result: str | None = None
    oracle_mode: str = "fixed"

    def to_payload(self) -> dict:
        payload = asdict(self)
        if self.condition != "B2":
            payload.pop("oracle_result")
            payload.pop("oracle_mode")
        self.from_dict(payload)
        return payload

    @classmethod
    def from_dict(cls, data):
        if data.get("condition") not in {"B0", "B1", "B2"}:
            raise ValueError("Condition must be B0, B1 or B2")
        if not isinstance(data.get("audio_path"), str) or not data["audio_path"]:
            raise ValueError("An input audio path is required")
        if data.get("condition") == "B1" and "oracle_result" in data:
            raise ValueError("B1 must not receive oracle data")
        mode = data.get("oracle_mode", "fixed")
        if mode not in {"fixed", "server_clock"}:
            raise ValueError("Unknown B2 reference mode")
        if "oracle_mode" in data and data["condition"] != "B2":
            raise ValueError("Oracle mode is exclusive to B2")
        oracle = data.get("oracle_result")
        if mode == "server_clock" and oracle is not None:
            raise ValueError("Server-clock references must not contain a saved fact")
        if oracle is not None and (not isinstance(oracle, str) or not oracle.strip()):
            raise ValueError("B2 reference result cannot be empty")
        if oracle is not None and data["condition"] != "B2":
            raise ValueError("Oracle results are exclusive to B2")
        settings = data.get("settings", {})
        if not isinstance(settings, dict) or not isinstance(data.get("tools", []), list):
            raise ValueError("Invalid runtime configuration")
        settings = RunSettings.from_dict(settings)
        return cls(data["condition"], data["audio_path"], data.get("audio_sha256", ""), settings,
                   data.get("tools", []) if data["condition"] == "B1" else [], oracle, mode)


@dataclass(frozen=True, slots=True)
class SynthesisRequest:
    question: str
    settings: RunSettings = field(default_factory=RunSettings)

    def __post_init__(self) -> None:
        if not isinstance(self.question, str) or not 0 < len(self.question.strip()) <= 4000:
            raise ValueError("Question must contain 1–4000 characters")

    def cache_key(self) -> str:
        import hashlib
        import json
        identity = [self.question, self.settings.voice, self.settings.tts_speed,
                    self.settings.tts_revision, "Kokoro-82M-v1.0"]
        # Keep existing CPU cache entries; GPU generation has a separate identity.
        if self.settings.tts_device != "cpu":
            identity.append(self.settings.tts_device)
        return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()

    def to_payload(self) -> dict:
        return {"job_kind": "synthesis", "question": self.question,
                "settings": asdict(self.settings)}
