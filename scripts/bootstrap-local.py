#!/usr/bin/env python3
"""Prepare local BC-250 app configuration from an existing llama-server, without Unsloth API."""
import argparse
import json
import os
from pathlib import Path
import secrets
from bc250_runtime import discover, option, sha


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", default="/etc/doctrad2")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Root required to protect local credentials")
    base = Path(args.config_dir)
    if (base / "app.env").exists():
        parser.error("Existing configuration preserved: use explicit administration for changes")
    found = discover()
    matches = [p for p in found["processes"] if p["model"] and Path(p["model"]).name == "translategemma-12b-it.Q4_K_M.gguf"]
    if len(matches) != 1:
        parser.error("Exactly one resident TranslateGemma 12B Q4_K_M runtime is required; no model switch performed")
    process = matches[0]
    argv = Path(f"/proc/{process['pid']}/cmdline").read_bytes().decode().strip("\0").split("\0")
    api_key = option(argv, "--api-key") or ""
    key_file = option(argv, "--api-key-file")
    if key_file:
        api_key = Path(key_file).read_text().strip().splitlines()[0]
    import urllib.request
    url = f"http://127.0.0.1:{process['port']}"
    request = urllib.request.Request(url + "/props", headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
    # Only loopback, no env HTTP proxy, no document payload.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=5) as response:
        props = json.load(response)
    if "source_lang_code" not in str(props.get("chat_template", "")):
        parser.error("Resident runtime lacks the official TranslateGemma template; configuration not written")
    base.mkdir(mode=0o750, parents=True, exist_ok=True)
    values = {"DOCTRAD2_ROOT": "/var/lib/doctrad2", "DOCTRAD2_DATABASE": "postgresql+psycopg:///doctrad2",
              "DOCTRAD2_SECRET": secrets.token_urlsafe(48), "DOCTRAD2_LLM_URL": url,
              "DOCTRAD2_LLM_KEY": api_key, "DOCTRAD2_MODEL_SHA": sha(process["model"]),
              "DOCTRAD2_RUNTIME_SHA": sha(process["binary"]), "DOCTRAD2_SECURE_COOKIE": "1",
              "TESSDATA_PREFIX": "/usr/share/tesseract-ocr/5/tessdata"}
    # Conservative systemd EnvironmentFile subset: generated values cannot inject new assignments.
    if any(any(c in value for c in '\n\r\"\\') for value in values.values()):
        parser.error("Credential requires explicit safely quoted environment configuration")
    path = base / "app.env"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(f'{k}="{v}"' for k, v in values.items()) + "\n")
    print("Local configuration created; existing resident engine reused directly. No credentials printed.")


if __name__ == "__main__":
    main()
