"""Persistent registration of independently deployed local Python services."""
import json
from pathlib import Path
import re

REGISTRY = Path('/etc/oneforall/local-apps.json')


def registered_apps(path=None):
    path = Path(path) if path else REGISTRY
    if not path.is_file():
        return {}
    entries = json.loads(path.read_text())
    for app, spec in entries.items():
        if not re.fullmatch(r'[a-z][a-z0-9-]{1,30}', app):
            raise ValueError('Invalid external application identifier')
        if spec.get('kind') != 'python' or type(spec.get('port')) is not int or not 1024 <= spec['port'] <= 65535:
            raise ValueError('External application requires a local Python HTTP port')
        if not re.fullmatch(r'/[A-Za-z0-9/_.-]+', spec.get('root', '')) or '..' in Path(spec['root']).parts:
            raise ValueError('Invalid external application root')
        if spec.get('health') != '/health' or spec.get('managed_externally') is not True:
            raise ValueError('Invalid external application contract')
        if not spec.get('systemd_services') or any(not re.fullmatch(r'[a-zA-Z0-9_.@-]+', s) for s in spec['systemd_services']):
            raise ValueError('Invalid external service names')
    return entries


def extend_catalog(catalog):
    entries = registered_apps()
    if set(entries) & set(catalog):
        raise ValueError('External registration cannot replace a managed application')
    return dict(catalog, **entries)


def extend_state(base):
    entries = registered_apps()
    result = {k: v for k, v in base.items() if not v.get('managed_externally') or k in entries}
    for app, spec in entries.items():
        root = Path(spec['root'])
        if root.is_dir():
            result[app] = {'enabled': spec.get('enabled', True), 'managed_externally': True,
                           'sha': root.resolve().name, 'repo': spec.get('repo', '')}
    return result


def refuse_external(app, catalog):
    if catalog[app].get('managed_externally'):
        raise ValueError('Cette application est déployée et sauvegardée depuis son propre dépôt.')
