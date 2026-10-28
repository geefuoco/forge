import concurrent.futures
import http.client
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
import unittest
import tempfile

spec = importlib.util.spec_from_file_location('gateway', Path(__file__).parents[1] / 'server.py')
g = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = g
spec.loader.exec_module(g)

class FakeWorker:
    def __init__(self, origin, config):
        self.closed = False
        self.calls = []
    def start(self, decks):
        pass
    def request(self, method, path, payload, seat):
        if self.closed:
            raise g.Failure(503, 'Match worker unavailable')
        self.calls.append((method, path, payload, seat))
        return dict(status='playing', matchId='engine-match', revision=1, players=[], stack=[], seat=seat)
    def close(self):
        self.closed = True

class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.gateway = g.Gateway(g.Config('http://localhost:8080', dev=True), 'secret', FakeWorker)
        self.server = g.Server(('127.0.0.1', 0), self.gateway)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.gateway.close()
        self.thread.join()
    def request(self, path, body=None, cookie=None, **overrides):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        headers = {'Host': 'localhost:8080', 'Origin': 'http://localhost:8080', 'Content-Type': 'application/json'}
        if cookie:
            headers['Cookie'] = cookie
        headers.update(overrides)
        raw = json.dumps(body) if body is not None else None
        conn.request('POST' if body is not None else 'GET', '/api/v1' + path, raw, headers)
        response = conn.getresponse()
        result = response.status, json.loads(response.read()), response.getheader('Set-Cookie')
        conn.close()
        return result
    def login(self):
        status, body, cookie = self.request('/session', {'accessKey': 'secret'})
        self.assertEqual(status, 200)
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Lax', cookie)
        return cookie.split(';')[0]
    def lobby(self, cookie):
        return self.request('/matches', {'humanDeck': {'name': 'A', 'main': []}, 'aiDeck': {'name': 'B', 'main': []}, 'mode': 'human'}, cookie)
    def test_boundary_and_reconnect(self):
        self.assertEqual(self.request('/session')[1]['authenticated'], False)
        self.assertEqual(self.request('/session', {'accessKey': 'secret'}, Origin='http://evil')[0], 403)
        self.assertEqual(self.request('/session', {'accessKey': 'secret'}, Host='evil')[0], 403)
        self.assertEqual(self.request('/session', {'accessKey': 'secret'}, **{'Content-Type': 'text/plain'})[0], 415)
        cookie = self.login()
        self.assertEqual(self.request('/session', cookie=cookie)[1]['canCreate'], True)
        self.assertEqual(self.lobby(cookie)[0], 200)
        self.assertEqual(self.lobby(cookie)[0], 409)
        self.assertEqual(self.request('/match', cookie=cookie)[1]['seat'], 0)
    def test_atomic_invite_guest_seat_and_rotation(self):
        owner = self.login()
        self.assertEqual(self.lobby(owner)[0], 200)
        first = self.request('/invites', {}, owner)[1]['inviteUrl'].split('=')[-1]
        token = self.request('/invites', {}, owner)[1]['inviteUrl'].split('=')[-1]
        self.assertEqual(self.request('/join', {'token': first})[0], 409)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.request('/join', {'token': token}), range(2)))
        self.assertEqual(sorted(r[0] for r in results), [200, 409])
        guest = next(r[2].split(';')[0] for r in results if r[0] == 200)
        self.assertFalse(self.request('/session', cookie=guest)[1]['canCreate'])
        self.assertEqual(self.lobby(guest)[0], 403)
        self.assertEqual(self.request('/match', cookie=guest)[1]['seat'], 1)
        self.assertEqual(self.request('/match', cookie=owner)[1]['seat'], 0)
        self.assertEqual(self.request('/action', {'seat': 0, 'action': 'concede'}, guest)[0], 200)
        worker = next(iter(self.gateway.matches.values())).worker
        self.assertEqual(worker.calls[-1][-1], 1)
        worker.close()
        self.assertEqual(self.request('/match', cookie=guest)[0], 503)
    def test_body_bound_and_secret_storage(self):
        self.assertEqual(self.request('/session', {'accessKey': 'x' * g.BODY_LIMIT})[0], 413)
        cookie = self.login()
        value = cookie.split('=')[1]
        self.assertNotIn(value, self.gateway.sessions)
        self.assertIn(g.digest(value), self.gateway.sessions)
        self.assertEqual(self.request('/logout', {}, cookie)[0], 200)
        self.assertFalse(self.request('/session', cookie=cookie)[1]['authenticated'])
    def test_isolation_expiry_and_replacement(self):
        first, second = self.login(), self.login()
        self.assertEqual(self.lobby(first)[0], 200)
        self.assertEqual(self.lobby(second)[0], 200)
        records = list(self.gateway.matches.values())
        self.assertNotEqual(records[0].id, records[1].id)
        self.assertEqual(self.request('/match', cookie=first)[1]['matchId'], records[0].id)
        self.assertEqual(self.request('/match', cookie=second)[1]['matchId'], records[1].id)
        self.assertEqual(self.lobby(self.login())[0], 503)
        records[0].state = 'failed'
        self.assertEqual(self.lobby(first)[0], 200)
        self.assertEqual(self.request('/match', cookie=second)[1]['matchId'], records[1].id)
        records[1].created = 0
        deadline = time.monotonic() + 3
        while records[1].id in self.gateway.matches and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertFalse(self.request('/session', cookie=second)[1]['hasMatch'])
        self.assertEqual(self.lobby(second)[0], 200)
    def test_static_paths_cannot_read_outside_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'public'
            root.mkdir()
            secret = Path(directory) / 'private.txt'
            secret.write_text('private fixture')
            (root / 'index.html').symlink_to(secret)
            self.gateway.config.static_root = root
            for path in ('/', '/../private.txt', '/%2e%2e/private.txt'):
                conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
                conn.request('GET', path, headers={'Host': 'localhost:8080'})
                response = conn.getresponse()
                self.assertEqual(response.status, 404)
                self.assertNotIn(b'private fixture', response.read())
                conn.close()

if __name__ == '__main__':
    unittest.main()
