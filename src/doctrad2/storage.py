import hashlib
import json
import os
from pathlib import Path
import tempfile


def digest(data: bytes):
    return hashlib.sha256(data).hexdigest()


def key(value):
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())


class Artifacts:
    def __init__(self, root: Path):
        self.root = root / "objects"
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, sha: str):
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("Invalid object digest")
        return self.root / sha[:2] / sha[2:]

    def put(self, data: bytes):
        sha = digest(data)
        target = self.path(sha)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            fd, name = tempfile.mkstemp(dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(name, target)
            finally:
                Path(name).unlink(missing_ok=True)
        return sha

    def get(self, sha):
        data = self.path(sha).read_bytes()
        if digest(data) != sha:
            raise ValueError("Corrupt artifact")
        return data

    def json(self, obj):
        return self.put(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode())

    def read_json(self, sha):
        return json.loads(self.get(sha))
