#!/usr/bin/env python3
"""Apply a public, user-enrolled BC250 gateway manifest only after mutual TLS and inference pass."""
import base64
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from doctrad2.config import Settings
from doctrad2.inference import LlamaTranslator
from doctrad2.quality import check_text


def main():
    manifest_path = Path(sys.argv[1])
    if not manifest_path.is_file():
        print('BC250 gateway enrollment pending')
        return
    if os.geteuid() != 0:
        raise SystemExit('Root required')
    value = json.loads(manifest_path.read_text())
    cert = base64.b64decode(value['server_certificate_b64'], validate=True)
    if b'BEGIN CERTIFICATE' not in cert or b'PRIVATE KEY' in cert:
        raise SystemExit('Public server certificate required')
    folder = Path('/etc/doctrad2')
    pending = folder / 'gateway-ca.pending.crt'
    pending.write_bytes(cert)
    pending.chmod(0o644)
    settings = replace(Settings.load(), llm_url=value['gateway_url'], model_sha=value['model_sha'],
                       runtime_sha=value['runtime_sha'], llm_ca=str(pending))
    if not settings.llm_url.startswith('https://') or not settings.client_cert or not settings.client_key:
        raise SystemExit('HTTPS and local client identity required')
    translator = LlamaTranslator(settings)
    try:
        translator.validate()
        identity = translator.request('/manifest')
        if any(identity.get(k) != value[k] for k in ('model_sha', 'runtime_sha')):
            raise SystemExit('Runtime fingerprints mismatch')
        source = 'Input voltage: 12 V.'
        target, provenance = translator.translate(source)
        if any(f.severity == 'critical' for f in check_text(source, target, 'setup')) or target == source:
            raise SystemExit('Real gateway translation failed validation')
    finally:
        translator.close()
    final = folder / 'gateway-ca.crt'
    os.replace(pending, final)
    env = folder / 'app.env'
    updates = {'DOCTRAD2_LLM_URL': settings.llm_url, 'DOCTRAD2_LLM_CA': str(final),
               'DOCTRAD2_MODEL_SHA': settings.model_sha, 'DOCTRAD2_RUNTIME_SHA': settings.runtime_sha}
    lines = [line for line in env.read_text().splitlines() if line.split('=', 1)[0] not in updates]
    lines += [f'{k}="{v}"' for k, v in updates.items()]
    temp = folder / 'app.env.pending'
    temp.write_text('\n'.join(lines)+'\n')
    temp.chmod(0o640)
    import grp
    os.chown(temp, 0, grp.getgrnam('doctrad2').gr_gid)
    os.replace(temp, env)
    print('BC250 mutual TLS, fingerprints and real technical translation verified')
    print(json.dumps({'input_tokens': provenance['chunks'][0]['input_tokens'], 'timings': provenance['chunks'][0]['timings']}))


if __name__ == '__main__':
    main()
