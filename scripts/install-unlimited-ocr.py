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


def candidates(explicit=None):
    if explicit:
        return [explicit.expanduser()]
    found = []
    located = shutil.which("llama-mtmd-cli")
    if located:
        found.append(Path(located))
    roots = [Path.home(), Path("/opt"), Path("/usr/local/bin")]
    for root in roots:
        for directory, dirs, files in os.walk(root, followlinks=False):
            depth = len(Path(directory).relative_to(root).parts)
            dirs[:] = sorted(d for d in dirs if d not in {
                "models", "hub", "node_modules", ".git", "venv", ".venv", "Trash"
            }) if depth < 8 else []
            if "llama-mtmd-cli" in files:
                found.append(Path(directory) / "llama-mtmd-cli")
    return list(dict.fromkeys(found))


def runtime(explicit=None):
    paths = candidates(explicit)
    if not paths:
        raise RuntimeError("Aucun llama-mtmd-cli trouvé dans PATH, le dossier utilisateur, /opt ou /usr/local/bin. "
                           "Le llama-server existant ne suffit pas pour cet essai multimodal CLI.")
    for path in paths:
        if not path.is_file() or not os.access(path, os.X_OK):
            print(f"REFUS {path}: absent ou non exécutable", flush=True)
            continue
        try:
            result = subprocess.run([str(path), "--help"], capture_output=True, text=True,
                                    errors="replace", timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"REFUS {path}: {exc}", flush=True)
            continue
        help_text = result.stdout + result.stderr
        missing = [flag for flag in ("--mmproj", "--image", "--device") if flag not in help_text]
        if result.returncode == 0 and not missing:
            print(f"Client multimodal détecté : {path}", flush=True)
            return path.resolve()
        print(f"REFUS {path}: code={result.returncode}, options absentes={missing}", flush=True)
        if result.returncode:
            print(help_text[-2000:], flush=True)
    raise RuntimeError("Aucun client multimodal accepté ; voir les diagnostics ci-dessus. "
                       "Aucun moteur ni service n'a été modifié.")


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
    parser.add_argument("--diagnose", action="store_true", help="Détection seule, sans téléchargement")
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error("Exécuter depuis le compte bc, sans sudo")
    binary = runtime(args.binary)
    if args.diagnose:
        print("Détection réussie ; compatibilité du modèle à vérifier par inférence.")
        return
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
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(str(exc)) from None
