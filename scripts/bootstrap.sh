#!/usr/bin/env bash
# One initial host enrollment; subsequent updates are handled by GitHub Actions.
set -euo pipefail
[[ $EUID == 0 ]] || exit 1
SOURCE=$(cd -- "$(dirname -- "$0")/.." && pwd)
apt-get update
apt-get install -y python3-venv postgresql nginx tesseract-ocr tesseract-ocr-eng curl git
id doctrad2 >/dev/null 2>&1 || useradd --system --home-dir /var/lib/doctrad2 --shell /usr/sbin/nologin doctrad2
systemctl enable --now postgresql
runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='doctrad2'" | grep -q 1 || runuser -u postgres -- createuser doctrad2
runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='doctrad2'" | grep -q 1 || runuser -u postgres -- createdb -O doctrad2 doctrad2
[[ -f /etc/doctrad2/app.env ]] || python3 "$SOURCE/scripts/bootstrap-local.py"
install -m 0755 "$SOURCE/deploy/doctrad2-deploy" /usr/local/sbin/doctrad2-deploy
bash "$SOURCE/scripts/install.sh"
set -a
source /etc/doctrad2/app.env
set +a
# Initial password is stored only in a root-readable file, not GitHub logs.
/opt/doctrad2/current/.venv/bin/python - <<'PY'
import os, secrets
from pathlib import Path
from argon2 import PasswordHasher
from doctrad2.db import Database, User
password = secrets.token_urlsafe(24)
import subprocess
password_hash = PasswordHasher().hash(password)
# Database insertion runs under the application peer-authenticated account.
subprocess.run(['runuser', '-u', 'doctrad2', '--preserve-environment', '--', '/opt/doctrad2/current/.venv/bin/python', '-c', "from doctrad2.config import Settings; from doctrad2.db import Database,User; import sys; db=Database(Settings.load().database_url);\nwith db.session() as s:\n if not s.get(User,'admin'): s.add(User(name='admin',password=sys.stdin.read()))"], input=password_hash, text=True, check=True)
path = Path('/etc/doctrad2/initial-admin')
if not path.exists():
 fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
 with os.fdopen(fd, 'w') as f: f.write('admin\n'+password+'\n')
PY
echo 'Application installed. Integrate the nginx snippet in the existing OneForAll server; credentials remain local.'
