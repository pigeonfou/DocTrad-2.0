#!/usr/bin/env bash
# Install a separate repository-scoped runner on the existing DocTrad application host.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run with sudo'; exit 1; }
ADMIN=${SUDO_USER:-}
[[ -n $ADMIN && $ADMIN != root ]] || { echo 'Start from the Ubuntu account already authenticated with gh'; exit 2; }
command -v gh >/dev/null || { echo 'GitHub CLI gh must be installed and authenticated by the Ubuntu administrator'; exit 2; }
runuser -u "$ADMIN" -- gh auth status >/dev/null 2>&1 || { echo 'The Ubuntu administrator is not authenticated with gh'; exit 2; }
[[ $(uname -m) == x86_64 ]] || { echo 'This profile requires Linux x64'; exit 2; }
ACCOUNT=doctrad2-runner
DIR=/home/$ACCOUNT/actions-runner
id "$ACCOUNT" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$ACCOUNT"
install -d -m 0750 -o "$ACCOUNT" -g "$ACCOUNT" "$DIR"
TEMP=$(mktemp -d)
trap 'rm -rf "$TEMP"; unset TOKEN' EXIT
if [[ ! -f $DIR/.runner ]]; then
    runuser -u "$ADMIN" -- gh api repos/actions/runner/releases/latest > "$TEMP/release.json"
    python3 - "$TEMP/release.json" "$TEMP/runner.tar.gz" <<'PY'
import hashlib,json,sys,urllib.request
release=json.load(open(sys.argv[1]))
assets=[a for a in release['assets'] if a['name'].startswith('actions-runner-linux-x64-') and a['name'].endswith('.tar.gz')]
if len(assets)!=1: raise SystemExit('Ambiguous official runner asset')
asset=assets[0]
digest=asset.get('digest','')
if not digest.startswith('sha256:'): raise SystemExit('Official SHA256 absent: download refused')
url=asset['browser_download_url']
if not url.startswith('https://github.com/actions/runner/releases/download/'): raise SystemExit('Unexpected runner download origin')
h=hashlib.sha256()
with urllib.request.urlopen(url,timeout=120) as response, open(sys.argv[2],'wb') as out:
 while chunk:=response.read(1024*1024): h.update(chunk); out.write(chunk)
if h.hexdigest()!=digest.split(':',1)[1]: raise SystemExit('Runner checksum mismatch')
PY
    tar -xzf "$TEMP/runner.tar.gz" -C "$DIR"
    chown -R "$ACCOUNT:$ACCOUNT" "$DIR"
    TOKEN=$(runuser -u "$ADMIN" -- gh api -X POST repos/pigeonfou/DocTrad-2.0/actions/runners/registration-token --jq .token)
    cd "$DIR"
    runuser -u "$ACCOUNT" -- ./config.sh --unattended --url https://github.com/pigeonfou/DocTrad-2.0 --token "$TOKEN" --name doctrad2-ubuntu --labels doctrad2-deploy --work _work
    unset TOKEN
else
    python3 - "$DIR/.runner" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]))
if r.get('gitHubUrl','').rstrip('/').lower()!='https://github.com/pigeonfou/doctrad-2.0': raise SystemExit('Existing runner belongs to another repository')
PY
fi
cd "$DIR"
[[ -f .service ]] || ./svc.sh install "$ACCOUNT"
./svc.sh start
./svc.sh status
# Prepare the isolated deployment helper; application/model installation is separate.
install -d -m 0755 /usr/local/src
if [[ ! -d /usr/local/src/DocTrad-2.0/.git ]]; then
    git clone https://github.com/pigeonfou/DocTrad-2.0.git /usr/local/src/DocTrad-2.0
fi
[[ $(git -C /usr/local/src/DocTrad-2.0 remote get-url origin) == https://github.com/pigeonfou/DocTrad-2.0.git ]] || exit 2
[[ $(stat -c %u /usr/local/src/DocTrad-2.0) == 0 ]] || { echo 'Deployment checkout must belong to root'; exit 2; }
install -m 0755 -o root -g root /usr/local/src/DocTrad-2.0/deploy/doctrad2-deploy /usr/local/sbin/doctrad2-deploy
printf '%s\n' "$ACCOUNT ALL=(root) NOPASSWD: /usr/local/sbin/doctrad2-deploy" > "$TEMP/sudoers"
visudo -cf "$TEMP/sudoers"
install -m 0440 -o root -g root "$TEMP/sudoers" /etc/sudoers.d/doctrad2-deploy
runuser -u "$ADMIN" -- gh api repos/pigeonfou/DocTrad-2.0/actions/runners --jq '.runners[] | select(.name=="doctrad2-ubuntu") | {name,status,labels:[.labels[].name]}'
echo 'DocTrad V2 runner installed; existing DocTrad and BC250 services preserved.'
