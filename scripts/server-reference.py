#!/usr/bin/env python3
"""Queue a fixed public reference through the real worker and export only its public outputs."""
from collections import Counter
import json
import os
from pathlib import Path
import time
from sqlalchemy import select
from doctrad2.config import Settings
from doctrad2.db import Database, Document, Job, User
from doctrad2.storage import Artifacts, digest, key
from doctrad2.prompts import TEMPLATE_SHA
from doctrad2.technical_prompt import PROMPT_SHA
from doctrad2.text_policy import POLICY_VERSION
from doctrad2.inference import LlamaTranslator
from doctrad2.layout import COMPOSITION_VERSION
from doctrad2.quality import QUALITY_VERSION

SOURCE_SHA = 'cc6a5ca2bd9fad41fce19136afd7aaca3315a783a52348a4984bf11d8b8e41f6'


def run_reference(settings, relative, expected_sha, label, output_name, export_suffix=''):
    source_sha = expected_sha
    db, store = Database(settings.database_url), Artifacts(settings.root)
    source = Path(__file__).resolve().parents[1] / relative
    data = source.read_bytes()
    if digest(data) != source_sha:
        raise SystemExit('Only the approved public source is allowed')
    jid = key([label, source_sha, settings.model_sha, settings.runtime_sha, TEMPLATE_SHA, PROMPT_SHA, POLICY_VERSION])[:36]
    with db.session() as s:
        job = s.get(Job, jid)
        if not job:
            owner = s.scalar(select(User.name).order_by(User.name).limit(1))
            if not owner:
                raise SystemExit('No local review account available')
            document = Document(owner=owner, name='Référence ' + label + ' — DocTrad 2.0.pdf', source_sha=store.put(data), format='pdf')
            s.add(document)
            s.flush()
            job = Job(id=jid, document_id=document.id, owner=owner)
            s.add(job)
            db.log(s, jid, 'reference_queued', {'source_sha': source_sha})
    with db.session() as s:
        job = s.get(Job, jid)
        if job.status == 'quality_blocked' and 'report' in job.artifacts:
            prior = store.read_json(job.artifacts['report']).get('metrics', {})
            if prior.get('composition_version') != COMPOSITION_VERSION or prior.get('quality_version') != QUALITY_VERSION:
                job.status, job.error, job.revision = 'queued', None, job.revision + 1
                db.log(s, jid, 'reference_recompose', {'composition': COMPOSITION_VERSION, 'quality': QUALITY_VERSION})
        if job.status == "runtime_failed" and ((job.error or "").startswith("llm_transport_failed") or job.error == "IndexError"):
            job.status, job.error = "queued", None
            db.log(s, jid, "reference_transport_resume")
    started = time.monotonic()
    last = None
    while time.monotonic() - started < 1200:
        with db.session() as s:
            job = s.get(Job, jid)
            state = (job.status, job.progress)
            artifacts = dict(job.artifacts)
            if state != last:
                print(json.dumps({'reference_job': jid, 'status': job.status, 'progress': job.progress}), flush=True)
                last = state
            if job.status in ('ready_for_review', 'quality_blocked', 'approved'):
                break
            if job.status == 'runtime_failed':
                translator = LlamaTranslator(settings)
                try:
                    print('REFERENCE_RUNTIME_DIAGNOSTIC=' + json.dumps(translator.validate()), flush=True)
                except Exception as exc:
                    print('REFERENCE_RUNTIME_DIAGNOSTIC=' + type(exc).__name__ + ':' + str(exc), flush=True)
                finally:
                    translator.close()
                raise SystemExit('Reference runtime failed: ' + (job.error or 'unknown'))
        time.sleep(5)
    else:
        raise SystemExit('Reference still processing after bounded wait; job remains resumable')
    export = Path('/var/lib/doctrad2-reference') / export_suffix
    export.mkdir(parents=True, exist_ok=True)
    export.chmod(0o755)
    report = store.read_json(artifacts['report'])
    manifest = {'job_id': jid, 'source_sha': source_sha, 'status': state[0], 'model_sha': settings.model_sha,
                'runtime_sha': settings.runtime_sha, 'template_sha': TEMPLATE_SHA, 'prompt_sha': PROMPT_SHA, 'translation_policy': POLICY_VERSION,
                'wait_seconds': round(time.monotonic() - started, 2), 'metrics': report.get('metrics'),
                'findings': dict(Counter(f['severity'] + ':' + f['code'] for f in report['findings']))}
    for name, sha in [(output_name, artifacts['output']),
                      ('report.json', artifacts['report']), ('translations.json', artifacts['translations'])]:
        target = export / name
        target.write_bytes(store.get(sha))
        target.chmod(0o644)
    (export / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    (export / 'manifest.json').chmod(0o644)
    print('PUBLIC_REFERENCE_RESULT=' + json.dumps(manifest, ensure_ascii=False), flush=True)


def main():
    settings = Settings.load()
    run_reference(settings, 'benchmarks/AN_PRC_167_source.pdf', SOURCE_SHA, 'AN-PRC167-reference-v1',
                  'DocTrad2_AN_PRC167_FR_TranslateGemma12B_Q4KM.pdf')
    run_reference(settings, 'benchmarks/general_equipment_source.pdf',
                  '40e3d24478e8ae219039c505f3faa3b0de6d5962c3f738d323f8b4a48146f2b2', 'General-equipment-v1',
                  'DocTrad2_General_Equipment_FR_TranslateGemma12B_Q4KM.pdf', 'general')


if __name__ == '__main__':
    os.umask(0o027)
    main()
