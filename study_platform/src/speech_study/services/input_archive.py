"""Read the numbered input-dataset ZIP format without extracting arbitrary paths."""

import io
import json
import re
import stat
import wave
import zipfile
from pathlib import PurePosixPath

from ..audio import read_pcm, wav_bytes

CATEGORIES = {'room', 'document', 'datetime', 'web', 'none', 'custom', 'calculator'}


class InputDatasetArchive:
    def __init__(self, store):
        self.store = store

    def read(self, identifier, content):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                return self._read(identifier, archive)
        except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, wave.Error, EOFError) as exc:
            raise ValueError('Invalid dataset ZIP, UTF-8 text or WAV content') from exc

    def _read(self, identifier, archive):
        entries = archive.infolist()
        if len(entries) > 6000 or sum(entry.file_size for entry in entries) > 250 * 1024 * 1024:
            raise ValueError('Dataset exceeds 6000 entries or 250 MiB expanded size')
        groups, seen, source_cases, roots = {}, set(), {}, set()
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in entry.filename or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError('Dataset ZIP contains an unsafe path or symbolic link')
            if entry.is_dir() or '__MACOSX' in path.parts or path.name == '.DS_Store':
                continue
            if entry.flag_bits & 1:
                raise ValueError('Use an unencrypted dataset ZIP')
            if entry.filename.casefold() in seen:
                raise ValueError('Dataset ZIP contains duplicate filenames')
            seen.add(entry.filename.casefold())
            if path.name == 'manifest.json' and len(path.parts) <= 2:
                if entry.file_size > 1024 * 1024:
                    raise ValueError('Dataset manifest exceeds 1 MiB')
                manifest = json.loads(archive.read(entry))
                if not isinstance(manifest, dict):
                    raise ValueError('Dataset manifest must be a JSON object')
                if manifest.get('kind') == 'study-inputs':
                    cases = manifest.get('cases', [])
                    if not isinstance(cases, list) or any(not isinstance(case, dict) or 'number' not in case for case in cases):
                        raise ValueError('Dataset manifest needs a list of numbered cases')
                    source_cases.update({str(case['number']): case for case in cases})
                continue
            if len(path.parts) not in {2, 3} or not path.parent.name.isdigit():
                raise ValueError('Use numbered dataset folders, optionally inside one study folder')
            number = path.parent.name
            roots.add(path.parts[0] if len(path.parts) == 3 else '')
            if len(roots) > 1:
                raise ValueError('Use one dataset root folder')
            if int(number) < 1 or len(number) > 6:
                raise ValueError('Dataset folder numbers must be positive integers')
            names = {'question.txt': 'question', 'category.txt': 'category',
                     f'input{int(number)}.wav': 'original', f'input{int(number)}_16khz.wav': 'normalized'}
            kind = names.get(path.name)
            if kind is None:
                raise ValueError(f'Unexpected file in folder {number}: {path.name}')
            group = groups.setdefault(str(int(number)), {})
            if kind in group:
                raise ValueError(f'Multiple {kind} files for folder {number}')
            limit = 50 * 1024 * 1024 if kind in {'original', 'normalized'} else 16000
            if entry.file_size > limit:
                raise ValueError(f'File in folder {number} exceeds the allowed size')
            group[kind] = archive.read(entry)
        if not groups or len(groups) > 1000:
            raise ValueError('Import between 1 and 1000 numbered input folders')
        items = []
        for number, group in sorted(groups.items(), key=lambda pair: int(pair[0])):
            question = group['question'].decode('utf-8-sig').strip() if 'question' in group else None
            category = group['category'].decode('utf-8-sig').strip() if 'category' in group else None
            if question is not None and not 0 < len(question) <= 4000:
                raise ValueError(f'Folder {number} needs non-empty question text, up to 4000 characters')
            if category is not None and category not in CATEGORIES:
                raise ValueError(f'Unknown category in folder {number}')
            item = {'number': number, 'question': question, 'category': category,
                    'original': None, 'normalized': None, 'source_case_id': source_cases.get(number, {}).get('case_id'),
                    'source_origin': source_cases.get(number, {}).get('audio_origin')}
            if item['source_case_id'] is not None and not isinstance(item['source_case_id'], str):
                raise ValueError('Manifest case IDs must be text')
            if item['source_origin'] is not None and not isinstance(item['source_origin'], str):
                raise ValueError('Manifest audio origins must be text')
            for kind in ('original', 'normalized'):
                if kind in group:
                    relative = f'{identifier}/{number}/{kind}.wav'
                    self.store.write(relative, group[kind])
                    read_pcm(self.store.resolve(relative))  # Validate supported PCM, duration and non-empty samples.
                    item[kind] = relative
            if item['normalized']:
                with wave.open(str(self.store.resolve(item['normalized'])), 'rb') as audio:
                    if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (16000, 1, 2):
                        raise ValueError(f'Folder {number}: normalized WAV must be 16 kHz mono PCM16')
            elif item['original']:
                item['normalized'] = self.store.write(f'{identifier}/{number}/normalized.wav',
                    wav_bytes(read_pcm(self.store.resolve(item['original']))))
            items.append(item)
        return items
