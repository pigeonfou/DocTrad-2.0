#!/usr/bin/env python3
"""Generate a local mTLS identity; print only its public certificate for BC250 enrollment."""
import base64
import grp
import os
from pathlib import Path
import subprocess


def main():
    if os.geteuid() != 0:
        raise SystemExit('Root required')
    folder = Path('/etc/doctrad2')
    cert, key = folder / 'client.crt', folder / 'client.key'
    if cert.exists() != key.exists():
        raise SystemExit('Incomplete TLS identity; refusing replacement')
    if not key.exists():
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '825',
                        '-subj', '/CN=DocTrad2-client', '-addext', 'basicConstraints=critical,CA:TRUE',
                        '-addext', 'keyUsage=critical,digitalSignature,keyCertSign',
                        '-addext', 'extendedKeyUsage=clientAuth', '-keyout', str(key), '-out', str(cert)],
                        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    group = grp.getgrnam('doctrad2').gr_gid
    os.chown(folder, 0, group)
    folder.chmod(0o750)
    os.chown(key, 0, group)
    key.chmod(0o640)
    cert.chmod(0o644)
    env = folder / 'app.env'
    text = env.read_text()
    for name, path in [('DOCTRAD2_CLIENT_CERT', cert), ('DOCTRAD2_CLIENT_KEY', key)]:
        if not any(line.startswith(name + '=') for line in text.splitlines()):
            text += f'{name}="{path}"\n'
    env.write_text(text)
    env.chmod(0o640)
    print('DOCTRAD2_PUBLIC_CLIENT_CERT=' + base64.b64encode(cert.read_bytes()).decode())
    print('Private TLS key remains local and was not logged')


if __name__ == '__main__':
    main()
