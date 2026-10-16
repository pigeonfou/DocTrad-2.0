import time
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from doctrad2.api import create_app
from doctrad2.db import User, Document, Job, Unit
from doctrad2.storage import Artifacts
from doctrad2.pipeline import Pipeline
from conftest import pdf


class FakeTranslator:
    count = 0
    def __init__(self, settings):
        pass
    def translate(self, text, context=None):
        FakeTranslator.count += 1
        return "Tension d’entrée 12 V", {"test": "not_real_inference"}
    def close(self):
        pass


def login(client, name="alice"):
    csrf = client.get("/v2/session").json()["csrf"]
    response = client.post("/v2/login", json={"username": name, "password": "a secure test password"}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf"]}


def user(db, name):
    with db.session() as s:
        s.add(User(name=name, password=PasswordHasher().hash("a secure test password")))


def test_full_job_correction_recompose_and_approval(settings, database):
    FakeTranslator.count = 0
    user(database, "alice")
    client = TestClient(create_app(settings, database))
    headers = login(client)
    doc = client.post("/v2/documents", files={"file": ("native.pdf", pdf())}, headers=headers).json()
    started = client.post(f"/v2/documents/{doc['id']}/jobs", json={}, headers=headers)
    assert started.status_code == 200
    jid = started.json()["id"]
    pipeline = Pipeline(settings, database, FakeTranslator)
    assert pipeline.work(once=True)
    status = client.get(f"/v2/jobs/{jid}").json()
    assert status["status"] == "ready_for_review", status
    assert FakeTranslator.count == 1
    unit = client.get(f"/v2/jobs/{jid}/units").json()[0]
    correction = client.patch(f"/v2/jobs/{jid}/units/{unit['id']}", json={"target": "Tension d’entrée 12 V", "version": 0}, headers=headers)
    assert correction.status_code == 200
    pipeline.work(once=True)
    assert FakeTranslator.count == 1
    assert client.post(f"/v2/jobs/{jid}/approve", headers=headers).json()["status"] == "approved"
    assert client.patch(f"/v2/jobs/{jid}/units/{unit['id']}", json={"target": "x", "version": 1}, headers=headers).status_code == 409
    assert client.get(f"/v2/jobs/{jid}/artifacts/output").status_code == 200
    with database.session() as s:
        assert len(s.get(Job, jid).artifacts["history"]) == 1


def test_critical_value_cannot_be_approved(settings, database):
    user(database, "alice")
    client = TestClient(create_app(settings, database))
    h = login(client)
    doc = client.post("/v2/documents", files={"file": ("native.pdf", pdf())}, headers=h).json()
    jid = client.post(f"/v2/documents/{doc['id']}/jobs", json={}, headers=h).json()["id"]
    pipeline = Pipeline(settings, database, FakeTranslator)
    pipeline.work(once=True)
    unit = client.get(f"/v2/jobs/{jid}/units").json()[0]
    client.patch(f"/v2/jobs/{jid}/units/{unit['id']}", json={"target": "Tension 21 V", "version": 0}, headers=h)
    pipeline.work(once=True)
    assert client.get(f"/v2/jobs/{jid}").json()["status"] == "quality_blocked"
    assert client.post(f"/v2/jobs/{jid}/approve", headers=h).status_code == 409


def test_auth_csrf_and_cross_user_isolation(settings, database):
    for name in ("alice", "bob"):
        user(database, name)
    client = TestClient(create_app(settings, database))
    assert client.get("/v2/jobs").status_code == 401
    h = login(client)
    assert client.post("/v2/documents", files={"file": ("x.pdf", pdf())}).status_code == 403
    doc = client.post("/v2/documents", files={"file": ("x.pdf", pdf())}, headers=h).json()
    jid = client.post(f"/v2/documents/{doc['id']}/jobs", json={}, headers=h).json()["id"]
    client.post("/v2/logout", headers=h)
    login(client, "bob")
    assert client.get(f"/v2/jobs/{jid}").status_code == 404
    assert client.get(f"/v2/jobs/{jid}/artifacts/source").status_code == 404


def test_lease_expiry_and_single_claim(settings, database):
    with database.session() as s:
        d = Document(owner="alice", name="x.pdf", source_sha="a" * 64, format="pdf")
        s.add(d)
        s.flush()
        job = Job(owner="alice", document_id=d.id)
        s.add(job)
        s.flush()
        jid = job.id
    first = database.claim()
    assert first[0] == jid
    assert database.claim() is None
    with database.session() as s:
        s.get(Job, jid).lease_until = time.time() - 1
    second = database.claim()
    assert second[0] == jid and second[1] != first[1]
    assert not database.heartbeat(*first)


def test_completed_units_survive_failure_and_resume(settings, database):
    FakeTranslator.count = 0
    store = Artifacts(settings.root)
    source = pdf()
    with database.session() as s:
        d = Document(owner="alice", name="x.pdf", source_sha=store.put(source), format="pdf")
        s.add(d)
        s.flush()
        job = Job(owner="alice", document_id=d.id)
        s.add(job)
        s.flush()
        jid = job.id
    pipeline = Pipeline(settings, database, FakeTranslator)
    pipeline.work(once=True)
    assert FakeTranslator.count == 1
    with database.session() as s:
        job = s.get(Job, jid)
        job.status, job.lease_until = "queued", 0
    pipeline.work(once=True)
    assert FakeTranslator.count == 1


def test_idempotent_job_creation(settings, database):
    user(database, "alice")
    client = TestClient(create_app(settings, database))
    headers = login(client) | {"Idempotency-Key": "same-import-request"}
    doc = client.post("/v2/documents", files={"file": ("x.pdf", pdf())}, headers=headers).json()
    first = client.post(f"/v2/documents/{doc['id']}/jobs", json={}, headers=headers)
    second = client.post(f"/v2/documents/{doc['id']}/jobs", json={}, headers=headers)
    assert first.json()["id"] == second.json()["id"]
    assert client.post(f"/v2/documents/{doc['id']}/jobs", json={"glossary": {"ground": "masse"}}, headers=headers).status_code == 409


def test_unconfigured_bc250_blocks_translation_start(settings, database):
    from dataclasses import replace
    user(database, "alice")
    client = TestClient(create_app(replace(settings, model_sha="", runtime_sha=""), database))
    headers = login(client)
    assert client.get('/health').json()['llm_configured'] is False
    doc = client.post('/v2/documents', files={'file': ('x.pdf', pdf())}, headers=headers).json()
    result = client.post(f"/v2/documents/{doc['id']}/jobs", json={}, headers=headers)
    assert result.status_code == 503


def test_recomposition_of_completed_older_contract_keeps_provenance_and_avoids_inference(settings, database):
    store = Artifacts(settings.root)
    with database.session() as s:
        document = Document(owner="alice", name="independent.pdf", source_sha=store.put(pdf()), format="pdf")
        s.add(document)
        s.flush()
        job = Job(owner="alice", document_id=document.id)
        s.add(job)
        s.flush()
        jid = job.id
    assert Pipeline(settings, database, FakeTranslator).work(once=True)
    with database.session() as s:
        job = s.get(Job, jid)
        contract = dict(job.contract)
        contract["translation_policy"] = "archived-policy"
        job.contract = contract
        job.status = "queued"
    def no_inference(settings):
        raise AssertionError("recomposition must not instantiate a translator")
    assert Pipeline(settings, database, no_inference).work(once=True)
    with database.session() as s:
        job = s.get(Job, jid)
        assert job.status == "ready_for_review"
        assert job.contract["translation_policy"] == "archived-policy"


def test_incomplete_older_contract_still_cannot_mix_machine_policies(settings, database):
    store = Artifacts(settings.root)
    with database.session() as s:
        document = Document(owner="alice", name="independent.pdf", source_sha=store.put(pdf()), format="pdf")
        s.add(document)
        s.flush()
        job = Job(owner="alice", document_id=document.id)
        s.add(job)
        s.flush()
        jid = job.id
    assert Pipeline(settings, database, FakeTranslator).work(once=True)
    with database.session() as s:
        job = s.get(Job, jid)
        unit = s.query(Unit).filter_by(job_id=jid).first()
        unit.target = None
        contract = dict(job.contract)
        contract["translation_policy"] = "archived-policy"
        job.contract = contract
        job.status = "queued"
    assert Pipeline(settings, database, FakeTranslator).work(once=True)
    with database.session() as s:
        job = s.get(Job, jid)
        assert job.status == "runtime_failed"
        assert job.error == "model_contract_changed_create_new_job"

