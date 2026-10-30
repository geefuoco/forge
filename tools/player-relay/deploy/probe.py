#!/usr/bin/env python3
"""Check one disposable room through verified HTTPS. Never print capabilities."""
import argparse
import concurrent.futures
import http.client
import json
from pathlib import Path
import ssl
import subprocess
import sys
import time
from urllib.parse import urlsplit
import uuid


class Client:
    def __init__(self, origin, ca_file=None):
        self.origin = origin.rstrip('/')
        self.address = urlsplit(self.origin)
        if (self.address.scheme != 'https' or not self.address.hostname or
                self.address.username or self.address.password or self.address.query or
                self.address.fragment or self.address.path):
            raise ValueError('Expected an HTTPS origin')
        self.context = ssl.create_default_context(cafile=ca_file)

    def request(self, method, path, data=None, token=None, headers=None):
        connection = http.client.HTTPSConnection(self.address.hostname, self.address.port,
                                                  timeout=12, context=self.context)
        request_headers = {'Content-Type': 'application/json'}
        if token:
            request_headers['Authorization'] = 'Bearer ' + token
        request_headers.update(headers or {})
        try:
            connection.request(method, path, json.dumps(data).encode() if data is not None else None,
                               request_headers)
            response = connection.getresponse()
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError('Oversized response')
            body = json.loads(raw) if raw and response.getheader('Content-Type', '').startswith('application/json') else None
            return response.status, body
        finally:
            connection.close()


def verify(client):
    checks = []
    room = None
    def expect(status, response):
        if response[0] != status:
            raise ValueError('Unexpected HTTP status')
        return response[1]
    try:
        expect(200, client.request('GET', '/health'))
        checks.append('verified HTTPS health')
        room = expect(201, client.request('POST', '/relay/v1/rooms',
                                         dict(protocolVersion=1, buildId='deployment-probe')))
        base = '/relay/v1/rooms/' + room['roomId']
        assert room['inviteUrl'].startswith(client.origin + '/#room=')
        join = dict(protocolVersion=1, buildId='wrong', inviteToken=room['inviteToken'])
        expect(409, client.request('POST', base + '/join', join))
        join['buildId'] = 'deployment-probe'
        guest = expect(200, client.request('POST', base + '/join', join))['guestToken']
        expect(409, client.request('POST', base + '/join', join))
        expect(401, client.request('GET', base + '/snapshot', token=room['hostToken']))
        expect(401, client.request('POST', base + '/host', {}, guest))
        checks.append('build gate, one-use invite, role isolation')
        snapshot = dict(schemaVersion=1, status='playing', revision=1, seat=1,
                        matchId='probe-match', players=[], stack=[], prompt={'id': 'probe-prompt'})
        expect(200, client.request('POST', base + '/host', {'snapshot': snapshot}, room['hostToken']))
        assert expect(200, client.request('GET', base + '/snapshot', token=guest)) == snapshot
        action = dict(commandId=str(uuid.uuid4()), action=dict(kind='ok', matchId='probe-match',
                       revision=1, promptId='probe-prompt'))
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.request, 'POST', base + '/actions', action, guest)
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                delivery = expect(200, client.request('POST', base + '/host', {}, room['hostToken']))
                if delivery['commands']:
                    break
                time.sleep(.05)
            assert delivery['commands'] == [action]
            result = dict(commandId=action['commandId'], status=200, body={'accepted': True})
            expect(200, client.request('POST', base + '/host', {'results': [result]}, room['hostToken']))
            assert expect(200, pending.result()) == result['body']
        assert expect(200, client.request('POST', base + '/actions', action, guest)) == result['body']
        checks.append('snapshot, queued action, acknowledgement, retained result')
        expect(200, client.request('POST', base + '/close', {}, room['hostToken']))
        expect(410, client.request('GET', base + '/snapshot', token=guest))
        room = None
        checks.append('close revokes capabilities')
        return {'status': 'passed', 'scope': 'HTTPS relay protocol, no real Forge game', 'checks': checks}
    finally:
        if room:
            client.request('POST', '/relay/v1/rooms/' + room['roomId'] + '/close', {}, room['hostToken'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--ca-file')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        try:
            print(json.dumps(verify(Client(args.origin, args.ca_file))))
            return 0
        except Exception:
            print(json.dumps({'status': 'failed', 'error': 'HTTPS relay protocol check failed'}))
            return 1
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--worker', '--origin', args.origin]
    if args.ca_file:
        command += ['--ca-file', args.ca_file]
    try:
        result = subprocess.run(command, capture_output=True, timeout=45)
        report = json.loads(result.stdout)
        status = result.returncode
    except (subprocess.TimeoutExpired, ValueError):
        report, status = {'status': 'failed', 'error': 'Probe exceeded its deadline or returned invalid output'}, 1
    rendered = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end='')
    return status


if __name__ == '__main__':
    sys.exit(main())
