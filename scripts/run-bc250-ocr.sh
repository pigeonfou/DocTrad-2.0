#!/usr/bin/env bash
# Execute a local OCR command, restoring only the runtime that was active initially.
set -euo pipefail
if [[ "${1:-}" != -- || $# -lt 2 ]]; then
  printf 'Usage: %s -- command [args...]\n' "$0" >&2
  exit 64
fi
shift
runtime=doctrad2-bc250-runtime.service
lock_dir="${XDG_CACHE_HOME:-$HOME/.cache}/doctrad2"
mkdir -p "$lock_dir"
exec 9>"$lock_dir/ocr-lifecycle.lock"
flock -n 9 || { printf 'OCR lifecycle already in use\n' >&2; exit 75; }

initially_active=0
if systemctl is-active --quiet "$runtime"; then initially_active=1; fi
runtime_pid=$(systemctl show -p MainPID --value "$runtime")
# ps also sees inference processes whose /proc/exe is unreadable by this account.
inference_processes() {
  ps -C llama-server,llama-cli,llama-mtmd-cli,sd-cli,sd-server -o pid=,stat=,comm= |
    awk '$2 !~ /^[ZX]/ {print $1, $3}' || true
}
processes=$(inference_processes)
while read -r pid name; do
  [[ -z "${pid:-}" ]] && continue
  if [[ "$initially_active" != 1 || "$pid" != "$runtime_pid" ]]; then
    printf 'BC250_BUSY pid=%s executable=%s; no service changed\n' "$pid" "$name" >&2
    exit 75
  fi
done <<< "$processes"

restore_required=0
cleanup() {
  result=$?
  trap - EXIT INT TERM
  if [[ "$restore_required" == 1 ]]; then
    # Another application may have started inference while the OCR was running.
    current_pid=$(systemctl show -p MainPID --value "$runtime")
    current_processes=$(inference_processes)
    while read -r pid name; do
      [[ -z "${pid:-}" ]] && continue
      if [[ "$pid" != "$current_pid" ]]; then
        printf 'TRANSLATION_RESTORE_DEFERRED pid=%s executable=%s\n' "$pid" "$name" >&2
        exit 75
      fi
    done <<< "$current_processes"
    if ! sudo -n /usr/bin/systemctl start "$runtime"; then
      printf 'TRANSLATION_RESTORE_FAILED\n' >&2
      exit 70
    fi
    ready=0
    for ((attempt=0; attempt<90; attempt++)); do
      if curl -fs --max-time 2 http://127.0.0.1:52365/health >/dev/null; then ready=1; break; fi
      sleep 2
    done
    if [[ "$ready" != 1 ]]; then
      printf 'TRANSLATION_HEALTH_FAILED\n' >&2
      exit 70
    fi
    printf 'TRANSLATION_RESTORED=active\n'
  else
    printf 'TRANSLATION_INITIAL_STATE_PRESERVED=inactive\n'
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [[ "$initially_active" == 1 ]]; then
  restore_required=1
  sudo -n /usr/bin/systemctl stop "$runtime"
fi
"$@"
