"""Atlas repositories and transactions behind the existing service boundary."""

import json
import threading
from dataclasses import asdict

from pymongo import MongoClient
from pymongo.write_concern import WriteConcern

from .repositories import StudyRepository, RunRepository
from ..domain.models import Case, ToolDefinition, LibraryTool, utc_now
from ..domain.errors import NotFoundError


class MongoDatabase:
    def __init__(self, uri, name):
        self.lock = threading.RLock()  # One active platform; serialize service transactions.
        self.client = MongoClient(uri, serverSelectionTimeoutMS=10000)
        self.client.admin.command('ping')
        self.db = self.client.get_database(name, write_concern=WriteConcern('majority'))
        for name in ('studies', 'cases', 'tools', 'runs', 'tool_library'):
            self.db[name].create_index('study_id')
        self.db.tools.create_index([('study_id', 1), ('name', 1)], unique=True)

    def unit_of_work(self):
        return MongoUnitOfWork(self)


class MongoRepository:
    def __init__(self, collection, session, decode):
        self.collection, self.session, self.decode = collection, session, decode

    def _find(self, query):
        return self.collection.find(query, session=self.session).sort('_order', 1)

    def get(self, identifier, *, include_deleted=False):
        row = self.collection.find_one({'_id': identifier}, session=self.session)
        if row is None:
            raise NotFoundError('Record not found')
        entity = self.decode(row)
        if getattr(entity, 'deleted_at', None) and not include_deleted:
            raise NotFoundError('Study is in Trash; restore it first')
        return entity

    def list(self, *, deleted=False):
        entities = [self.decode(row) for row in self._find({})]
        if self.collection.name in {'studies', 'tool_library'}:
            entities.reverse()
        return [e for e in entities if bool(getattr(e, 'deleted_at', None)) == deleted]

    def list_for_study(self, study_id):
        entities = [self.decode(row) for row in self._find({'study_id': study_id})]
        return list(reversed(entities)) if self.collection.name == 'runs' else entities

    def list_active(self):
        return [e for e in self.list() if e.status in {'queued', 'running'}]

    def save(self, entity):
        # JSON preserves arbitrary tool keys without Mongo field-name semantics.
        previous = self.collection.find_one({'_id': entity.id}, session=self.session)
        row = {'_order': previous['_order'] if previous else getattr(entity, 'created_at', utc_now()),
               '_id': entity.id, 'payload': json.dumps(asdict(entity), ensure_ascii=False)}
        if hasattr(entity, 'study_id'):
            row['study_id'] = entity.study_id
        if self.collection.name == 'tools':
            row['name'] = entity.name
        self.collection.replace_one({'_id': entity.id}, row, upsert=True, session=self.session)

    def delete(self, identifier):
        self.get(identifier)
        self.collection.delete_one({'_id': identifier}, session=self.session)


class MongoUnitOfWork:
    def __init__(self, database):
        self.database = database

    def __enter__(self):
        self.database.lock.acquire()
        try:
            self.session = self.database.client.start_session()
            self.session.start_transaction()
        except BaseException:
            self.database.lock.release()
            raise
        decoders = {
            'studies': StudyRepository._decode, 'runs': RunRepository._decode,
            'cases': lambda row: Case(**json.loads(row['payload'])),
            'tools': lambda row: ToolDefinition(**json.loads(row['payload'])),
            'library': lambda row: LibraryTool(**json.loads(row['payload'])),
        }
        for name, decode in decoders.items():
            collection = 'tool_library' if name == 'library' else name
            setattr(self, name, MongoRepository(self.database.db[collection], self.session, decode))
        return self

    def __exit__(self, error_type, error, traceback):
        try:
            if error_type:
                self.session.abort_transaction()
            else:
                self.session.commit_transaction()
        finally:
            try:
                self.session.end_session()
            finally:
                self.database.lock.release()
