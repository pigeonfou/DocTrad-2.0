#!/usr/bin/env python3
"""Register DocTrad2 without letting OneForAll overwrite its independent installation."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time


def lan_endpoint(config):
    """Path routing has an IP virtual host; no split DNS is required on clients."""
    if config.get('routing_mode') == 'paths':
        return f"https://{config['lan_ip']}:{config['lan_port']}/doctrad2/", ['--cacert', config['certificate']]
    host = 'doctrad2.' + config['domain']
    return f"https://{host}:{config['lan_port']}/", [
        '--resolve', f"{host}:{config['lan_port']}:{config['lan_ip']}", '--cacert', config['certificate']]


def main():
    if os.geteuid() != 0:
        raise SystemExit('Root required')
    manager = Path('/opt/oneforall/manager/oneforall')
    site = Path('/etc/oneforall/site.json')
    if not (manager / 'common.py').is_file() or not site.is_file():
        print(json.dumps({'oneforall': 'not_local', 'stock_nginx': Path('/etc/nginx/sites-enabled').is_dir(),
                          'native_health': 'http://127.0.0.1:8097/health'}))
        return
    release = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('ofa_patch', release / 'packaging/oneforall/patch.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sources = {name: (manager / (name + '.py')).read_text() for name in ('common', 'render', 'deploy', 'cli')}
    patched = {name: getattr(module, 'patch_' + name)(text) for name, text in sources.items()}
    registry = Path('/etc/oneforall/local-apps.json')
    old_registry = registry.read_bytes() if registry.exists() else None
    old_site = site.read_bytes()
    config = json.loads(old_site)
    entries = json.loads(old_registry) if old_registry else {}
    entries['doctrad2'] = {'name': 'DocTrad 2.0', 'description': 'Traduction documentaire locale sur BC-250, révision et PDF natif.',
        'repo': 'pigeonfou/DocTrad-2.0', 'ref': 'main', 'kind': 'python', 'port': 8097, 'health': '/health',
        'root': '/opt/doctrad2/current', 'legacy': '/opt/doctrad2', 'managed_externally': True,
        'strip_prefix': True, 'services': ['web', 'worker'], 'systemd_services': ['doctrad2-web', 'doctrad2-worker']}
    # Inherit the existing DocTrad exposure decision instead of opening unrelated services.
    if 'doctrad' in config.get('public_apps', []) and 'doctrad2' not in config['public_apps']:
        config['public_apps'].append('doctrad2')
    backups = Path('/var/backups/doctrad2') / ('oneforall-' + str(time.time_ns()))
    backups.mkdir(parents=True, mode=0o700)
    for name, text in sources.items():
        (backups / (name + '.py')).write_text(text)
    (backups / 'site.json').write_bytes(old_site)
    if old_registry:
        (backups / 'local-apps.json').write_bytes(old_registry)
    external = manager / 'external_apps.py'
    old_external = external.read_bytes() if external.exists() else None
    def atomic(path, data, mode=0o644):
        pending = path.with_name(path.name + '.doctrad2-pending')
        pending.write_bytes(data if isinstance(data, bytes) else data.encode())
        pending.chmod(mode)
        os.replace(pending, path)
    try:
        atomic(external, (release / 'packaging/oneforall/external_apps.py').read_bytes())
        for name, text in patched.items():
            atomic(manager / (name + '.py'), text)
        atomic(registry, json.dumps(entries, ensure_ascii=False, indent=2)+'\n', 0o600)
        atomic(site, json.dumps(config, ensure_ascii=False, indent=2)+'\n', 0o600)
        program = "import sys;sys.path.insert(0,sys.argv[1]);from cli import reload_front,status;reload_front();status()"
        result = subprocess.run(['/usr/bin/python3', '-I', '-c', program, str(manager)], check=True, capture_output=True, text=True)
        records = json.loads(result.stdout.strip().splitlines()[-1]).get('checks', [])
        record = next((x for x in records if x.get('id') == 'doctrad2'), {})
        summary = {'oneforall': 'registered', 'routing_mode': config.get('routing_mode', 'subdomains'),
                   'public_enabled': config.get('public_enabled') and 'doctrad2' in config.get('public_apps', []),
                   'public_url': record.get('url'), 'public_status': record.get('status'),
                   'lan_url': (f"https://{config['lan_ip']}:{config['lan_port']}/doctrad2/" if config.get('routing_mode') == 'paths' else f"https://doctrad2.{config['domain']}:{config['lan_port']}/")}
        summary['lan_url'], tls_args = lan_endpoint(config)
        checks = {}
        for suffix, expected in [('', 200), ('static/app.js', 200), ('static/style.css', 200), ('v2/session', 200), ('v2/jobs', 401)]:
            probe = subprocess.run(['curl', '--noproxy', '*', '--silent', '--show-error', '--max-time', '8',
                *tls_args,
                '--output', '/dev/null', '--write-out', '%{http_code}', summary['lan_url'] + suffix], capture_output=True, text=True)
            checks[suffix or 'interface'] = probe.stdout.strip()
            if probe.returncode or probe.stdout.strip() != str(expected):
                raise RuntimeError('OneForAll frontend validation failed: ' + suffix)
        summary['frontend_checks'] = checks
        Path('/var/lib/doctrad2/oneforall-integration.json').write_text(json.dumps(summary))
        print(json.dumps(summary))
    except Exception:
        for name, text in sources.items():
            atomic(manager / (name + '.py'), text)
        atomic(site, old_site, 0o600)
        if old_registry is None:
            registry.unlink(missing_ok=True)
        else:
            atomic(registry, old_registry, 0o600)
        if old_external is None:
            external.unlink(missing_ok=True)
        else:
            atomic(external, old_external)
        subprocess.run(['/usr/bin/python3', '-I', '-c', "import sys;sys.path.insert(0,sys.argv[1]);from cli import reload_front;reload_front()", str(manager)], capture_output=True, check=False)
        raise


if __name__ == '__main__':
    with open('/run/lock/oneforall.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        main()
