"""Record installed distributions without loading optional model packages."""
import importlib.metadata
import os


def software_versions() -> dict[str, str | None]:
    result = {}
    for package in ('tool-pipeline', 'speech-contracts', 'torch', 'transformers', 'faster-whisper', 'ctranslate2', 'kokoro', 'numpy', 'websockets', 'psutil', 'nvidia-ml-py'):
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result[package] = None
    return result


def execution_environment() -> dict:
    return {'packages': software_versions(), 'cuda_visible_devices': os.environ.get('CUDA_VISIBLE_DEVICES'), 'native_revision_verification': 'Configured revisions are declarations. Check the native launcher manifest for verified checkout and patch provenance.'}
