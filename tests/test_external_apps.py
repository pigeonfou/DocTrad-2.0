import importlib.util
import json
from pathlib import Path
import pytest

root = Path(__file__).resolve().parents[1] / 'packaging/oneforall'
spec = importlib.util.spec_from_file_location('ofa_external', root / 'external_apps.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def descriptor(tmp_path):
    return {'doctrad2': {'kind': 'python', 'port': 8097, 'root': str(tmp_path), 'health': '/health',
                         'managed_externally': True, 'systemd_services': ['doctrad2-web', 'doctrad2-worker']}}


def test_registry_merges_catalog_without_replacing_managed_apps(tmp_path, monkeypatch):
    path = tmp_path / 'apps.json'
    path.write_text(json.dumps(descriptor(tmp_path)))
    monkeypatch.setattr(module, 'REGISTRY', path)
    assert set(module.extend_catalog({'doctrad': {}})) == {'doctrad', 'doctrad2'}
    with pytest.raises(ValueError):
        module.extend_catalog({'doctrad2': {}})


def test_external_state_is_persistent_and_not_installed_without_root(tmp_path, monkeypatch):
    path = tmp_path / 'apps.json'
    entries = descriptor(tmp_path / 'current')
    path.write_text(json.dumps(entries))
    monkeypatch.setattr(module, 'REGISTRY', path)
    assert 'doctrad2' not in module.extend_state({})
    (tmp_path / 'current').mkdir()
    assert module.extend_state({})['doctrad2']['managed_externally']
    with pytest.raises(ValueError):
        module.refuse_external('doctrad2', entries)


def test_registry_rejects_nginx_or_service_injection(tmp_path):
    path = tmp_path / 'apps.json'
    value = descriptor(tmp_path)
    value['doctrad2']['systemd_services'] = ['doctrad2-web; touch /tmp/x']
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        module.registered_apps(path)
