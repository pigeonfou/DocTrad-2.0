#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || exit 1
SHA=${1:-}
[[ $SHA =~ ^[0-9a-f]{40}$ ]] || exit 2
RELEASE=/opt/doctrad2/releases/$SHA
[[ -f $RELEASE/VALIDATED ]] || { echo 'Only installed validated releases can be restored'; exit 2; }
systemctl stop doctrad2-worker
ln -s "$RELEASE" /opt/doctrad2/rollback.new
mv -Tf /opt/doctrad2/rollback.new /opt/doctrad2/current
systemctl restart doctrad2-web doctrad2-worker
curl --retry 10 --retry-delay 1 --retry-connrefused -fsS http://127.0.0.1:8097/health
