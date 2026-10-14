#!/usr/bin/env python3
"""One real local inference test; no model switch, restart, download or Studio API."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.request

PREFIX = '<bos><start_of_turn>user\nYou are a professional English (en) to French (fr) translator. Your goal is to accurately convey the meaning and nuances of the original English text while adhering to French grammar, vocabulary, and cultural sensitivities.\nProduce only the French translation, without any additional explanations or commentary. Please translate the following English text into French:\n\n\n'
SUFFIX = '<end_of_turn>\n<start_of_turn>model\n'
TEMPLATE_SHA = '8cc87f7b5cb3e30c5a8d1438387cb1376e1ed4eb934804500c10c466731e2ea5'

def request(port, path, payload=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}',
          data=json.dumps(payload).encode() if payload is not None else None,
          headers={'Content-Type': 'application/json'})
    with opener.open(req, timeout=90) as response:
        return json.load(response)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=52365)
    args = parser.parse_args()
    props = request(args.port, '/props')
    model = props.get('model_path', '')
    if Path(model).name != 'translategemma-12b-it.Q4_K_M.gguf':
        raise SystemExit('The expected resident model is not loaded')
    processes = []
    for pid in Path('/proc').glob('[0-9]*'):
        try:
            argv = pid.joinpath('cmdline').read_bytes().decode().strip('\0').split('\0')
            if Path(argv[0]).name == 'llama-server' and model in argv:
                processes.append(argv[0])
        except (OSError, UnicodeError, IndexError):
            pass
    if len(processes) != 1:
        raise SystemExit('Cannot identify exactly one local model process')
    source = 'Input voltage: 12 V. Operating temperature: -20 to 55 degrees Celsius.'
    prompt = PREFIX + source + SUFFIX
    encoded = request(args.port, '/tokenize', {'content': prompt, 'add_special': False, 'parse_special': True})
    tokens = encoded.get('tokens')
    if not tokens or len(tokens) > 1800:
        raise SystemExit('Tokenizer or budget validation failed')
    started = time.monotonic()
    result = request(args.port, '/completion', {'prompt': tokens, 'n_predict': 256, 'temperature': 0,
                     'seed': 42, 'cache_prompt': True, 'stream': False})
    if result.get('stopped_limit') or result.get('truncated') or result.get('stop_type') == 'limit' or not result.get('content'):
        raise SystemExit('Incomplete inference result')
    inference_seconds = round(time.monotonic() - started, 3)
    manifest = {'model': model, 'binary': processes[0], 'model_sha': sha(model), 'runtime_sha': sha(processes[0]),
                'native_port': args.port, 'context': props.get('default_generation_settings', {}).get('n_ctx'),
                'template_sha': TEMPLATE_SHA, 'input_tokens': len(tokens), 'source': source,
                'translation': result['content'].strip(), 'inference_seconds': inference_seconds,
                'timings': result.get('timings', {})}
    directory = Path.home() / '.config/doctrad2'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    dest = directory / 'runtime-manifest.json'
    dest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    dest.chmod(0o600)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
