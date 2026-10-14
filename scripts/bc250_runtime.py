#!/usr/bin/env python3
"""Inspect existing local llama.cpp installation; never installs/builds or switches models."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def option(args, *names):
    for i, value in enumerate(args):
        if value in names and i + 1 < len(args):
            return args[i + 1]
        for name in names:
            if value.startswith(name + "="):
                return value.split("=", 1)[1]
    return None


def discover(proc=Path("/proc"), home=Path("/home/bc")):
    processes = []
    for pid in proc.glob("[0-9]*"):
        try:
            args = pid.joinpath("cmdline").read_bytes().decode().strip("\0").split("\0")
            if Path(args[0]).name != "llama-server":
                continue
            model = option(args, "-m", "--model")
            processes.append({"pid": int(pid.name), "binary": args[0], "model": model,
                              "port": option(args, "--port") or "8080", "host": option(args, "--host") or "127.0.0.1",
                              "context": option(args, "-c", "--ctx-size") or "unknown",
                              "device": option(args, "--device") or "auto",
                              "has_api_key": bool(option(args, "--api-key", "--api-key-file"))})
        except (OSError, UnicodeError, IndexError):
            continue
    binaries = [str(p) for p in [home / ".unsloth/llama.cpp/llama-server",
                home / ".unsloth/llama.cpp/build/bin/llama-server", home / "ai-build/llama.cpp/build-vulkan/bin/llama-server"] if p.is_file()]
    models = sorted(str(p) for base in [home / ".cache", home / ".unsloth", home / "models"] if base.exists()
                    for p in base.rglob("translategemma-12b-it.Q4_K_M.gguf"))
    return {"processes": processes, "binaries": binaries, "models": models}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["discover", "manifest", "launch"])
    parser.add_argument("--binary")
    parser.add_argument("--model")
    parser.add_argument("--key-file")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default="8098")
    args = parser.parse_args()
    if args.command == "discover":
        print(json.dumps(discover(), indent=2))
        return
    binary, model = Path(args.binary or ""), Path(args.model or "")
    if not binary.is_file() or not model.is_file() or model.name != "translategemma-12b-it.Q4_K_M.gguf":
        parser.error("Existing llama-server and TranslateGemma 12B Q4_K_M files required")
    if args.command == "manifest":
        print(json.dumps({"binary": str(binary), "model": str(model), "runtime_sha": sha(binary), "model_sha": sha(model),
                          "profile": "BC250-Vulkan-4096-single-slot", "version": subprocess.check_output([str(binary), "--version"], stderr=subprocess.STDOUT).decode().strip()}, indent=2))
        return
    if discover()["processes"]:
        parser.error("Un llama-server tourne déjà : réutiliser son endpoint direct ou arrêter son gestionnaire avant activation")
    if not args.key_file or not Path(args.key_file).is_file():
        parser.error("A local API key file is required")
    help_text = subprocess.check_output([str(binary), "--help"], stderr=subprocess.STDOUT).decode()
    flags = ["--device", "--jinja", "--api-key-file", "--parallel", "--ctx-size"]
    if any(flag not in help_text for flag in flags):
        parser.error("Existing runtime lacks required protocol flags; no automatic upgrade")
    command = [str(binary), "--model", str(model), "--host", args.host, "--port", args.port,
               "--device", "Vulkan0", "--n-gpu-layers", "99", "--ctx-size", "4096", "--parallel", "1",
               "--batch-size", "512", "--ubatch-size", "128", "--cache-type-k", "f16", "--cache-type-v", "f16",
               "--jinja", "--api-key-file", args.key_file]
    print("Launching existing Vulkan runtime:", shlex.join(command), flush=True)
    import os
    os.execv(str(binary), command)


if __name__ == "__main__":
    main()
