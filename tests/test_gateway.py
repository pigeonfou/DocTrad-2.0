import importlib.util
from pathlib import Path
import ssl
import subprocess
import threading
import httpx
import pytest

path = Path(__file__).resolve().parents[1] / 'scripts/bc250-gateway.py'
spec = importlib.util.spec_from_file_location('bc_gateway', path)
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


@pytest.fixture(scope='module')
def certificates(tmp_path_factory):
    root = tmp_path_factory.mktemp('tls')
    for name, purpose in [('client', 'clientAuth'), ('server', 'serverAuth')]:
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2',
                        '-subj', f'/CN={name}', '-addext', 'basicConstraints=critical,CA:TRUE',
                        '-addext', f'extendedKeyUsage={purpose}', '-addext', 'subjectAltName=IP:127.0.0.1',
                        '-keyout', str(root / (name + '.key')), '-out', str(root / (name + '.crt'))],
                        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return root


@pytest.fixture
def server(certificates):
    calls = []
    config = {'model': '/models/translategemma-12b-it.Q4_K_M.gguf', 'binary': '/bin/llama-server',
              'model_sha': 'a' * 64, 'runtime_sha': 'b' * 64}
    def forward(port, path, payload=None):
        calls.append((path, payload))
        if path == '/props':
            return {'model_path': config['model'], 'default_generation_settings': {'n_ctx': 4096}}
        if path == '/completion':
            return {'content': 'Entrée 12 V'}
        return {'tokens': [2, 17]}
    s = gateway.GatewayServer(('127.0.0.1', 0), gateway.make_handler(config, lambda _: 1234, forward))
    s.context = gateway.server_context(str(certificates / 'server.crt'), str(certificates / 'server.key'),
                                       str(certificates / 'client.crt'))
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    yield s, calls
    s.shutdown()
    s.server_close()
    t.join(timeout=2)


def client(certificates, server, identity=True):
    ctx = ssl.create_default_context(cafile=str(certificates / 'server.crt'))
    if identity:
        ctx.load_cert_chain(certificates / 'client.crt', certificates / 'client.key')
    return httpx.Client(base_url=f'https://127.0.0.1:{server[0].server_port}', verify=ctx, trust_env=False, timeout=3)


def test_mtls_authenticated_manifest_and_inference(certificates, server):
    with client(certificates, server) as c:
        assert c.get('/manifest').json()['model_sha'] == 'a' * 64
        result = c.post('/completion', json={'prompt': [2, 17], 'n_predict': 100, 'stream': False})
        assert result.json()['content'] == 'Entrée 12 V'


def test_missing_client_certificate_is_rejected_before_forwarding(certificates, server):
    with client(certificates, server, identity=False) as c:
        with pytest.raises(httpx.HTTPError):
            c.get('/props')
    assert server[1] == []


def test_model_control_routes_are_not_exposed(certificates, server):
    with client(certificates, server) as c:
        assert c.post('/api/inference/load', json={}).status_code == 404
        assert c.post('/props', json={}).status_code == 404
    assert server[1] == []


def test_output_and_body_limits(certificates, server):
    with client(certificates, server) as c:
        assert c.post('/completion', json={'prompt': [2], 'n_predict': 99999}).status_code == 422
        assert c.post('/tokenize', content=b'x' * (gateway.MAX_BODY + 1)).status_code == 413
    assert server[1] == []


def test_invalid_server_trust_is_rejected(server):
    with httpx.Client(trust_env=False, timeout=3) as c:
        with pytest.raises(httpx.HTTPError):
            c.get(f'https://127.0.0.1:{server[0].server_port}/props')
