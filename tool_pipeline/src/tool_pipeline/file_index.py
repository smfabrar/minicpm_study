"""Locate filenames in an explicit virtual file index; no filesystem access."""

import re
from difflib import SequenceMatcher
from pathlib import PurePosixPath


def normalize_filename(filename: str) -> str:
    spoken = re.sub(r'\bdot\b', '.', filename.casefold())
    return re.sub(r'[\W_]+', '', spoken)


class FileIndex:
    def __init__(self, paths: list[str], similarity_threshold: float = 0.8):
        if not isinstance(paths, list) or any(not isinstance(path, str) or not path.strip() for path in paths):
            raise ValueError('The file index must be a list of non-empty path strings')
        if not 0 < similarity_threshold <= 1:
            raise ValueError('The similarity threshold must be greater than 0 and at most 1')
        self.paths = list(dict.fromkeys(paths))
        self.similarity_threshold = similarity_threshold

    def search(self, filename: str) -> dict:
        if not isinstance(filename, str) or not 0 < len(filename.strip()) <= 240:
            raise ValueError('Provide a filename containing 1–240 characters')
        normalized = normalize_filename(filename)
        if not normalized:
            raise ValueError('Provide a filename, not just punctuation')
        exact = []
        approximate = []
        spoken = re.sub(r'\bdot\b', '.', filename.casefold())
        extension_omitted = not PurePosixPath(spoken).suffix
        for indexed_path in self.paths:
            path = PurePosixPath(indexed_path)
            indexed_name = normalize_filename(path.name)
            match = {'filename': path.name, 'folder': str(path.parent), 'path': indexed_path}
            if indexed_name == normalized:
                exact.append({**match, 'similarity': 1.0})
                continue
            score = SequenceMatcher(None, normalized, indexed_name, autojunk=False).ratio()
            if extension_omitted:
                stem_score = SequenceMatcher(None, normalized, normalize_filename(path.stem),
                                             autojunk=False).ratio()
                score = max(score, stem_score)
            if score >= self.similarity_threshold:
                approximate.append({**match, 'similarity': score})
        matches = exact or sorted(approximate, key=lambda item: (-item['similarity'], item['path']))
        match_type = 'exact' if exact else 'approximate' if matches else 'not_found'
        locations = ' '.join(
            f"File {item['filename']} is in folder {item['folder']}. Full path: {item['path']}."
            for item in matches
        )
        label = 'match' if len(matches) == 1 else 'matches'
        if match_type == 'exact':
            facts = f'Found {len(matches)} exact filename {label}. {locations}'
        elif match_type == 'approximate':
            facts = (f'No exact filename match for {filename!r}. Found {len(matches)} possible '
                     f'approximate filename {label}, ranked by similarity. {locations}')
        else:
            facts = (f'No file found with the name {filename!r}. No exact or sufficiently similar '
                     'filename was found in the configured file index.')
        return {'facts': facts, 'sources': ['study://configured-file-index'],
                'evidence': {'query': filename, 'normalized_filename': normalized, 'matches': matches,
                             'match_type': match_type, 'similarity_threshold': self.similarity_threshold,
                             'similarity_method': 'difflib.SequenceMatcher; stem fallback when extension omitted',
                             'index_kind': 'virtual', 'implementation': 'filename-index-v2'}}
