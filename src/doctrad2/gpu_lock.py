from contextlib import contextmanager
import fcntl
from sqlalchemy import text


@contextmanager
def gpu_lock(db, root):
    """Single BC-250 admission. PostgreSQL advisory lock covers multiple LAN workers."""
    if db.engine.dialect.name == "postgresql":
        with db.engine.connect() as conn:
            admitted = bool(conn.scalar(text("SELECT pg_try_advisory_lock(207250)")))
            try:
                yield admitted
            finally:
                if admitted:
                    conn.execute(text("SELECT pg_advisory_unlock(207250)"))
    else:
        # SQLite profile supports a single host; production distributed workers require PostgreSQL.
        root.mkdir(parents=True, exist_ok=True)
        with (root / "bc250.lock").open("a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                admitted = True
            except BlockingIOError:
                admitted = False
            try:
                yield admitted
            finally:
                if admitted:
                    fcntl.flock(f, fcntl.LOCK_UN)
