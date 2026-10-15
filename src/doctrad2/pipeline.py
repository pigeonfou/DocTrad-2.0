from contextlib import contextmanager
import threading
import time
from sqlalchemy import select
from .db import Job, Unit, Document, Cache
from .domain import DocumentIR, ModelContract, Finding
from .storage import Artifacts, key
from .extraction import extract
from .inference import LlamaTranslator
from .text_policy import POLICY_VERSION
from .quality import check_text
from .reconstruction import build, validate_pdf


class LostLease(RuntimeError):
    pass


@contextmanager
def keep_lease(db, job_id, token):
    stop = threading.Event()
    lost = threading.Event()
    def heartbeat():
        while not stop.wait(15):
            try:
                if not db.heartbeat(job_id, token):
                    lost.set()
                    return
            except Exception:
                lost.set()
                return
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        yield lost
    finally:
        stop.set()
        thread.join(timeout=5)


class Pipeline:
    def __init__(self, settings, db, translator_factory=LlamaTranslator):
        self.settings, self.db = settings, db
        self.store = Artifacts(settings.root)
        self.translator_factory = translator_factory

    def owned(self, session, jid, token, lost):
        job = session.get(Job, jid)
        if lost.is_set() or not job or job.lease != token or job.status != "running":
            raise LostLease()
        return job

    def run(self, jid, token):
        with keep_lease(self.db, jid, token) as lost:
            try:
                self.process(jid, token, lost)
            except LostLease:
                return
            except Exception as exc:
                with self.db.session() as s:
                    job = s.get(Job, jid)
                    if job and job.lease == token and job.status == "running":
                        job.status = "runtime_failed"
                        job.error = str(exc) if str(exc).replace("_", "").isalnum() and len(str(exc)) <= 100 else type(exc).__name__
                        job.lease, job.lease_until = None, 0
                        self.db.log(s, jid, "runtime_failed", {"error_class": type(exc).__name__})

    def process(self, jid, token, lost):
        with self.db.session() as s:
            job = self.owned(s, jid, token, lost)
            document = s.get(Document, job.document_id)
            source = self.store.get(document.source_sha)
            fmt, owner, glossary = document.format, job.owner, job.glossary
            artifacts = dict(job.artifacts)
        if "ir" in artifacts:
            ir = DocumentIR.model_validate(self.store.read_json(artifacts["ir"]))
        else:
            ir = extract(source, fmt, self.settings.tessdata)
            if fmt == "pdf" and self.settings.docling_models:
                from .semantic import inspect_pdf, compare
                semantic = inspect_pdf(self.store.path(ir.source_sha), self.settings.docling_models)
                artifacts["semantic"] = self.store.json(semantic)
                ir.findings.extend(compare(ir, semantic))
            artifacts["ir"] = self.store.json(ir.model_dump())
            with self.db.session() as s:
                job = self.owned(s, jid, token, lost)
                job.artifacts = artifacts
                for node in ir.nodes:
                    if not s.get(Unit, (jid, node.id)):
                        s.add(Unit(job_id=jid, node_id=node.id, source=node.text))
                self.db.log(s, jid, "extracted", {"units": len(ir.nodes)})
        with self.db.session() as s:
            job = self.owned(s, jid, token, lost)
            contract = ModelContract(model_sha=self.settings.model_sha, runtime_sha=self.settings.runtime_sha).model_dump()
            targets = dict(s.execute(select(Unit.node_id, Unit.target).where(Unit.job_id == jid)).all())
            pending = any(n.translatable and targets.get(n.id) is None for n in ir.nodes)
            if pending:
                if job.contract and job.contract != contract:
                    # Never combine machine candidates from different contracts in a resumed revision.
                    raise RuntimeError("model_contract_changed_create_new_job")
                job.contract = contract
            # A completed candidate set can be recomposed after an upgrade without
            # calling the model or changing its original generation contract.
        translator = None
        try:
            for index, node in enumerate(ir.nodes):
                with self.db.session() as s:
                    job = self.owned(s, jid, token, lost)
                    unit = s.get(Unit, (jid, node.id))
                    if unit.target is not None or not node.translatable:
                        continue
                    ck = key({"owner": owner, "source": ir.source_sha, "ir": artifacts["ir"], "node": node.id,
                              "context": node.context, "glossary": glossary, "model": contract, "policy": POLICY_VERSION})
                    cached = s.get(Cache, ck)
                if cached:
                    target, provenance = cached.target, cached.provenance
                else:
                    if translator is None:
                        translator = self.translator_factory(self.settings)
                    target, provenance = translator.translate(node.text)
                    provenance["review_context"] = node.context
                findings = check_text(node.text, target, node.id, glossary)
                with self.db.session() as s:
                    job = self.owned(s, jid, token, lost)
                    unit = s.get(Unit, (jid, node.id))
                    unit.target, unit.cache_key, unit.provenance = target, ck, provenance
                    if not cached and not any(f.severity == "critical" for f in findings) and not s.get(Cache, ck):
                        s.add(Cache(id=ck, owner=owner, target=target, provenance=provenance))
                    job.progress = int((index + 1) / max(1, len(ir.nodes)) * 85)
                    self.db.log(s, jid, "translated", {"unit_id": node.id, "findings": [f.code for f in findings]})
        finally:
            if translator:
                translator.close()
        with self.db.session() as s:
            self.owned(s, jid, token, lost)
            units = s.scalars(select(Unit).where(Unit.job_id == jid)).all()
            translations = {u.node_id: u.target for u in units if u.target is not None}
        result, report = build(source, ir, translations)
        for unit in units:
            if unit.node_id in translations:
                report.findings.extend(check_text(unit.source, unit.target, unit.node_id, glossary))
                for chunk in unit.provenance.get('chunks', []):
                    attempts = chunk.get('attempts', [])
                    chosen = chunk.get('selected_attempt', 0)
                    if attempts and attempts[chosen].get('unit_repairs'):
                        report.findings.append(Finding(code='source_unit_restored', severity='review', unit_id=unit.node_id,
                                                       detail='Unité restaurée depuis une valeur source inchangée ; candidat brut conservé'))
        if fmt == "pdf":
            report = validate_pdf(source, result, report)
        artifacts["output"] = self.store.put(result)
        artifacts["report"] = self.store.json(report.model_dump())
        artifacts["translations"] = self.store.json({u.node_id: {"source": u.source, "target": u.target, "version": u.version,
                                                                "provenance": u.provenance} for u in units})
        with self.db.session() as s:
            job = self.owned(s, jid, token, lost)
            job.artifacts = artifacts
            job.status = "quality_blocked" if report.blocked else "ready_for_review"
            job.progress, job.lease_until, job.lease, job.error = 100, 0, None, None
            self.db.log(s, jid, job.status, {"findings": len(report.findings)})

    def work(self, once=False):
        # A DB-wide admission lock enforces one BC-250 inference consumer across workers.
        from .gpu_lock import gpu_lock
        while True:
            with gpu_lock(self.db, self.settings.root) as admitted:
                claimed = self.db.claim() if admitted else None
                if claimed:
                    self.run(*claimed)
            if once:
                return bool(claimed)
            if not claimed:
                time.sleep(2)
