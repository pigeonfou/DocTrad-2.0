#!/usr/bin/env bash
set -euo pipefail
DEST=${1:?Destination wheelhouse required}
mkdir -p "$DEST"
python3 -m pip wheel --wheel-dir "$DEST" .
(cd "$DEST" && sha256sum *.whl > SHA256SUMS)
echo 'Copy this wheelhouse to the matching Python/OS target; inference weights are existing local files.'
