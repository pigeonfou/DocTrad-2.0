#!/usr/bin/env python3
"""Initialize the separate Ubuntu application state; never modify the BC-250 or v1 data."""
import json
import os
from pathlib import Path
import secrets
import shlex
import subprocess


def command(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs).stdout.strip()


def envfile(path):
    result = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
                continue
            name, value = line.split('=', 1)
            values = shlex.split(value, comments=True)
            result[name.strip()] = values[0] if values else ''
    return result


def main():
    if os.geteuid() != 0:
        raise SystemExit('Root required')
    config = Path('/etc/doctrad2/app.env')
    if config.exists():
        print('Existing V2 configuration preserved')
        return
    command(['apt-get', 'install', '-y', 'python3-venv', 'postgresql', 'tesseract-ocr', 'tesseract-ocr-eng'])
    if subprocess.run(['id', 'doctrad2'], capture_output=True).returncode:
        command(['useradd', '--system', '--home-dir', '/var/lib/doctrad2', '--shell', '/usr/sbin/nologin', 'doctrad2'])
    command(['systemctl', 'start', 'postgresql'])
    for query, create in [("SELECT 1 FROM pg_roles WHERE rolname='doctrad2'", ['createuser', 'doctrad2']),
                          ("SELECT 1 FROM pg_database WHERE datname='doctrad2'", ['createdb', '-O', 'doctrad2', 'doctrad2'])]:
        if command(['runuser', '-u', 'postgres', '--', 'psql', '-tAc', query]) != '1':
            command(['runuser', '-u', 'postgres', '--', *create])
    config.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    # No guess of the BC-250 runtime port, key or hashes. Runtime connection is a separate gate.
    values = {'DOCTRAD2_ROOT': '/var/lib/doctrad2', 'DOCTRAD2_DATABASE': 'postgresql+psycopg:///doctrad2',
              'DOCTRAD2_SECRET': secrets.token_urlsafe(48), 'DOCTRAD2_LLM_URL': 'http://127.0.0.1:8098',
              'DOCTRAD2_LLM_KEY': '', 'DOCTRAD2_MODEL_SHA': '', 'DOCTRAD2_RUNTIME_SHA': '',
              'DOCTRAD2_SECURE_COOKIE': '1', 'TESSDATA_PREFIX': '/usr/share/tesseract-ocr/5/tessdata'}
    fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        out.write('\n'.join(f'{k}="{v}"' for k, v in values.items()) + '\n')
    print('Separate V2 database and configuration initialized; BC250 connection pending')


def initialize_users(python):
    old = envfile(Path('/etc/docutranslate/docutranslate.env'))
    credentials = []
    old_python = Path('/opt/docutranslate/current/.venv/bin/python')
    if old_python.is_file():
        environment = os.environ.copy()
        environment.update(old)
        environment['DATABASE_URL'] = old.get('DATABASE_URL', 'postgresql+psycopg://docutranslate@localhost/docutranslate')
        script = "import os,json; from sqlalchemy import create_engine,text; e=create_engine(os.environ['DATABASE_URL']);\nwith e.connect() as c: print(json.dumps([dict(r._mapping) for r in c.execute(text('SELECT username,password FROM users'))]))"
        try:
            credentials = json.loads(command(['runuser', '-u', 'docutranslate', '--preserve-environment', '--', str(old_python), '-c', script], env=environment))
        except (subprocess.CalledProcessError, ValueError):
            print('V1 accounts not readable; a separate local admin will be generated')
    # Hashes travel only through the local child process stdin, never workflow output or argv.
    program = "import sys,json; from doctrad2.config import Settings; from doctrad2.db import Database,User; db=Database(Settings.load().database_url);\nwith db.session() as s:\n for u in json.load(sys.stdin):\n  if not s.get(User,u['username']): s.add(User(name=u['username'],password=u['password']))"
    if not credentials:
        from argon2 import PasswordHasher
        password = secrets.token_urlsafe(24)
        credentials = [{'username': 'admin', 'password': PasswordHasher().hash(password)}]
        path = Path('/etc/doctrad2/initial-admin')
        if not path.exists():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as out:
                out.write('admin\n' + password + '\n')
    command(['runuser', '-u', 'doctrad2', '--preserve-environment', '--', python, '-c', program], input=json.dumps(credentials))
    print(f'V2 accounts initialized: {len(credentials)}; no passwords or hashes logged')


if __name__ == '__main__':
    import sys
    initialize_users(sys.argv[2]) if len(sys.argv) > 1 and sys.argv[1] == 'users' else main()
