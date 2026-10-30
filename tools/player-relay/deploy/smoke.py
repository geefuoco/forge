#!/usr/bin/env python3
"""Exercise the production Compose bundle with a temporary local TLS certificate."""
import argparse
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import uuid

from probe import Client


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    project = 'relay-smoke-' + uuid.uuid4().hex[:10]
    with tempfile.TemporaryDirectory(prefix=project + '-') as temporary:
        work = Path(temporary)
        work.chmod(0o755)
        def run(command, **kwargs):
            result = subprocess.run(command, capture_output=True, timeout=120, **kwargs)
            if result.returncode:
                Path('/tmp/relay-compose-failure.log').write_bytes(result.stderr)
                result.check_returncode()
            return result
        run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
             '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost',
             '-keyout', str(work / 'key.pem'), '-out', str(work / 'cert.pem')])
        (work / 'key.pem').chmod(0o644)
        (work / 'cert.pem').chmod(0o644)
        configuration = (ROOT / 'Caddyfile').read_text()
        configuration = configuration.replace('admin off', 'admin off\n\tauto_https off')
        configuration = configuration.replace('https://{$RELAY_DOMAIN} {',
            'https://{$RELAY_DOMAIN} {\n\ttls /test/cert.pem /test/key.pem')
        configuration = configuration.replace('https:// {', 'https:// {\n\ttls /test/cert.pem /test/key.pem')
        (work / 'Caddyfile').write_text(configuration)
        (work / 'Caddyfile').chmod(0o644)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        override = {'services': {'caddy': {
            'ports': ['127.0.0.1:' + str(port) + ':443'],
            'volumes': [str(work / 'Caddyfile') + ':/etc/caddy/Caddyfile:ro', str(work) + ':/test:ro']},
            'relay': {'command': ['--origin', 'https://localhost:' + str(port),
                                 '--trusted-proxy-peer', '172.30.92.2']}}}
        # Compose replaces the published ports rather than exposing production listeners.
        import_text = json.dumps(override)
        override_path = work / 'override.yaml'
        import_text = import_text.replace('"ports": [', '"ports": !override [')
        override_path.write_text(import_text)
        environment = dict(os.environ, RELAY_DOMAIN='localhost')
        compose = ['docker', 'compose', '-p', project, '-f', str(ROOT / 'compose.yaml'), '-f', str(override_path)]
        def dc(*arguments):
            return run(compose + list(arguments), env=environment)
        checks = []
        try:
            dc('up', '-d', '--build')
            origin = 'https://localhost:' + str(port)
            client = Client(origin, str(work / 'cert.pem'))
            deadline = time.monotonic() + 30
            while True:
                try:
                    status = client.request('GET', '/health')[0]
                    assert status == 200, 'health status ' + str(status)
                    break
                except (OSError, AssertionError):
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.2)
            checks.append('production services accept verified local HTTPS')
            print(checks[-1], file=sys.stderr, flush=True)
            for unsafe in (Client(origin), Client('https://127.0.0.1:' + str(port), str(work / 'cert.pem'))):
                try:
                    unsafe.request('GET', '/health')
                    raise AssertionError('Untrusted TLS unexpectedly succeeded')
                except ssl.SSLCertVerificationError:
                    pass
            checks.append('unknown CA and wrong certificate hostname rejected')
            print(checks[-1], file=sys.stderr, flush=True)
            assert client.request('GET', '/health', headers={'Host': 'localhost'})[0] == 403
            assert client.request('GET', '/health', headers={'Origin': 'https://wrong.example'})[0] == 403
            assert client.request('GET', '/health', headers={'Host': 'wrong.example'})[0] == 403
            checks.append('raw Host authority and Origin preserved and rejected')
            print(checks[-1], file=sys.stderr, flush=True)
            probe = run([sys.executable, '-B', str(ROOT / 'probe.py'), '--origin', origin,
                         '--ca-file', str(work / 'cert.pem')])
            assert json.loads(probe.stdout)['status'] == 'passed'
            checks.append('external protocol probe passed through TLS proxy')
            print(checks[-1], file=sys.stderr, flush=True)
            created = []
            data = dict(protocolVersion=1, buildId='smoke')
            for i in range(4):
                status, room = client.request('POST', '/relay/v1/rooms', data,
                    headers={'X-Relay-Client-IP': '192.0.2.' + str(i)})
                assert status == 201
                created.append(room)
            assert client.request('POST', '/relay/v1/rooms', data,
                   headers={'X-Relay-Client-IP': '203.0.113.1'})[0] == 429
            checks.append('proxy overwrites forged client identity and enforces one-IP room cap')
            print(checks[-1], file=sys.stderr, flush=True)
            room = created[0]
            base = '/relay/v1/rooms/' + room['roomId']
            status, guest = client.request('POST', base + '/join',
                dict(data, inviteToken=room['inviteToken']))
            assert status == 200
            guest = guest['guestToken']
            snapshot = dict(schemaVersion=1, status='playing', revision=1, seat=1,
                            matchId='smoke', players=[], stack=[], prompt={'id': 'smoke'})
            assert client.request('POST', base + '/host', {'snapshot': snapshot}, room['hostToken'])[0] == 200
            action = dict(commandId=str(uuid.uuid4()), action=dict(kind='ok', matchId='smoke', revision=1, promptId='smoke'))
            started = time.monotonic()
            assert client.request('POST', base + '/actions', action, guest)[0] == 504
            assert time.monotonic() - started >= 7
            assert client.request('POST', base + '/host', {}, room['hostToken'])[1]['commands'] == [action]
            checks.append('eight-second action timeout reaches client and retains pending command')
            print(checks[-1], file=sys.stderr, flush=True)
            backend = dc('ps', '-q', 'relay').stdout.decode().strip()
            inspect = json.loads(run(['docker', 'inspect', backend]).stdout)[0]
            assert not inspect['NetworkSettings']['Ports'].get('8080/tcp')
            assert len(inspect['NetworkSettings']['Networks']) == 1
            checks.append('backend has no published port and only the private network')
            print(checks[-1], file=sys.stderr, flush=True)
            canary = 'secret-canary-' + uuid.uuid4().hex
            snapshot['revision'] = 2
            snapshot['probeCanary'] = canary
            assert client.request('POST', base + '/host', {'snapshot': snapshot}, room['hostToken'])[0] == 200
            assert client.request('POST', '/unknown?' + canary, {'canary': canary}, canary)[0] == 400
            dc('stop', 'relay')
            assert client.request('POST', '/unknown?' + canary, {'canary': canary}, canary)[0] == 502
            logs = dc('logs', '--no-color').stdout
            for secret in (canary, room['hostToken'], room['inviteToken'], guest):
                assert secret.encode() not in logs
            checks.append('success and upstream-failure logs omit query, body, and capability canaries')
            print(checks[-1], file=sys.stderr, flush=True)
            dc('start', 'relay')
            deadline = time.monotonic() + 10
            while True:
                status = client.request('GET', base + '/snapshot', token=guest)[0]
                if status == 404:
                    break
                assert time.monotonic() < deadline, 'restart revocation status ' + str(status)
                time.sleep(.2)
            dc('restart', 'caddy')
            deadline = time.monotonic() + 10
            while True:
                try:
                    assert client.request('GET', '/health')[0] == 200
                    break
                except (OSError, AssertionError):
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.2)
            checks.append('relay restart revokes rooms and proxy restarts with supplied local certificate')
            print(checks[-1], file=sys.stderr, flush=True)
            report = {'status': 'passed', 'scope': 'local Compose HTTPS, no public DNS or real Forge game', 'checks': checks}
            rendered = json.dumps(report, indent=2) + '\n'
            if args.output:
                args.output.write_text(rendered)
            print(rendered, end='')
        except Exception:
            print('Completed checks: ' + ', '.join(checks), file=sys.stderr)
            Path('/tmp/relay-compose-services.log').write_bytes(dc('logs', '--no-color').stdout)
            raise
        finally:
            dc('down', '--volumes', '--remove-orphans')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Compose HTTPS smoke failed (' + type(error).__name__ + ').', file=sys.stderr)
        sys.exit(1)
