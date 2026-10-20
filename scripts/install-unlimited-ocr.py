#!/usr/bin/env python3
"""Prepare the pinned OCR experiment on BC-250; never modify running services."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request

REVISION = "0dc781d8a23f52963918ebd5b2d1b9fe61504661"
REPOSITORY = "sahilchachra/Unlimited-OCR-GGUF"
FILES = {
    "Unlimited-OCR-Q5_K_M.gguf": (2219208704, "3f3fc21627c8998cc5b9f682d913ad392f84f72d7037ab465f50a1c8c46d02c2"),
    "mmproj-Unlimited-OCR-F16.gguf": (811876448, "4f28c295e1fcf67a97488e356f2b4372da4702b77fdfad0fa138b5821325743c"),
}


def verified(path, size, sha):
    if not path.is_file() or path.stat().st_size != size:
        return False
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest() == sha


def runtime(explicit=None):
    candidates = [explicit] if explicit else [
        Path.home() / ".unsloth/llama.cpp/llama-mtmd-cli",
        Path.home() / ".unsloth/llama.cpp/build/bin/llama-mtmd-cli",
        Path.home() / "ai-build/llama.cpp/build-vulkan/bin/llama-mtmd-cli",
    ]
    for path in candidates:
        if path and path.is_file() and os.access(path, os.X_OK):
            result = subprocess.run([str(path), "--help"], capture_output=True, text=True, timeout=30)
            help_text = result.stdout + result.stderr
            if result.returncode == 0 and all(flag in help_text for flag in ("--mmproj", "--image", "--device")):
                return path.resolve()
    raise RuntimeError("llama-mtmd-cli compatible introuvable ; aucun moteur n'a été compilé ou modifié")


def install_file(directory, name, size, sha, offline=False):
    target = directory / name
    if verified(target, size, sha):
        print(f"Déjà vérifié : {name}", flush=True)
        return
    if target.exists():
        raise RuntimeError(f"Empreinte incorrecte : {target} ; fichier conservé, installation interrompue")
    if offline:
        raise RuntimeError(f"Fichier absent en mode hors ligne : {target}")
    if shutil.disk_usage(directory).free < size + 512 * 1024 * 1024:
        raise RuntimeError("Espace disque insuffisant (fichier + réserve de 512 Mio)")
    url = f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}"
    print(f"Téléchargement épinglé : {name} ({size / 1024**3:.2f} Gio)", flush=True)
    fd, temporary = tempfile.mkstemp(prefix=name + ".", suffix=".part", dir=directory)
    part = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as output, urllib.request.urlopen(url, timeout=60) as response:
            received = 0
            while chunk := response.read(4 * 1024 * 1024):
                received += len(chunk)
                if received > size:
                    raise RuntimeError("Taille téléchargée supérieure à la taille épinglée")
                output.write(chunk)
        if not verified(part, size, sha):
            raise RuntimeError("Téléchargement invalide : taille ou SHA-256 incorrect")
        # Atomic creation without overwriting a concurrent installation.
        os.link(part, target)
    finally:
        part.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--directory", type=Path, default=Path.home() / ".local/share/doctrad2/models/unlimited-ocr")
    parser.add_argument("--offline", action="store_true", help="Vérifier uniquement les fichiers déjà présents")
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error("Exécuter depuis le compte bc, sans sudo")
    binary = runtime(args.binary)
    args.directory.mkdir(parents=True, exist_ok=True)
    for name, (size, sha) in FILES.items():
        install_file(args.directory, name, size, sha, args.offline)
    with binary.open("rb") as handle:
        binary_sha = hashlib.file_digest(handle, "sha256").hexdigest()
    manifest = {"repository": REPOSITORY, "revision": REVISION, "binary": str(binary),
                "runtime_sha256": binary_sha, "model": str(args.directory / next(iter(FILES))),
                "projector": str(args.directory / "mmproj-Unlimited-OCR-F16.gguf"),
                "files": {name: {"size": size, "sha256": sha} for name, (size, sha) in FILES.items()},
                "status": "installed_not_inference_validated"}
    (args.directory / "installation.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    print("Installation vérifiée. Aucun service arrêté ou démarré. Test d'inférence restant.")


if __name__ == "__main__":
    main()
