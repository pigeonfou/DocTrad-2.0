import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('runtime_service', Path(__file__).resolve().parents[1] / 'scripts/install-bc250-runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def test_refuses_concurrent_runtime_before_binding(tmp_path):
    process = tmp_path / '123'
    process.mkdir()
    (process / 'cmdline').write_bytes(b'/other/build/llama-server\0--model\0other.gguf\0')
    with pytest.raises(RuntimeError, match='another_llama_server_is_running'):
        runtime.ensure_available(tmp_path)


def test_service_uses_enrolled_runtime_and_single_gpu_slot():
    text = runtime.unit()
    assert f'ExecStart={runtime.BINARY} --model {runtime.MODEL}' in text
    assert '--host 127.0.0.1 --port 52365' in text
    assert '--device Vulkan0 --n-gpu-layers 99 --ctx-size 4096 --parallel 1' in text
    assert 'Restart=on-failure' in text
    assert 'ExecStartPre=/usr/bin/python3' in text
    assert 'User=bc' in text
    assert '--no-jinja --chat-template chatml' in text
    assert ' --jinja' not in text


def test_port_probe_allows_tcp_time_wait(monkeypatch, tmp_path):
    calls = []
    class Socket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def setsockopt(self, *args): calls.append(('reuse', args))
        def bind(self, address): calls.append(('bind', address))
    monkeypatch.setattr(runtime.socket, 'socket', Socket)
    runtime.ensure_available(tmp_path)
    assert calls[0] == ('reuse', (runtime.socket.SOL_SOCKET, runtime.socket.SO_REUSEADDR, 1))
    assert calls[1] == ('bind', ('127.0.0.1', 52365))
