#!/usr/bin/env python3
"""Supervise the enrolled BC250 model directly, without a Studio dependency."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

BINARY = Path('/home/bc/.unsloth/llama.cpp/llama-server')
MODEL = Path('/home/bc/.cache/huggingface/hub/models--mradermacher--translategemma-12b-it-GGUF/snapshots/41d7c8aa650b26791225ad9d0597e674e680da96/translategemma-12b-it.Q4_K_M.gguf')
EXPECTED = {'binary': '05367ddadee77b4d33634046d058bbb86101910a668b8759f5cd2265faab341a',
            'model': 'b7aac4b4be7ab0c49b6556c29c4467e74313df7f1e95d9f9676bb2adf0afa528'}
PORT = 52365
SERVICE = 'doctrad2-bc250-runtime.service'
INSTALLED = Path('/usr/local/lib/doctrad2/install-bc250-runtime.py')
CONFIG = Path('/home/bc/.config/doctrad2/gateway.json')


def validate_files():
    config = json.loads(CONFIG.read_text())
    for name, path in [('binary', BINARY), ('model', MODEL)]:
        if config[name] != str(path):
            raise RuntimeError('enrollment_path_changed_' + name)
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != EXPECTED[name] or config[name.replace('binary', 'runtime') + '_sha'] != actual:
            raise RuntimeError('enrollment_hash_changed_' + name)
        stat = path.stat()
        if config['file_stats'][name] != [stat.st_size, stat.st_mtime_ns]:
            raise RuntimeError('gateway_file_statistics_changed_' + name)


def ensure_available(proc=Path('/proc')):
    for entry in proc.glob('[0-9]*'):
        try:
            args = entry.joinpath('cmdline').read_bytes().split(b'\0')
            if Path(os.fsdecode(args[0])).name == 'llama-server':
                raise RuntimeError('another_llama_server_is_running')
        except (OSError, IndexError):
            continue
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', PORT))


def unit():
    return f'''[Unit]
Description=DocTrad2 TranslateGemma 12B on BC250 Vulkan
After=network.target
StartLimitIntervalSec=300
StartLimitBurst=5
[Service]
Type=simple
User=bc
WorkingDirectory=/home/bc
Environment=HOME=/home/bc
ExecStartPre=/usr/bin/python3 {INSTALLED} --check
ExecStart={BINARY} --model {MODEL} --host 127.0.0.1 --port {PORT} --device Vulkan0 --n-gpu-layers 99 --ctx-size 4096 --parallel 1 --batch-size 512 --ubatch-size 128 --cache-type-k f16 --cache-type-v f16 --jinja
Restart=on-failure
RestartSec=10
TimeoutStartSec=180
TimeoutStopSec=30
KillSignal=SIGINT
NoNewPrivileges=true
UMask=0077
[Install]
WantedBy=multi-user.target
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    validate_files()
    if args.check:
        ensure_available()
        return
    if os.geteuid() != 0:
        raise SystemExit('Run the installer with sudo')
    target = Path('/etc/systemd/system') / SERVICE
    if target.exists() and target.read_text() != unit():
        raise SystemExit('Existing service differs; refusing to overwrite it')
    active = subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE]).returncode == 0
    if not active:
        ensure_available()
    help_text = subprocess.check_output([str(BINARY), '--help'], stderr=subprocess.STDOUT, text=True)
    for flag in ('--device', '--n-gpu-layers', '--parallel', '--ctx-size', '--cache-type-k', '--cache-type-v', '--jinja'):
        if flag not in help_text:
            raise SystemExit('Enrolled runtime lacks ' + flag)
    INSTALLED.parent.mkdir(parents=True, exist_ok=True)
    INSTALLED.write_bytes(Path(__file__).read_bytes())
    INSTALLED.chmod(0o644)
    target.write_text(unit())
    target.chmod(0o644)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', SERVICE], check=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(90):
        try:
            with opener.open(f'http://127.0.0.1:{PORT}/props', timeout=2) as response:
                props = json.load(response)
            if props.get('model_path') != str(MODEL) or props.get('default_generation_settings', {}).get('n_ctx') != 4096:
                raise SystemExit('Unexpected native model contract')
            print(json.dumps({'service': SERVICE, 'native_port': PORT, 'model_sha': EXPECTED['model'],
                              'runtime_sha': EXPECTED['binary'], 'context': 4096, 'ready': True}))
            return
        except (OSError, ValueError):
            time.sleep(2)
    raise SystemExit('Model did not become ready; inspect systemctl status ' + SERVICE)


if __name__ == '__main__':
    main()
