import importlib.util
from pathlib import Path
from types import SimpleNamespace

from doctrad2.models import catalog


spec = importlib.util.spec_from_file_location(
    "ocr_experiment", Path(__file__).parents[1] / "scripts" / "test-unlimited-ocr.py")
experiment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(experiment)


def test_ocr_cannot_be_mistaken_for_available_translation():
    models = catalog(SimpleNamespace(model_sha="a" * 64, runtime_sha="b" * 64))
    ocr = models[1]
    assert ocr["role"] == "ocr"
    assert not ocr["configured"]
    assert ocr["availability"] == "installation_required"
    assert len(ocr["files"]) == 2


def test_cli_uses_argument_list_and_vulkan():
    cmd = experiment.command(Path("/llama-mtmd-cli"), Path("/model with spaces.gguf"),
                             Path("/projector.gguf"), Path("/page.png"))
    assert cmd[cmd.index("-m") + 1] == "/model with spaces.gguf"
    assert cmd[cmd.index("--device") + 1] == "Vulkan0"
    assert cmd[cmd.index("--chat-template") + 1] == "deepseek-ocr"


def test_busy_runtime_is_detected(tmp_path, monkeypatch):
    (tmp_path / "123").mkdir()
    monkeypatch.setattr(experiment.os, "readlink", lambda _: "/opt/llama-server")
    assert experiment.busy(tmp_path)


def test_file_hash_matches_known_content(tmp_path):
    path = tmp_path / "model"
    path.write_bytes(b"abc")
    assert experiment.digest(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
