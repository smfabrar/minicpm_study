from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class RunSettings:
    seed: int = 42
    repetitions: int = 1
    paced: bool = True
    oracle_delay_ms: int = 1000
    drain_seconds: int = 12
    timeout_seconds: int = 240
    system_prompt: str = "You are a helpful voice assistant. Use current external information when available. Answer concisely."
    granite_model: str = "ibm-granite/granite-4.0-350m"
    granite_revision: str = "main"
    granite_device: str = "cuda:1"
    whisper_model: str = "tiny"
    whisper_device: str = "cuda"
    whisper_device_index: int = 1
    whisper_compute_type: str = "float16"
    native_url: str = "ws://127.0.0.1:8000/v1/realtime?mode=audio"
    native_revision: str = "873056743b74e1a4ce5dcf7290e2298428e214db"
    gateway_revision: str = "47709a9210dfd71afa76c058e017fc8c4db5c8d2"
    patch_sha256: str = ""
    reference_audio: str = ""
    memory_interval_ms: int = 20
    voice: str = "af_heart"
    tts_speed: float = 1.0
    tts_revision: str = "main"

    def __post_init__(self):
        for name, lower, upper in (("repetitions", 1, 20), ("oracle_delay_ms", 0, 60000),
                                   ("drain_seconds", 1, 120), ("timeout_seconds", 10, 1800),
                                   ("memory_interval_ms", 5, 1000), ("tts_speed", 0.5, 2.0)):
            value = getattr(self, name)
            if type(value) not in (int, float) or not lower <= value <= upper:
                raise ValueError(f"{name} must be between {lower} and {upper}")
        integer_fields = ("seed", "repetitions", "oracle_delay_ms", "drain_seconds", "timeout_seconds", "memory_interval_ms", "whisper_device_index")
        if any(type(getattr(self, name)) is not int for name in integer_fields):
            raise ValueError("Counts, delays, seed and device index must be integers")
        if self.whisper_device_index < 0:
            raise ValueError("Whisper device index must be nonnegative")
        for definition in fields(self):
            if definition.type is str and not isinstance(getattr(self, definition.name), str):
                raise ValueError(f"{definition.name} must be text")
        if type(self.paced) is not bool:
            raise ValueError("Paced must be a boolean")
        if self.whisper_device not in {"cpu", "cuda", "auto"}:
            raise ValueError("Whisper device must be cpu, cuda or auto")
        if not self.voice or "/" in self.voice or "\\" in self.voice:
            raise ValueError("Voice must be a Kokoro voice identifier")

    @classmethod
    def from_dict(cls, value):
        unknown = set(value) - {definition.name for definition in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}")
        return cls(**value)
