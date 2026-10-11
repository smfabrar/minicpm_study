"""Files owned by the platform, addressed relative to one storage root."""

import hashlib
import json
import os
import tempfile
from pathlib import Path


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Artifact path escapes storage")
        return path

    def write(self, relative: str, content: bytes) -> str:
        path = self.resolve(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return relative

    def write_json(self, relative: str, value) -> str:
        return self.write(relative, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())

    def checksum(self, relative: str) -> str:
        return hashlib.sha256(self.resolve(relative).read_bytes()).hexdigest()
