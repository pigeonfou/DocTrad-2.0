#!/usr/bin/env python3
"""mTLS-only LAN gateway to an already resident loopback llama-server. Python stdlib + OpenSSL."""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import hashlib
import os
from pathlib import Path
import pwd
import shutil
import socket
import ssl
import subprocess
import threading
import urllib.request
import urllib.error

CLIENT_CERT_SHA = '5f60a6051edc52632b1d7dc1f16bb3c8c75d2e07213cac6faa573b6b38c31f38'
POST_PATHS = {'/tokenize', '/completion', '/apply-template'}
GET_PATHS = {'/props', '/manifest'}
MAX_BODY = 1024 * 1024


def private_ip(value):
    address = ipaddress.ip_address(value)
    return address.is_loopback or any(address in ipaddress.ip_network(n) for n in
                    ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16') if address.version == 4)


def resident(config):
    candidates = []
    for pid in Path('/proc').glob('[0-9]*'):
        try:
            argv = pid.joinpath('cmdline').read_bytes().decode().strip('\0').split('\0')
            if argv[0] != config['binary'] or config['model'] not in argv:
                continue
            index = argv.index('--port')
            candidates.append(int(argv[index + 1]))
        except (OSError, UnicodeError, IndexError, ValueError):
            continue
    if len(candidates) != 1:
        raise ValueError('resident_model_not_available')
    for name in ('binary', 'model'):
        stat = Path(config[name]).stat()
        if [stat.st_size, stat.st_mtime_ns] != config['file_stats'][name]:
            raise ValueError('resident_files_changed')
    return candidates[0]


def upstream(port, path, payload=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}',
         data=json.dumps(payload).encode() if payload is not None else None,
         headers={'Content-Type': 'application/json'})
    with opener.open(req, timeout=90) as response:
        return json.load(response)


def make_handler(config, resolver=resident, forward=upstream):
    # Queue rather than parallel inference; this gateway never loads another GPU model.
    completion_lock = threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *args):
            pass  # Never log document bodies, prompts or certificate private material.
        def reply(self, status, value):
            data = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = True
        def do_GET(self):
            self.handle_request('GET')
        def do_POST(self):
            self.handle_request('POST')
        def handle_request(self, method):
            if not private_ip(self.client_address[0]):
                return self.reply(403, {'error': 'LAN_only'})
            if self.path not in (GET_PATHS if method == 'GET' else POST_PATHS):
                return self.reply(404, {'error': 'route_not_allowed'})
            payload = None
            if method == 'POST':
                try:
                    length = int(self.headers.get('Content-Length', '-1'))
                    if not 0 < length <= MAX_BODY or self.headers.get('Transfer-Encoding'):
                        return self.reply(413, {'error': 'bounded_json_body_required'})
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError()
                    if self.path == '/completion':
                        if payload.get('stream') or not 1 <= payload.get('n_predict', 0) <= 1800:
                            return self.reply(422, {'error': 'bounded_nonstreaming_inference_required'})
                except (ValueError, TypeError):
                    return self.reply(422, {'error': 'invalid_json_request'})
            try:
                port = resolver(config)
                props = forward(port, '/props')
                if props.get('model_path') != config['model'] or props.get('default_generation_settings', {}).get('n_ctx', 0) < 3000:
                    raise ValueError('resident_model_contract_changed')
                if self.path == '/manifest':
                    return self.reply(200, {k: config[k] for k in ('model_sha', 'runtime_sha', 'model', 'binary')})
                if self.path == '/props':
                    return self.reply(200, props)
                if self.path == '/completion':
                    if not completion_lock.acquire(timeout=90):
                        return self.reply(503, {'error': 'inference_busy'})
                    try:
                        # Re-resolve after waiting: a manager may have replaced the resident process.
                        result = forward(resolver(config), self.path, payload)
                    finally:
                        completion_lock.release()
                else:
                    result = forward(port, self.path, payload)
                return self.reply(200, result)
            except (OSError, ValueError, urllib.error.URLError):
                return self.reply(503, {'error': 'resident_runtime_unavailable'})
    return Handler


def server_context(cert, key, client_cert):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    context.load_verify_locations(cafile=client_cert)
    context.verify_mode = ssl.CERT_REQUIRED
    return context


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16
    def get_request(self):
        raw, address = self.socket.accept()
        raw.settimeout(10)
        try:
            tls = self.context.wrap_socket(raw, server_side=True)
            tls.settimeout(100)
            return tls, address
        except Exception:
            raw.close()
            raise


def serve(config):
    handler = make_handler(config)
    server = GatewayServer((config['bind'], config['port']), handler)
    server.context = server_context(config['server_cert'], config['server_key'], config['client_cert'])
    print('BC250 mTLS gateway active; resident model and manager unchanged', flush=True)
    server.serve_forever()


def install(args):
    if os.geteuid() != 0:
        raise SystemExit('Run installation with sudo')
    account = os.environ.get('SUDO_USER')
    if account != 'bc':
        raise SystemExit('Start from the existing bc account')
    user = pwd.getpwnam(account)
    home = Path(user.pw_dir)
    manifest = json.loads((home / '.config/doctrad2/runtime-manifest.json').read_text())
    if Path(manifest['model']).name != 'translategemma-12b-it.Q4_K_M.gguf':
        raise SystemExit('Expected verified local model manifest required')
    if args.bind:
        bind = args.bind
    else:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(('192.168.6.1', 9))
            bind = probe.getsockname()[0]
    if not private_ip(bind) or ipaddress.ip_address(bind).is_loopback:
        raise SystemExit('Explicit private LAN bind address required')
    directory = home / '.config/doctrad2'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chown(directory, user.pw_uid, user.pw_gid)
    client = directory / 'client.crt'
    incoming = Path(args.client_cert).read_bytes()
    if hashlib.sha256(incoming).hexdigest() != CLIENT_CERT_SHA:
        raise SystemExit('Unexpected application enrollment certificate')
    if client.exists() and client.read_bytes() != incoming:
        raise SystemExit('Client identity changed; refusing automatic replacement')
    client.write_bytes(incoming)
    cert, key = directory / 'gateway.crt', directory / 'gateway.key'
    if cert.exists() != key.exists():
        raise SystemExit('Incomplete server identity; refusing replacement')
    if not cert.exists():
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '825',
                        '-subj', '/CN=DocTrad2-BC250', '-addext', f'subjectAltName=IP:{bind}',
                        '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'extendedKeyUsage=serverAuth',
                        '-keyout', str(key), '-out', str(cert)], check=True,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    config = {k: manifest[k] for k in ('model', 'binary', 'model_sha', 'runtime_sha')}
    config.update(bind=bind, port=8098, server_cert=str(cert), server_key=str(key), client_cert=str(client))
    config['file_stats'] = {n: [Path(config[n]).stat().st_size, Path(config[n]).stat().st_mtime_ns] for n in ('model', 'binary')}
    port = resident(config)  # No load/start/switch command is issued.
    if upstream(port, '/props').get('model_path') != config['model']:
        raise SystemExit('Resident model identity changed')
    cfg = directory / 'gateway.json'
    cfg.write_text(json.dumps(config))
    for path in (client, cert, key, cfg):
        os.chown(path, user.pw_uid, user.pw_gid)
        path.chmod(0o600)
    code = home / '.local/share/doctrad2/bc250-gateway.py'
    code.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(__file__, code)
    os.chown(code, user.pw_uid, user.pw_gid)
    code.chmod(0o644)
    unit = f'''[Unit]
Description=DocTrad2 BC250 mTLS gateway to resident Vulkan runtime
After=network.target
[Service]
User=bc
ExecStart=/usr/bin/python3 {code} --serve --config {cfg}
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadOnlyPaths={directory}
UMask=0077
[Install]
WantedBy=multi-user.target
'''
    Path('/etc/systemd/system/doctrad2-bc250-gateway.service').write_text(unit)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', 'doctrad2-bc250-gateway'], check=True)
    subprocess.run(['systemctl', 'is-active', '--quiet', 'doctrad2-bc250-gateway'], check=True)
    print(json.dumps({'gateway_url': f'https://{bind}:8098', 'server_certificate_b64': base64.b64encode(cert.read_bytes()).decode(),
                      'model_sha': config['model_sha'], 'runtime_sha': config['runtime_sha']}, indent=2))
    print('Only public certificate and fingerprints shown; private keys remain on their respective machines.')


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--serve', action='store_true')
    group.add_argument('--install', action='store_true')
    parser.add_argument('--config')
    parser.add_argument('--client-cert')
    parser.add_argument('--bind')
    args = parser.parse_args()
    if args.install:
        if not args.client_cert:
            parser.error('--client-cert required')
        install(args)
    else:
        if not args.config:
            parser.error('--config required')
        serve(json.loads(Path(args.config).read_text()))


if __name__ == '__main__':
    main()
