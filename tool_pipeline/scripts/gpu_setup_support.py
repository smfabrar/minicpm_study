"""Operations that need the installed model environment, invoked by the setup script."""

import argparse
import ctypes
import hashlib
import importlib.metadata
import json
import tempfile
import wave
from dataclasses import asdict
from pathlib import Path


GGUF_FILES = (
    "MiniCPM-o-4_5-Q4_K_M.gguf",
    "vision/MiniCPM-o-4_5-vision-F16.gguf",
    "audio/MiniCPM-o-4_5-audio-F16.gguf",
    "tts/MiniCPM-o-4_5-tts-F16.gguf",
    "tts/MiniCPM-o-4_5-projector-F16.gguf",
    "token2wav-gguf/encoder.gguf",
    "token2wav-gguf/flow_matching.gguf",
    "token2wav-gguf/flow_extra.gguf",
    "token2wav-gguf/hifigan2.gguf",
    "token2wav-gguf/prompt_cache.gguf",
)


def probe_gpu() -> dict:
    import torch

    if torch.version.cuda != "12.4" or not torch.cuda.is_available():
        raise RuntimeError("The CUDA 12.4 Torch wheel cannot access an NVIDIA GPU")
    devices = []
    for index in range(torch.cuda.device_count()):
        with torch.cuda.device(index):
            # Exercise the runtime rather than reporting driver presence alone.
            value = torch.ones((32, 32), device=f"cuda:{index}")
            assert (value @ value).sum().item() == 32768
            torch.cuda.synchronize()
        properties = torch.cuda.get_device_properties(index)
        major, minor = torch.cuda.get_device_capability(index)
        devices.append({"index": index, "name": properties.name,
                        "memory_bytes": properties.total_memory, "architecture": f"{major}{minor}"})
    site = Path(torch.__file__).resolve().parent.parent
    libraries = [site / "nvidia" / name / "lib" for name in ("cublas", "cudnn")]
    if not all(directory.is_dir() for directory in libraries):
        raise RuntimeError("Torch's cuBLAS/cuDNN library directories are missing")
    return {"torch": torch.__version__, "torch_cuda": torch.version.cuda,
            "devices": devices, "library_paths": [str(directory) for directory in libraries]}


def verify_imports() -> dict:
    import ctranslate2
    importlib.import_module("kokoro")
    import transformers
    import tool_pipeline
    import duplex_tools
    import spacy

    spacy.load("en_core_web_sm", enable=["tok2vec", "tagger"])

    for name in ("libcublas.so.12", "libcublasLt.so.12", "libcudnn.so.9"):
        ctypes.CDLL(name)
    if ctranslate2.get_cuda_device_count() < 1:
        raise RuntimeError("CTranslate2 cannot access a CUDA device")
    return {"transformers": transformers.__version__, "ctranslate2": ctranslate2.__version__,
            "audio_decoder": verify_audio_decoder(),
            "kokoro": importlib.metadata.version("kokoro"), "pipeline": str(Path(tool_pipeline.__file__).parent),
            "reference": str(Path(duplex_tools.__file__).parent)}


def verify_audio_decoder() -> dict:
    from faster_whisper.audio import decode_audio

    # Use a temporary recording so verification cannot enter study data or downloads.
    with tempfile.TemporaryDirectory(prefix="minicpm-audio-check-") as directory:
        audio_path = Path(directory) / "check.wav"
        with wave.open(str(audio_path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(bytes(3200))
        decoded = decode_audio(str(audio_path), sampling_rate=16000)
        if len(decoded) != 1600:
            raise RuntimeError("Faster Whisper did not decode the verification WAV correctly")
    return {"pyav": importlib.metadata.version("av"),
            "faster_whisper": importlib.metadata.version("faster-whisper"),
            "sample_rate": 16000, "sample_count": len(decoded)}


def download_models(root: Path) -> dict:
    from huggingface_hub import HfApi, snapshot_download

    # Resolve once, persist the commit, and reuse it on subsequent setup runs.
    manifest_path = root / "model-revisions.json"
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    definitions = {
        "native": ("openbmb/MiniCPM-o-4_5-gguf", list(GGUF_FILES)),
        "granite": ("ibm-granite/granite-4.0-350m", ["*.json", "*.jinja", "*.txt", "*.safetensors"]),
        "tts": ("hexgrad/Kokoro-82M", None),
        "whisper": ("Systran/faster-whisper-tiny", None),
    }
    result = {}
    for name, (repository, patterns) in definitions.items():
        saved = previous.get(name, {})
        if saved and saved.get("repository") != repository:
            raise ValueError(f"Unexpected {name} repository in {manifest_path}")
        revision = saved.get("revision") or HfApi().model_info(repository).sha
        # Record the pin before downloading so an interrupted download resumes at that pin.
        previous[name] = {"repository": repository, "revision": revision}
        temporary = manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(previous, indent=2) + "\n")
        temporary.replace(manifest_path)
        location = Path(snapshot_download(repository, revision=revision, allow_patterns=patterns))
        result[name] = {**previous[name], "path": str(location)}
        if name == "native":
            missing = [filename for filename in GGUF_FILES if not (location / filename).is_file()]
            if missing:
                raise RuntimeError(f"Incomplete native model layout: {missing}")
    return result


def run_settings(models: dict, demo: Path, patch: Path, device_count: int) -> dict:
    from speech_contracts import RunSettings

    sidecar_device = 1 if device_count > 1 else 0
    return asdict(RunSettings(
        granite_device=f"cuda:{sidecar_device}", whisper_device_index=sidecar_device,
        whisper_model=models["whisper"]["path"], granite_model=models["granite"]["path"],
        granite_revision=models["granite"]["revision"], tts_revision=models["tts"]["revision"],
        tts_device=f"cuda:{sidecar_device}",
        reference_audio=str(demo / "assets/ref_audio/ref_en_dlc_1.wav"),
        patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),
    ))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("probe", "verify", "verify-audio", "download", "settings"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--models", type=json.loads)
    parser.add_argument("--demo", type=Path)
    parser.add_argument("--patch", type=Path)
    parser.add_argument("--device-count", type=int)
    args = parser.parse_args()
    if args.operation == "verify-audio":
        result = verify_audio_decoder()
    elif args.operation == "download":
        if args.root is None:
            parser.error("download requires --root")
        args.root.mkdir(parents=True, exist_ok=True)
        result = download_models(args.root)
    elif args.operation == "settings":
        if any(value is None for value in (args.models, args.demo, args.patch, args.device_count)):
            parser.error("settings requires --models, --demo, --patch and --device-count")
        result = run_settings(args.models, args.demo, args.patch, args.device_count)
    else:
        result = probe_gpu() if args.operation == "probe" else verify_imports()
    # A marker tolerates package initialization messages without confusing the caller.
    print("SETUP_RESULT=" + json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
