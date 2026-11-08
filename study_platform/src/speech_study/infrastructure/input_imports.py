"""Short-lived local staging for dataset previews; accepted inputs go to GridFS."""

import shutil
import time
import json
from pathlib import Path
from uuid import uuid4

from ..artifacts import ArtifactStore
from ..domain.errors import NotFoundError


class InputImportRepository:
    def __init__(self, root: Path):
        self.store = ArtifactStore(root)

    def create(self, study_id):
        for path in self.store.root.iterdir():
            if path.is_dir() and time.time() - path.stat().st_mtime > 86400:
                shutil.rmtree(path)
        identifier = uuid4().hex
        self.save({'id': identifier, 'study_id': study_id, 'items': [], 'fingerprints': {}})
        return identifier

    def get(self, identifier, study_id):
        if len(identifier) != 32 or any(char not in '0123456789abcdef' for char in identifier):
            raise NotFoundError('Import preview not found')
        path = self.store.resolve(identifier + '/stage.json')
        if not path.is_file() or time.time() - path.stat().st_mtime > 86400:
            raise NotFoundError('Import preview expired; upload the ZIP again')
        stage = json.loads(path.read_text())
        if stage['study_id'] != study_id:
            raise NotFoundError('Import preview not found in this study')
        return stage

    def save(self, stage):
        self.store.write_json(stage['id'] + '/stage.json', stage)

    def discard(self, identifier, study_id):
        self.get(identifier, study_id)
        self.store.delete(identifier)

    def delete_for_study(self, study_id):
        for path in self.store.root.glob('*/stage.json'):
            if json.loads(path.read_text()).get('study_id') == study_id:
                self.store.delete(path.parent.name)
