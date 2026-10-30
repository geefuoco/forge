"""Exercise real Forge workers through browser-facing hosted HTTP sessions."""
import argparse
import http.client
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('hosted_gateway', ROOT / 'tools/hosted-engine/server.py')
gateway_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gateway_module
spec.loader.exec_module(gateway_module)


class Client:
    def __init__(self, port):
        self.port, self.cookie = port, None

    def call(self, path, body=None, expected=200):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        headers = {'Origin': f'http://127.0.0.1:{self.port}', 'Content-Type': 'application/json'}
        if self.cookie:
            headers['Cookie'] = self.cookie
        connection.request('POST' if body is not None else 'GET', '/api/v1/' + path,
                           None if body is None else json.dumps(body), headers)
        response = connection.getresponse()
        data = json.loads(response.read())
        cookie = response.getheader('Set-Cookie')
        if cookie:
            self.cookie = cookie.split(';', 1)[0]
        status = response.status
        connection.close()
        assert status == expected, (path, status, data)
        return data


def wait_for(client, predicate, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        snapshot = client.call('match')
        assert snapshot.get('status') != 'error', snapshot.get('error')
        if predicate(snapshot):
            return snapshot
        time.sleep(.1)
    raise TimeoutError('Forge did not reach the expected state')


def private_view(snapshot):
    if not snapshot.get('players'):
        return
    own = snapshot['viewerPlayerId']
    assert sum('hand' in p for p in snapshot['players']) == 1
    assert next(p for p in snapshot['players'] if 'hand' in p)['id'] == own
    assert all('library' not in p for p in snapshot['players'])


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    key = os.urandom(32).hex()
    gateway = gateway_module.Gateway(gateway_module.Config('http://127.0.0.1:8080', dev=True), key)
    server = gateway_module.Server(('127.0.0.1', 0), gateway)
    gateway.config.origin = f'http://127.0.0.1:{server.server_port}'
    gateway.authority = f'127.0.0.1:{server.server_port}'
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    decks = json.loads((ROOT / 'web/neoforge/dist/data/precons.json').read_text())
    checks = []
    samples = []
    try:
        owner, guest, stranger = [Client(server.server_port) for _ in range(3)]
        owner.call('session', {'accessKey': key})
        request = {'humanDeck': decks[0], 'aiDeck': decks[1], 'mode': 'human'}
        owner.call('matches', request)
        assert not gateway.matches[next(iter(gateway.matches))].worker
        token = owner.call('invites', {})['inviteUrl'].split('=', 1)[1]
        guest.call('join', {'token': token})
        stranger.call('join', {'token': token}, 409)
        stranger.call('action', {'kind': 'concede'}, 403)
        first = wait_for(owner, lambda s: s.get('status') == 'playing' and s.get('players'))
        second = wait_for(guest, lambda s: s.get('status') == 'playing' and s.get('players'))
        deadline = time.monotonic() + 20
        while not first.get('prompt') and not second.get('prompt'):
            assert time.monotonic() < deadline, 'Neither human received a prompt'
            time.sleep(.1)
            first, second = owner.call('match'), guest.call('match')
        assert first['matchId'] == second['matchId']
        assert first['viewerPlayerId'] != second['viewerPlayerId']
        private_view(first)
        private_view(second)
        checks += ['real two-human engine setup', 'private hands per viewer', 'single-use invitation', 'stranger cannot act']
        reconnect = Client(server.server_port)
        reconnect.cookie = guest.cookie
        assert reconnect.call('session')['seat'] == 1
        assert reconnect.call('match')['matchId'] == second['matchId']
        checks.append('cookie reconnect retains guest seat')
        active = first if first.get('prompt') else second
        inactive = guest if first.get('prompt') else owner
        inactive.call('action', {'matchId': active['matchId'], 'revision': active['revision'],
                                'promptId': active['prompt']['id'], 'kind': 'ok'}, 409)
        checks.append('cross-seat prompt rejected')
        other = Client(server.server_port)
        other.call('session', {'accessKey': key})
        other.call('matches', dict(request, mode='cpu'))
        third = wait_for(other, lambda s: s.get('status') == 'playing' and s.get('players'))
        private_view(third)
        workers = [r.worker for r in gateway.matches.values()]
        assert workers[0].process.pid != workers[1].process.pid
        assert workers[0].profile.name != workers[1].profile.name
        for worker in workers:
            status = Path(f'/proc/{worker.process.pid}/status').read_text()
            fields = {line.split(':', 1)[0]: line.split(':', 1)[1].strip() for line in status.splitlines() if ':' in line}
            samples.append({'rss': fields['VmRSS'], 'peakRSS': fields['VmHWM'], 'threads': fields['Threads']})
        checks.append('concurrent games have distinct JVMs and profiles')
        snapshot = inactive.call('match')
        inactive.call('action', {'matchId': snapshot['matchId'], 'revision': snapshot['revision'],
                                 'kind': 'concede'})
        for client in (owner, guest):
            terminal = wait_for(client, lambda s: s.get('status') == 'finished', 20)
            assert terminal.get('result'), terminal
            assert any(p.get('lossReason') == 'Conceded' for p in terminal['result']['participants'])
        checks.append('off-turn concession completes both seat projections')
        workers[0].close()
        owner.call('match', expected=503)
        surviving = other.call('match')
        assert surviving['matchId'] == third['matchId'] and surviving['status'] == 'playing'
        checks.append('worker termination does not stop other match')
        result = {'scope': 'local real-engine HTTP, not public deployment',
                  'sourceRevision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  'checks': checks, 'resourceSamples': samples,
                  'resourceLimit': 'one sampling point per JVM, not capacity or performance proof'}
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result), flush=True)
    finally:
        server.shutdown()
        server.server_close()
        gateway.close()
        thread.join()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
