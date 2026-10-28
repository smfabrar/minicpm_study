"""GridFS is durable storage; local files are a disposable working cache."""

import hashlib
import re
import threading

from gridfs import GridFSBucket
from ..artifacts import ArtifactStore


class GridFSArtifactStore(ArtifactStore):
    def __init__(self, root, database, namespace='artifacts'):
        super().__init__(root)
        self.lock = threading.RLock()
        self.cache = ArtifactStore(root)
        self.bucket = GridFSBucket(database, bucket_name=namespace)
        self.index = database[namespace + '_paths']

    def _download(self, entry):
        path = super().resolve(entry['_id'])
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256']:
            return
        with self.bucket.open_download_stream(entry['file_id']) as stream:
            content = stream.read()
            if hashlib.sha256(content).hexdigest() != entry["sha256"]:
                raise ValueError("Cloud artifact checksum mismatch")
            self.cache.write(entry['_id'], content)

    def resolve(self, relative):
        with self.lock:
            return self._resolve(relative)

    def _resolve(self, relative):
        path = super().resolve(relative)
        key = path.relative_to(self.root).as_posix()
        entry = self.index.find_one({'_id': key})
        if entry:
            self._download(entry)
        else:
            prefix = '' if key == '.' else key.rstrip('/') + '/'
            for entry in self.index.find({'_id': {'$regex': '^' + re.escape(prefix)}}):
                self._download(entry)
        return path

    def write(self, relative, content):
        with self.lock:
            return self._write(relative, content)

    def _write(self, relative, content):
        # Upload completely before publishing the path pointer. No GridFS transaction.
        path = super().resolve(relative)
        key = path.relative_to(self.root).as_posix()
        digest = hashlib.sha256(content).hexdigest()
        previous = self.index.find_one({'_id': key})
        if not previous or previous['sha256'] != digest:
            identifier = self.bucket.upload_from_stream(key, content)
            self.index.replace_one({'_id': key}, {'_id': key, 'file_id': identifier, 'sha256': digest}, upsert=True)
            if previous:
                self.bucket.delete(previous['file_id'])
        return self.cache.write(key, content)

    def sync(self, relative):
        # Local producers (WAV normalization and logs) explicitly publish their result.
        return self.write(relative, super().resolve(relative).read_bytes())
