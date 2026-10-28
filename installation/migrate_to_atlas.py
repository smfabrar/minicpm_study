#!/usr/bin/env python3
"""Copy an existing stopped platform's records/files to Atlas. Never deletes source."""
import argparse
import os
import json
import sqlite3
from pathlib import Path

from speech_study.infrastructure.mongo import MongoDatabase
from speech_study.infrastructure.gridfs_store import GridFSArtifactStore


def migrate(root: Path, database):
    connection = sqlite3.connect(root / 'studies.sqlite')
    connection.row_factory = sqlite3.Row
    try:
        with database.client.start_session() as session:
            with session.start_transaction():
                for name in ('studies', 'cases', 'tools', 'runs', 'tool_library'):
                    for row in connection.execute(f'SELECT rowid AS insertion_order, * FROM {name}'):
                        document = {'_id': row['id'], 'payload': row['payload'],
                                    '_order': json.loads(row['payload']).get('created_at', f"0:{row['insertion_order']:012d}")}
                        if 'study_id' in row.keys(): document['study_id'] = row['study_id']
                        if name == 'tools': document['name'] = row['name']
                        existing = database.db[name].find_one({'_id': row['id']}, session=session)
                        if existing and existing['payload'] != row['payload']:
                            raise ValueError('Destination has a different record; migration will not overwrite it')
                        database.db[name].replace_one({'_id': row['id']}, document, upsert=True, session=session)
        for directory, namespace in (('artifacts', 'artifacts'), ('operations', 'operations')):
            source = root / directory
            store = GridFSArtifactStore(source, database.db, namespace)
            for path in source.rglob('*'):
                if path.is_file():
                    store.write(path.relative_to(source).as_posix(), path.read_bytes())
    finally:
        connection.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    args = parser.parse_args()
    if not (args.data / 'studies.sqlite').is_file(): parser.error('SQLite source not found')
    uri = os.environ.get('SPEECH_MONGODB_URI')
    if not uri: parser.error('Set SPEECH_MONGODB_URI first')
    migrate(args.data, MongoDatabase(uri, os.environ.get('SPEECH_MONGODB_DATABASE', 'minicpm_study')))
    print('Records and files copied to Atlas. Source files remain unchanged.')
