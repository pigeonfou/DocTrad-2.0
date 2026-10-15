#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Installation requires root'; exit 1; }
SOURCE=${DOCTRAD2_SOURCE:-$(cd -- "$(dirname -- "$0")/.." && pwd)}
SHA=${1:-$(git -C "$SOURCE" rev-parse HEAD)}
[[ $SHA =~ ^[0-9a-f]{40}$ ]] || exit 2
if [[ ! -f /etc/doctrad2/app.env ]]; then
    PREPARE=$(mktemp)
    git -C "$SOURCE" show "$SHA:scripts/prepare-server.py" > "$PREPARE"
    python3 "$PREPARE"
    rm -f "$PREPARE"
fi
command -v python3 >/dev/null
id doctrad2 >/dev/null 2>&1 || useradd --system --home-dir /var/lib/doctrad2 --shell /usr/sbin/nologin doctrad2
install -d -m 0750 -o doctrad2 -g doctrad2 /var/lib/doctrad2
install -d -m 0755 /opt/doctrad2/releases
RELEASE=/opt/doctrad2/releases/$SHA
[[ ! -e $RELEASE ]] || { echo 'Release already exists: refusing to mutate an immutable release'; exit 2; }
install -d -m 0755 "$RELEASE"
git -C "$SOURCE" archive "$SHA" | tar -x -C "$RELEASE"
python3 -m venv "$RELEASE/.venv"
if [[ -n ${DOCTRAD2_WHEELHOUSE:-} ]]; then
    "$RELEASE/.venv/bin/pip" install --no-index --find-links "$DOCTRAD2_WHEELHOUSE" "$RELEASE"
else
    "$RELEASE/.venv/bin/pip" install "$RELEASE"
fi
chown root:doctrad2 /etc/doctrad2/app.env
chmod 0640 /etc/doctrad2/app.env
install -m 0644 "$RELEASE/deploy/doctrad2-web.service" "$RELEASE/deploy/doctrad2-worker.service" /etc/systemd/system/
# Backup precedes schema initialization/bascule; source env is root-owned configuration, never repository code.
install -d -m 0700 /var/backups/doctrad2
if [[ -e /opt/doctrad2/current ]]; then
    bash "$RELEASE/scripts/backup.sh"
fi
set -a
source /etc/doctrad2/app.env
set +a
runuser -u doctrad2 --preserve-environment -- "$RELEASE/.venv/bin/doctrad2" migrate
"$RELEASE/.venv/bin/python" "$RELEASE/scripts/prepare-server.py" users "$RELEASE/.venv/bin/python"
if [[ -e /opt/doctrad2/current ]]; then
    python3 "$RELEASE/scripts/integrate-oneforall.py"
fi
python3 "$RELEASE/scripts/client-identity.py"
"$RELEASE/.venv/bin/python" "$RELEASE/scripts/configure-gateway.py" "$RELEASE/deploy/bc250-connection.json"
set -a
source /etc/doctrad2/app.env
set +a
PREVIOUS=$(readlink /opt/doctrad2/current || true)
ln -s "$RELEASE" /opt/doctrad2/current.new
mv -Tf /opt/doctrad2/current.new /opt/doctrad2/current
systemctl daemon-reload
systemctl enable doctrad2-web
systemctl restart doctrad2-web
if [[ ${DOCTRAD2_MODEL_SHA:-} =~ ^[0-9a-f]{64}$ && ${DOCTRAD2_RUNTIME_SHA:-} =~ ^[0-9a-f]{64}$ ]]; then
    systemctl enable doctrad2-worker
    systemctl restart doctrad2-worker
else
    systemctl stop doctrad2-worker
    echo 'Application installed; translation worker held until BC250 runtime is configured'
fi
READY=0
for attempt in {1..20}; do
    if curl -fsS http://127.0.0.1:8097/health >/dev/null; then READY=1; break; fi
    sleep 1
done
if [[ $READY != 1 ]]; then
    if [[ -n $PREVIOUS ]]; then
        ln -s "$PREVIOUS" /opt/doctrad2/current.rollback
        mv -Tf /opt/doctrad2/current.rollback /opt/doctrad2/current
        systemctl restart doctrad2-web doctrad2-worker
    fi
    echo 'Health failed; previous application release restored if available'; exit 1
fi
printf '%s\n' "$PREVIOUS" > /opt/doctrad2/previous
printf '%s\n' "$SHA" > "$RELEASE/VALIDATED"
echo "Installed tested release $SHA (quality acceptance is separate)"

python3 "$RELEASE/scripts/integrate-oneforall.py"
install -d -m 0755 -o doctrad2 -g doctrad2 /var/lib/doctrad2-reference
runuser -u doctrad2 --preserve-environment -- "$RELEASE/.venv/bin/python" "$RELEASE/scripts/server-reference.py"
