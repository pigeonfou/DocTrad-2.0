import asyncio
from collections import defaultdict
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import time
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select
from .config import Settings
from .db import Database, Document, Job, Unit, User, Event
from .storage import Artifacts


class Login(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=1024)


class Start(BaseModel):
    glossary: dict[str, str] = Field(default_factory=dict)


class Correction(BaseModel):
    target: str = Field(min_length=1, max_length=20000)
    version: int


def create_app(settings=None, database=None):
    settings = settings or Settings.load()
    settings.root.mkdir(parents=True, exist_ok=True)
    db = database or Database(settings.database_url)
    db.migrate()
    store = Artifacts(settings.root)
    app = FastAPI(title="DocTrad 2.0", docs_url=None, redoc_url=None)
    app.add_middleware(SessionMiddleware, secret_key=settings.secret, session_cookie="doctrad2_session",
                       same_site="strict", https_only=settings.secure_cookie, max_age=28800)
    app.state.db, app.state.store = db, store
    attempts = defaultdict(list)
    ph = PasswordHasher()
    dummy = ph.hash(secrets.token_urlsafe(32))

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-src 'self'; frame-ancestors 'self'; object-src 'none'"
        return response

    def owner(request):
        name = request.session.get("user")
        if not name:
            raise HTTPException(401, "Authentification requise")
        return name

    def csrf(request):
        expected = request.session.get("csrf", "")
        supplied = request.headers.get("X-CSRF-Token", "")
        if not expected or not hmac.compare_digest(expected, supplied):
            raise HTTPException(403, "Jeton de formulaire invalide")

    def owned_job(s, jid, request):
        job = s.get(Job, jid)
        if not job or job.owner != owner(request):
            raise HTTPException(404, "Traitement absent")
        return job

    def serialize(job):
        return {"id": job.id, "document_id": job.document_id, "status": job.status, "progress": job.progress,
                "revision": job.revision, "error": job.error, "artifacts": list(job.artifacts), "contract": job.contract}

    @app.get("/health")
    def health():
        with db.session() as s:
            s.execute(select(User.name).limit(1))
        return {"status": "ok", "version": "2.0.0", "inference": "BC250/Vulkan/llama-server", "quality": "not-certified-by-health", "llm_configured": len(settings.model_sha) == 64 and len(settings.runtime_sha) == 64}

    @app.get("/v2/models")
    def models(request: Request):
        owner(request)
        from .models import catalog
        return catalog(settings)

    @app.get("/")
    def index():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/static/{name}")
    def static(name: str):
        if name not in {"app.js", "style.css"}:
            raise HTTPException(404)
        return FileResponse(Path(__file__).parent / "static" / name)

    @app.get("/v2/session")
    def session(request: Request):
        request.session.setdefault("csrf", secrets.token_urlsafe(32))
        return {"user": request.session.get("user"), "csrf": request.session["csrf"]}

    @app.post("/v2/login")
    def login(body: Login, request: Request):
        csrf(request)
        throttle_key = (request.client.host, body.username)
        now = time.monotonic()
        attempts[throttle_key] = [t for t in attempts[throttle_key] if now - t < 300]
        if len(attempts[throttle_key]) >= 8:
            raise HTTPException(429, "Réessayez dans quelques minutes")
        attempts[throttle_key].append(now)
        with db.session() as s:
            user = s.get(User, body.username)
            try:
                valid = ph.verify(user.password if user else dummy, body.password) and bool(user)
            except (VerificationError, InvalidHashError):
                valid = False
        if not valid:
            raise HTTPException(401, "Identifiants invalides")
        attempts.pop(throttle_key, None)
        request.session.clear()
        request.session.update(user=body.username, csrf=secrets.token_urlsafe(32))
        return {"user": body.username, "csrf": request.session["csrf"]}

    @app.post("/v2/logout")
    def logout(request: Request):
        csrf(request)
        request.session.clear()
        return {"ok": True}

    @app.post("/v2/documents")
    async def upload(request: Request, file: UploadFile = File(...)):
        user = owner(request)
        csrf(request)
        name = Path((file.filename or "document.pdf").replace("\\", "/")).name[:200]
        fmt = name.rsplit(".", 1)[-1].lower()
        if fmt not in {"pdf", "docx", "pptx"}:
            raise HTTPException(415, "Formats acceptés : PDF, DOCX, PPTX")
        data = bytearray()
        while chunk := await file.read(1024 * 1024):
            data.extend(chunk)
            if len(data) > 100 * 1024 * 1024:
                raise HTTPException(413, "Limite de 100 Mo")
        if not data or (fmt == "pdf" and not bytes(data[:1024]).lstrip().startswith(b"%PDF-")):
            raise HTTPException(422, "Fichier invalide")
        if fmt != "pdf":
            import zipfile
            from io import BytesIO
            try:
                with zipfile.ZipFile(BytesIO(data)) as archive:
                    if sum(x.file_size for x in archive.infolist()) > 200 * 1024 * 1024:
                        raise HTTPException(413, "Archive décompressée trop volumineuse")
                    expected = "word/document.xml" if fmt == "docx" else "ppt/presentation.xml"
                    if expected not in archive.namelist():
                        raise HTTPException(422, "Paquet bureautique invalide")
            except zipfile.BadZipFile:
                raise HTTPException(422, "Archive invalide") from None
        sha = store.put(bytes(data))
        with db.session() as s:
            doc = Document(owner=user, name=name, source_sha=sha, format=fmt)
            s.add(doc)
            s.flush()
            return {"id": doc.id, "name": doc.name, "source_sha": sha, "format": fmt}

    @app.get("/v2/documents")
    def documents(request: Request):
        with db.session() as s:
            return [{"id": d.id, "name": d.name, "format": d.format} for d in s.scalars(select(Document).where(Document.owner == owner(request)).order_by(Document.created.desc()))]

    @app.post("/v2/documents/{did}/jobs")
    def start(did: str, body: Start, request: Request):
        csrf(request)
        if not settings.model_sha or not settings.runtime_sha:
            raise HTTPException(503, "Connexion au moteur BC-250 à configurer")
        with db.session() as s:
            doc = s.get(Document, did)
            if not doc or doc.owner != owner(request):
                raise HTTPException(404)
            if len(body.glossary) > 1000 or any(len(k) > 100 or len(v) > 200 for k, v in body.glossary.items()):
                raise HTTPException(422, "Glossaire trop volumineux")
            idem = request.headers.get("Idempotency-Key")
            if idem:
                if len(idem) > 200:
                    raise HTTPException(422)
                # Scoped deterministic ID enforces uniqueness in DB as well as sequential requests.
                jid = hashlib.sha256((doc.owner + did + idem).encode()).hexdigest()[:36]
                old = s.get(Job, jid)
                if old:
                    if old.glossary != body.glossary:
                        raise HTTPException(409, "Clé déjà utilisée avec un autre glossaire")
                    return serialize(old)
            else:
                jid = None
            job = Job(document_id=did, owner=doc.owner, glossary=body.glossary, **({"id": jid} if jid else {}))
            s.add(job)
            s.flush()
            db.log(s, job.id, "queued")
            return serialize(job)

    @app.get("/v2/jobs")
    def jobs(request: Request):
        with db.session() as s:
            return [serialize(j) for j in s.scalars(select(Job).where(Job.owner == owner(request)).order_by(Job.created.desc()))]

    @app.get("/v2/jobs/{jid}")
    def job(jid: str, request: Request):
        with db.session() as s:
            return serialize(owned_job(s, jid, request))

    @app.get("/v2/jobs/{jid}/units")
    def units(jid: str, request: Request):
        with db.session() as s:
            owned_job(s, jid, request)
            return [{"id": u.node_id, "source": u.source, "target": u.target, "version": u.version} for u in s.scalars(select(Unit).where(Unit.job_id == jid))]

    @app.patch("/v2/jobs/{jid}/units/{uid}")
    def correction(jid: str, uid: str, body: Correction, request: Request):
        csrf(request)
        with db.session() as s:
            job = owned_job(s, jid, request)
            if job.status in {"queued", "running", "approved"}:
                raise HTTPException(409, "Créer une nouvelle traduction pour une version approuvée ; attendre le traitement actif")
            unit = s.get(Unit, (jid, uid))
            if not unit:
                raise HTTPException(404)
            if unit.version != body.version:
                raise HTTPException(409, "La traduction a été modifiée depuis votre lecture")
            history = list(job.artifacts.get("history", []))
            if job.artifacts.get("output"):
                history.append({"revision": job.revision, "output": job.artifacts["output"], "report": job.artifacts.get("report"), "translations": job.artifacts.get("translations")})
            job.artifacts = {k: v for k, v in job.artifacts.items() if k not in {"output", "report", "translations"}} | {"history": history}
            unit.target, unit.version = body.target, unit.version + 1
            unit.provenance = {"actor": owner(request), "kind": "human_correction", "previous": unit.provenance}
            job.revision += 1
            job.status, job.lease_until, job.lease = "queued", 0, None
            db.log(s, jid, "corrected", {"unit_id": uid, "revision": job.revision})
            return {"version": unit.version, "status": job.status}

    @app.post("/v2/jobs/{jid}/resume")
    def resume(jid: str, request: Request):
        csrf(request)
        with db.session() as s:
            job = owned_job(s, jid, request)
            if job.status != "runtime_failed":
                raise HTTPException(409, "Seul un échec d’exécution peut être repris")
            job.status, job.lease_until, job.lease, job.error = "queued", 0, None, None
            db.log(s, jid, "resumed")
            return serialize(job)

    @app.post("/v2/jobs/{jid}/approve")
    def approve(jid: str, request: Request):
        csrf(request)
        with db.session() as s:
            job = owned_job(s, jid, request)
            if job.status != "ready_for_review":
                raise HTTPException(409, "Les erreurs critiques empêchent l’approbation")
            job.status = "approved"
            db.log(s, jid, "approved", {"actor": owner(request), "revision": job.revision})
            return serialize(job)

    @app.get("/v2/jobs/{jid}/report")
    def report(jid: str, request: Request):
        with db.session() as s:
            job = owned_job(s, jid, request)
            if "report" not in job.artifacts:
                raise HTTPException(404)
            return store.read_json(job.artifacts["report"])

    @app.get("/v2/jobs/{jid}/artifacts/{kind}")
    def artifact(jid: str, kind: str, request: Request):
        with db.session() as s:
            job = owned_job(s, jid, request)
            doc = s.get(Document, job.document_id)
            if kind == "source":
                sha, name = doc.source_sha, doc.name
            elif kind in {"output", "ir", "translations", "report"} and kind in job.artifacts:
                sha = job.artifacts[kind]
                suffix = doc.format if kind == "output" else "json"
                name = f"DocTrad2_{jid}_FR_TranslateGemma12B_Q4KM_r{job.revision}.{suffix}"
            else:
                raise HTTPException(404)
        return FileResponse(store.path(sha), filename=name)

    @app.get("/v2/jobs/{jid}/events")
    async def events(jid: str, request: Request):
        with db.session() as s:
            owned_job(s, jid, request)
        async def stream():
            last = 0
            while not await request.is_disconnected():
                with db.session() as s:
                    rows = s.scalars(select(Event).where(Event.job_id == jid, Event.id > last).order_by(Event.id)).all()
                    job = s.get(Job, jid)
                    status = serialize(job)
                for row in rows:
                    last = row.id
                    yield f"id: {last}\nevent: progress\ndata: {json.dumps(status)}\n\n"
                yield ": heartbeat\n\n"
                if status["status"] not in {"queued", "running"}:
                    return
                await asyncio.sleep(2)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    return app

