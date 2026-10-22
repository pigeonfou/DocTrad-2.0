"""Local, content-addressed documents and optimistic translation revisions."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from .domain import DocumentIR
from .quality import check_text


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def checked_digest(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('invalid_object_digest')
    return value


class RevisionConflict(RuntimeError):
    pass


class DocumentStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name in ('objects', 'heads', 'locks'):
            (self.root / name).mkdir(mode=0o700, exist_ok=True)

    def object_path(self, digest):
        return self.root / 'objects' / checked_digest(digest)

    def put(self, data):
        digest = hashlib.sha256(data).hexdigest()
        destination = self.object_path(digest)
        fd, temporary = tempfile.mkstemp(dir=self.root / 'objects')
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if self.read(digest) != data:
                    raise ValueError('existing_object_corrupted')
        finally:
            os.unlink(temporary)
        return digest

    def read(self, digest):
        data = self.object_path(digest).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('object_digest_mismatch')
        return data

    def put_json(self, value):
        return self.put(canonical(value))

    def read_json(self, digest):
        return json.loads(self.read(digest))

    def document(self, digest):
        value = self.read_json(digest)
        if value.get('schema') != 'doctrad-skynet-document-1':
            raise ValueError('not_a_document_snapshot')
        ir = DocumentIR.model_validate(value['ir'])
        if value['original'] != ir.source_sha:
            raise ValueError('document_source_mismatch')
        self.read(value['original'])
        ids = [node.id for node in ir.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate_block_id')
        return value, ir

    def head(self, document):
        path = self.root / 'heads' / checked_digest(document)
        return checked_digest(path.read_text().strip()) if path.exists() else None

    @contextmanager
    def locked(self, document):
        with (self.root / 'locks' / checked_digest(document)).open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def revise(self, document, base, updates, actor, reason, provenance=None):
        _, ir = self.document(document)
        if not actor.strip() or not reason.strip() or not updates:
            raise ValueError('revision_actor_reason_and_updates_required')
        nodes = {node.id: node for node in ir.nodes}
        if not set(updates).issubset(nodes):
            raise ValueError('unknown_source_block')
        if any(not isinstance(text, str) or not text.strip() for text in updates.values()):
            raise ValueError('empty_translation')
        with self.locked(document):
            if self.head(document) != base:
                raise RevisionConflict('stale_translation_revision')
            entries = {}
            if base:
                previous = self.read_json(base)
                if previous.get('schema') != 'doctrad-skynet-revision-1' or previous['document'] != document:
                    raise ValueError('revision_document_mismatch')
                entries.update(previous['entries'])
            for block_id, target in updates.items():
                findings = check_text(nodes[block_id].text, target, block_id)
                entries[block_id] = {'target': target, 'status': 'requires_review',
                                     'findings': [finding.model_dump() for finding in findings]}
            revision = {'schema': 'doctrad-skynet-revision-1', 'document': document, 'parent': base,
                        'actor': actor, 'reason': reason, 'created': datetime.now(timezone.utc).isoformat(),
                        'changed_blocks': sorted(updates), 'entries': entries, 'provenance': provenance or {}}
            digest = self.put_json(revision)
            fd, temporary = tempfile.mkstemp(dir=self.root / 'heads')
            try:
                with os.fdopen(fd, 'w') as handle:
                    handle.write(digest + '\n')
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.root / 'heads' / document)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return digest
