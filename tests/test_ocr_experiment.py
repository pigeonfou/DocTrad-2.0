import importlib.util
import hashlib
import io
from pathlib import Path
from types import SimpleNamespace
import pytest

from doctrad2.models import catalog


spec = importlib.util.spec_from_file_location(
    "ocr_experiment", Path(__file__).parents[1] / "scripts" / "test-unlimited-ocr.py")
experiment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(experiment)

install_spec = importlib.util.spec_from_file_location(
    "ocr_install", Path(__file__).parents[1] / "scripts" / "install-unlimited-ocr.py")
installer = importlib.util.module_from_spec(install_spec)
install_spec.loader.exec_module(installer)


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


def test_install_reuses_verified_file_without_network(tmp_path, monkeypatch):
    (tmp_path / "model.gguf").write_bytes(b"abc")
    def unexpected(*args, **kwargs):
        raise AssertionError("network must not be used")
    monkeypatch.setattr(installer.urllib.request, "urlopen", unexpected)
    installer.install_file(tmp_path, "model.gguf", 3, hashlib.sha256(b"abc").hexdigest())


def test_install_preserves_invalid_existing_file(tmp_path):
    target = tmp_path / "model.gguf"
    target.write_bytes(b"old")
    with pytest.raises(RuntimeError, match="Empreinte incorrecte"):
        installer.install_file(tmp_path, target.name, 3, hashlib.sha256(b"abc").hexdigest())
    assert target.read_bytes() == b"old"


def test_install_bad_download_is_never_published(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"bad"))
    with pytest.raises(RuntimeError, match="SHA-256"):
        installer.install_file(tmp_path, "model.gguf", 3, hashlib.sha256(b"abc").hexdigest())
    assert list(tmp_path.iterdir()) == []


def test_install_is_pinned_and_atomic(tmp_path, monkeypatch):
    urls = []
    def download(url, **kwargs):
        urls.append(url)
        return io.BytesIO(b"abc")
    monkeypatch.setattr(installer.urllib.request, "urlopen", download)
    installer.install_file(tmp_path, "model.gguf", 3, hashlib.sha256(b"abc").hexdigest())
    assert f"/resolve/{installer.REVISION}/" in urls[0]
    assert (tmp_path / "model.gguf").read_bytes() == b"abc"
    assert len(list(tmp_path.iterdir())) == 1


def test_offline_install_requires_files(tmp_path):
    with pytest.raises(RuntimeError, match="hors ligne"):
        installer.install_file(tmp_path, "model.gguf", 3, "a" * 64, offline=True)


def test_runtime_reports_missing_library(tmp_path, monkeypatch, capsys):
    binary = tmp_path / "llama-mtmd-cli"
    binary.write_text("test")
    binary.chmod(0o755)
    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=127, stdout="", stderr="libmtmd.so: cannot open shared object file"))
    with pytest.raises(RuntimeError, match="diagnostics"):
        installer.runtime(binary)
    assert "libmtmd.so" in capsys.readouterr().out


def test_runtime_absence_is_distinct_from_rejection(monkeypatch):
    monkeypatch.setattr(installer, "candidates", lambda _: [])
    with pytest.raises(RuntimeError, match="Aucun llama-mtmd-cli trouvé"):
        installer.runtime()


def test_runtime_accepts_supported_explicit_path(tmp_path, monkeypatch):
    binary = tmp_path / "llama-mtmd-cli"
    binary.write_text("test")
    binary.chmod(0o755)
    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout="--mmproj --image --device", stderr=""))
    assert installer.runtime(binary) == binary.resolve()
