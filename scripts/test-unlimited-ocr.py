#!/usr/bin/env python3
"""Explicit, offline, single-page experiment on the BC-250. No downloads/services."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def recognized_text(output):
    """Ignore control/grounding tokens when deciding whether OCR read anything."""
    output = re.sub(r"<\|det\|>.*?<\|/det\|>", "", output, flags=re.DOTALL)
    output = re.sub(r"<\|/?(?:ref|grounding)\|>", "", output)
    for token in ("<｜end▁of▁sentence｜>", "<｜begin▁of▁sentence｜>", "<｜▁pad▁｜>"):
        output = output.replace(token, "")
    return output.strip()


def command(binary, model, projector, image):
    return [str(binary), "-m", str(model), "--mmproj", str(projector),
            "--image", str(image), "-p", "document parsing.",
            "--chat-template", "deepseek-ocr", "--device", "Vulkan0",
            "--n-gpu-layers", "99", "--temp", "0", "--repeat-penalty", "1.0",
            "--flash-attn", "off", "--no-warmup", "-n", "2600", "-c", "16384"]


def busy(proc=Path("/proc")):
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            executable = Path(os.readlink(entry / "exe")).name
        except (OSError, PermissionError):
            continue
        if executable in {"llama-server", "llama-cli", "llama-mtmd-cli"}:
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "model", "projector", "image", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    for name in ("binary", "model", "projector", "image"):
        path = getattr(args, name).resolve(strict=True)
        if not path.is_file():
            parser.error(f"{name}: fichier attendu")
        setattr(args, name, path)
    if args.binary.name != "llama-mtmd-cli":
        parser.error("Utiliser le llama-mtmd-cli existant, compatible deepseek2-ocr")
    # Reserve the destination before any expensive work; never overwrite a report.
    args.output.mkdir(parents=True, exist_ok=False)
    lock_path = Path.home() / ".cache" / "doctrad2" / "ocr-test.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if busy():
            raise SystemExit("BC-250 occupée : libérer le runtime existant avant le test")
        manifest = {"model": "Unlimited-OCR-GGUF", "role": "ocr", "experimental": True,
                    "files": {name: {"path": str(getattr(args, name)), "sha256": digest(getattr(args, name))}
                              for name in ("binary", "model", "projector", "image")},
                    "translation_performed": False, "started": time.time()}
        invocation = command(args.binary, args.model, args.projector, args.image)
        manifest["command"] = invocation
        try:
            with (args.output / "ocr.txt").open("w") as out, (args.output / "runtime.log").open("w") as err:
                result = subprocess.run(invocation, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                        timeout=900, check=False, start_new_session=True)
            manifest["runtime_returncode"] = result.returncode
            manifest["returncode"] = result.returncode
            manifest["status"] = "completed_requires_review" if result.returncode == 0 else "failed"
            if result.returncode == 0:
                text = recognized_text((args.output / "ocr.txt").read_text(encoding="utf-8", errors="replace"))
                manifest["recognized_characters"] = len(text)
                if not any(char.isalnum() for char in text):
                    manifest.update(status="empty_ocr", returncode=65)
        except subprocess.TimeoutExpired:
            manifest.update(status="timeout", returncode=124)
        finally:
            manifest["finished"] = time.time()
            (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest["returncode"]


if __name__ == "__main__":
    raise SystemExit(main())
