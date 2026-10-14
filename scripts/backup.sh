#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || exit 1
set -a
source /etc/doctrad2/app.env
set +a
DEST=/var/backups/doctrad2/$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 0700 "$DEST"
WAS_RUNNING=0
WEB_RUNNING=0
systemctl is-active --quiet doctrad2-worker && WAS_RUNNING=1
systemctl is-active --quiet doctrad2-web && WEB_RUNNING=1
systemctl stop doctrad2-web doctrad2-worker
trap 'if [[ $WAS_RUNNING == 1 ]]; then systemctl start doctrad2-worker; fi; if [[ $WEB_RUNNING == 1 ]]; then systemctl start doctrad2-web; fi' EXIT
if [[ ${DOCTRAD2_DATABASE:-} == postgresql* ]]; then
    DB_URL=${DOCTRAD2_DATABASE/postgresql+psycopg:/postgresql:}
    runuser -u doctrad2 --preserve-environment -- pg_dump "$DB_URL" > "$DEST/database.sql"
else
    python3 - "$DOCTRAD2_ROOT/jobs.sqlite" "$DEST/database.sqlite" <<'PY'
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as source, sqlite3.connect(sys.argv[2]) as target:
    source.backup(target)
PY
fi
tar -C "${DOCTRAD2_ROOT:-/var/lib/doctrad2}" -cf "$DEST/objects.tar" objects
cp /etc/doctrad2/app.env "$DEST/app.env"
readlink /opt/doctrad2/current > "$DEST/release"
echo 'Coordinated local backup completed'
