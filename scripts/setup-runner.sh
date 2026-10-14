#!/usr/bin/env bash
# Executed once on the intended Ubuntu application host, with an already authenticated gh account.
# Registers a repository-specific runner without printing the registration token.
set -euo pipefail
[[ $EUID != 0 ]] || { echo 'Run as the dedicated non-root runner user'; exit 2; }
command -v gh >/dev/null
DIR=${1:?Existing extracted GitHub runner directory required}
[[ -x $DIR/config.sh ]] || exit 2
TOKEN=$(gh api -X POST repos/pigeonfou/DocTrad-2.0/actions/runners/registration-token --jq .token)
trap 'unset TOKEN' EXIT
cd "$DIR"
./config.sh --unattended --url https://github.com/pigeonfou/DocTrad-2.0 --token "$TOKEN" --name doctrad2-ubuntu --labels doctrad2-deploy --work _work
unset TOKEN
echo 'Runner registered. Service installation uses the existing host administration process.'
