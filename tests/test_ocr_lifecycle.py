import os
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).parents[1] / 'scripts/run-bc250-ocr.sh'


@pytest.mark.parametrize('active,processes,command_code,late,expected,actions', [
    (False, '123 S llama-server', 0, False, 75, []),
    (True, '100 S llama-server\n123 S llama-server', 0, False, 75, []),
    (False, '', 0, False, 0, ['command']),
    (False, '', 65, False, 65, ['command']),
    (True, '100 S llama-server', 0, False, 0, ['stop', 'command', 'start']),
    (True, '100 S llama-server', 65, False, 65, ['stop', 'command', 'start']),
    (True, '100 S llama-server', 0, True, 75, ['stop', 'command']),
    (False, '123 Z llama-server', 0, False, 0, ['command']),
    (True, '100 S llama-server\n123 Z llama-server', 0, False, 0, ['stop', 'command', 'start']),
])
def test_lifecycle_preserves_other_workloads_and_initial_service_state(
        tmp_path, active, processes, command_code, late, expected, actions):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    log = tmp_path / 'actions'
    helpers = {
        'systemctl': 'if [ "$1" = show ]; then echo 100; else exit ' + ('0' if active else '3') + '; fi',
        'ps': 'if [ -f "$TEST_LATE_FILE" ]; then echo "123 S llama-server"; else printf "%s\\n" "$TEST_PROCESSES"; fi',
        'sudo': 'printf "%s\\n" "$3" >> "$TEST_ACTIONS"',
        'curl': 'exit 0',
        'ocr-command': 'echo command >> "$TEST_ACTIONS"; if [ "$TEST_LATE" = 1 ]; then touch "$TEST_LATE_FILE"; fi; exit "$TEST_COMMAND_CODE"',
    }
    for name, body in helpers.items():
        path = bin_dir / name
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)
    env = {**os.environ, 'PATH': str(bin_dir) + ':' + os.environ['PATH'],
           'HOME': str(tmp_path), 'XDG_CACHE_HOME': str(tmp_path / 'cache'),
           'TEST_ACTIONS': str(log), 'TEST_PROCESSES': processes,
           'TEST_LATE': '1' if late else '0', 'TEST_LATE_FILE': str(tmp_path / 'late'),
           'TEST_COMMAND_CODE': str(command_code)}
    result = subprocess.run(['bash', str(SCRIPT), '--', 'ocr-command'], env=env,
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == expected, result.stderr
    assert (log.read_text().splitlines() if log.exists() else []) == actions
