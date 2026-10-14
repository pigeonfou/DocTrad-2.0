from contextlib import contextmanager
import time
import uuid
from sqlalchemy import create_engine, String, Text, Float, Integer, JSON, select, update, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    password: Mapped[str] = mapped_column(Text)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(200))
    source_sha: Mapped[str] = mapped_column(String(64))
    format: Mapped[str] = mapped_column(String(10))
    created: Mapped[float] = mapped_column(Float, default=time.time)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(String(36), index=True)
    owner: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    lease: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    artifacts: Mapped[dict] = mapped_column(JSON, default=dict)
    contract: Mapped[dict] = mapped_column(JSON, default=dict)
    glossary: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class Unit(Base):
    __tablename__ = "units"
    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    cache_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    time: Mapped[float] = mapped_column(Float, default=time.time)
    kind: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class Cache(Base):
    __tablename__ = "cache"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(Text)
    provenance: Mapped[dict] = mapped_column(JSON)


class Database:
    def __init__(self, url):
        kwargs = {"connect_args": {"check_same_thread": False, "timeout": 30}} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, pool_pre_ping=True, **kwargs)
        if url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def setup(conn, _):
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def migrate(self):
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self):
        with self.sessions.begin() as session:
            yield session

    def claim(self):
        now = time.time()
        with self.session() as s:
            q = select(Job).where((Job.status == "queued") | ((Job.status == "running") & (Job.lease_until < now))).order_by(Job.created).limit(1)
            if self.engine.dialect.name == "postgresql":
                q = q.with_for_update(skip_locked=True)
            job = s.scalar(q)
            if not job:
                return None
            token = str(uuid.uuid4())
            result = s.execute(update(Job).where(Job.id == job.id, Job.lease_until <= now).values(
                status="running", lease=token, lease_until=now + 60))
            if result.rowcount != 1:
                return None
            return job.id, token

    def heartbeat(self, job_id, token):
        with self.session() as s:
            result = s.execute(update(Job).where(Job.id == job_id, Job.lease == token,
                               Job.status == "running").values(lease_until=time.time() + 60))
            return result.rowcount == 1

    def log(self, s, job_id, kind, payload=None):
        s.add(Event(job_id=job_id, kind=kind, payload=payload or {}))
