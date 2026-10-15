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
