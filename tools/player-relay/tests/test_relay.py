import concurrent.futures
import http.client
import importlib.util
import json
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
import uuid


SPEC = importlib.util.spec_from_file_location('player_relay', Path(__file__).parents[1] / 'server.py')
relay = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = relay
SPEC.loader.exec_module(relay)


class RelayHTTPTest(unittest.TestCase):
    def setUp(self):
        self.registry = relay.Registry('http://127.0.0.1', action_timeout=.12)
        self.server = relay.RelayServer(('127.0.0.1', 0), self.registry, '127.0.0.1')
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)

    def tearDown(self):
        self.pool.shutdown()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, data=None, token=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        request_headers = {'Host': '127.0.0.1'}
        if data is not None:
            request_headers['Content-Type'] = 'application/json'
        if token:
            request_headers['Authorization'] = 'Bearer ' + token
        request_headers.update(headers or {})
        conn.request(method, path, body=json.dumps(data).encode() if data is not None else None, headers=request_headers)
        response = conn.getresponse()
        raw = response.read()
        result = response.status, json.loads(raw) if raw else None, dict(response.getheaders())
        conn.close()
        return result

    def create(self):
        status, body, _ = self.request('POST', '/relay/v1/rooms', {'protocolVersion': 1, 'buildId': 'test-release'})
        self.assertEqual(status, 201, body)
        self.room = body
        self.base = '/relay/v1/rooms/' + body['roomId']
        return body

    def join(self):
        status, body, _ = self.request('POST', self.base + '/join', dict(protocolVersion=1, buildId='test-release', inviteToken=self.room['inviteToken']))
        self.assertEqual(status, 200, body)
        self.guest = body['guestToken']

    def publish(self, revision=1, **changes):
        snapshot = dict(schemaVersion=1, seat=1, status='playing', revision=revision,
                        matchId='match-one', players=[{'id': 'p1', 'hand': ['guest-card']}], stack=[],
                        prompt={'id': 'prompt-one', 'kind': 'priority'})
        snapshot.update(changes)
        status, body, _ = self.request('POST', self.base + '/host', {'snapshot': snapshot, 'results': []}, self.room['hostToken'])
        self.assertEqual(status, 200, body)
        return snapshot

    def action(self, **changes):
        action = dict(matchId='match-one', revision=1, promptId='prompt-one', kind='ok')
        action.update(changes)
        return dict(commandId=str(uuid.uuid4()), action=action)

    def test_join_checks_versions_before_atomic_one_use_and_role_isolation(self):
        room = self.create()
        bad = dict(protocolVersion=1, buildId='wrong', inviteToken=room['inviteToken'])
        self.assertEqual(self.request('POST', self.base + '/join', bad)[0], 409)
        bad.update(buildId='test-release', protocolVersion=True)
        self.assertEqual(self.request('POST', self.base + '/join', bad)[0], 409)
        good = dict(protocolVersion=1, buildId='test-release', inviteToken=room['inviteToken'])
        futures = [self.pool.submit(self.request, 'POST', self.base + '/join', good) for _ in range(2)]
        responses = [future.result() for future in futures]
        self.assertEqual(sorted(r[0] for r in responses), [200, 409])
        self.guest = next(r[1]['guestToken'] for r in responses if r[0] == 200)
        self.assertNotEqual(self.guest, room['hostToken'])
        for token in (room['hostToken'], room['inviteToken'], None):
            self.assertEqual(self.request('GET', self.base + '/snapshot', token=token)[0], 401)
        for endpoint in ('host', 'close'):
            self.assertEqual(self.request('POST', self.base + '/' + endpoint, {}, self.guest)[0], 401)
        self.assertEqual(self.request('POST', self.base + '/actions', self.action(), room['hostToken'])[0], 401)
        self.assertEqual(self.request('GET', self.base + '/snapshot', token=self.guest)[1], relay.STARTING)
        stored = self.registry.rooms[room['roomId']]
        self.assertEqual(stored.host_digest, relay.digest(room['hostToken']))
        self.assertIsNone(stored.invite_digest)

    def test_pending_survives_timeout_and_repeated_delivery_ack_and_retry(self):
        self.create()
        self.join()
        self.publish()
        request = self.action()
        first = self.request('POST', self.base + '/actions', request, self.guest)
        self.assertEqual(first[0], 504)
        self.assertIn('unknown', first[1]['error'])
        for _ in range(2):
            status, body, _ = self.request('POST', self.base + '/host', {}, self.room['hostToken'])
            self.assertEqual(status, 200)
            self.assertEqual(body['commands'], [request])
        self.assertEqual(self.request('POST', self.base + '/actions', self.action(), self.guest)[0], 409)
        retry = self.pool.submit(self.request, 'POST', self.base + '/actions', request, self.guest)
        result = dict(commandId=request['commandId'], status=409, body={'error': 'Engine rejected stale handle'})
        self.assertEqual(self.request('POST', self.base + '/host', {'results': [result]}, self.room['hostToken'])[1]['commands'], [])
        self.assertEqual(retry.result()[:2], (409, result['body']))
        self.publish(2)
        self.assertEqual(self.request('POST', self.base + '/actions', request, self.guest)[:2], (409, result['body']))
        self.assertEqual(self.request('POST', self.base + '/host', {'results': [result]}, self.room['hostToken'])[0], 200)
        result['body'] = {'error': 'changed'}
        self.assertEqual(self.request('POST', self.base + '/host', {'results': [result]}, self.room['hostToken'])[0], 409)
        request['action']['kind'] = 'cancel'
        self.assertEqual(self.request('POST', self.base + '/actions', request, self.guest)[0], 409)

    def test_stale_revision_prompt_match_and_malformed_actions_never_enqueue(self):
        self.create()
        self.join()
        self.publish()
        for changes, expected in (({'revision': 0}, 409), ({'revision': True}, 400),
                                  ({'revision': '1'}, 400), ({'revision': 1.2}, 400),
                                  ({'revision': None}, 400), ({'matchId': 'other'}, 409),
                                  ({'promptId': 'old'}, 409), ({'kind': 'shell'}, 400),
                                  ({'kind': 'concede', 'revision': None}, 400)):
            with self.subTest(changes=changes):
                self.assertEqual(self.request('POST', self.base + '/actions', self.action(**changes), self.guest)[0], expected)
        body = self.request('POST', self.base + '/host', {}, self.room['hostToken'])[1]
        self.assertEqual(body['commands'], [])
        concede = self.action(kind='concede')
        del concede['action']['promptId']
        self.assertEqual(self.request('POST', self.base + '/actions', concede, self.guest)[0], 504)

    def test_snapshot_monotonicity_host_lease_reconnect_close_and_restart(self):
        self.create()
        self.join()
        snapshot = self.publish(3)
        for changes in ({'revision': 2}, {'matchId': 'replacement', 'revision': 4},
                        {'revision': 3, 'prompt': None}, {'seat': 0}, {'revision': True}):
            invalid = dict(snapshot, **changes)
            status = self.request('POST', self.base + '/host', {'snapshot': invalid}, self.room['hostToken'])[0]
            self.assertIn(status, (400, 409))
        stored = self.registry.rooms[self.room['roomId']]
        with self.registry.condition:
            stored.heartbeat -= 16
        self.assertEqual(self.request('GET', self.base + '/snapshot', token=self.guest)[0], 503)
        self.assertEqual(self.request('POST', self.base + '/actions', self.action(revision=3), self.guest)[0], 503)
        self.assertEqual(self.request('POST', self.base + '/host', {}, self.room['hostToken'])[0], 200)
        self.assertEqual(self.request('GET', self.base + '/snapshot', token=self.guest)[1], snapshot)
        self.assertEqual(self.request('POST', self.base + '/close', {}, self.room['hostToken'])[0], 200)
        self.assertEqual(self.request('GET', self.base + '/snapshot', token=self.guest)[0], 410)
        self.assertEqual(stored.host_digest, b'')
        self.assertIsNone(stored.guest_digest)
        self.server.registry = relay.Registry('http://127.0.0.1')
        self.assertEqual(self.request('GET', self.base + '/snapshot', token=self.guest)[0], 404)

    def test_expiry_and_resource_bounds(self):
        self.create()
        stored = self.registry.rooms[self.room['roomId']]
        with self.registry.condition:
            stored.created -= 601
        self.assertEqual(self.request('POST', self.base + '/join', dict(protocolVersion=1, buildId='test-release', inviteToken=self.room['inviteToken']))[0], 410)
        self.assertIsNone(stored.invite_digest)
        with self.registry.condition:
            stored.touched -= 1801
        self.assertEqual(self.request('GET', self.base + '/snapshot', token='no')[0], 404)
        self.registry.max_rooms = 1
        self.create()
        self.assertEqual(self.request('POST', '/relay/v1/rooms', dict(protocolVersion=1, buildId='x'))[0], 503)
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        conn.request('POST', '/relay/v1/rooms', headers={'Host': '127.0.0.1', 'Content-Type': 'application/json', 'Content-Length': str(relay.MAX_BODY + 1)})
        response = conn.getresponse()
        self.assertEqual(response.status, 413)
        response.read()
        conn.close()

    def test_http_boundaries_and_health(self):
        status, body, headers = self.request('GET', '/health')
        self.assertEqual((status, body), (200, {'schemaVersion': 1, 'status': 'ready'}))
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        for headers in ({'Host': 'evil.example'}, {'Origin': 'https://evil.example'}, {'Origin': 'null'}):
            self.assertEqual(self.request('GET', '/health', headers=headers)[0], 403)
        self.assertEqual(self.request('GET', '/health?token=secret')[0], 400)
        self.assertEqual(self.request('OPTIONS', '/health')[0], 405)
        self.assertEqual(self.request('POST', '/relay/v1/rooms', {}, headers={'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(relay.origin_value('https://relay.example/', False), 'https://relay.example')
        for origin, dev in (('http://relay.example', False), ('http://relay.example', True),
                            ('https://u:p@relay.example', False), ('https://relay.example/path', False)):
            with self.assertRaises(ValueError):
                relay.origin_value(origin, dev)

    def test_json_boundary_creation_and_request_rate_bounds(self):
        for raw in (b'{"protocolVersion":1,"protocolVersion":1,"buildId":"x"}',
                    b'{"protocolVersion":1,"buildId":NaN}', b'[]', b'{'):
            conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
            conn.request('POST', '/relay/v1/rooms', raw,
                         {'Host': '127.0.0.1', 'Content-Type': 'application/json'})
            response = conn.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
            conn.close()
        self.create()
        for _ in range(3):
            self.create()
        self.assertEqual(self.request('POST', '/relay/v1/rooms', dict(protocolVersion=1, buildId='test-release'))[0], 429)
        for _ in range(6):
            self.request('POST', '/relay/v1/rooms', dict(protocolVersion=1, buildId='test-release'))
        self.assertEqual(self.request('POST', '/relay/v1/rooms', dict(protocolVersion=1, buildId='test-release'))[0], 429)
        self.join()
        responses = [self.request('GET', self.base + '/snapshot', token=self.guest)[0] for _ in range(61)]
        self.assertIn(429, responses)

    def test_worker_capacity_rejects_connection_without_creating_a_thread(self):
        limited = relay.RelayServer(('127.0.0.1', 0), relay.Registry('http://127.0.0.1'), '127.0.0.1', max_threads=1)
        worker = threading.Thread(target=limited.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        worker.start()
        first = socket.create_connection(('127.0.0.1', limited.server_port), timeout=3)
        try:
            first.sendall(b'GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n')
            time.sleep(.03)
            second = http.client.HTTPConnection('127.0.0.1', limited.server_port, timeout=3)
            second.request('GET', '/health', headers={'Host': '127.0.0.1'})
            response = second.getresponse()
            self.assertEqual(response.status, 503)
            self.assertEqual(response.getheader('Cache-Control'), 'no-store')
            response.read()
            second.close()
        finally:
            first.close()
            limited.shutdown()
            limited.server_close()
            worker.join()

    def test_unknown_host_ack_is_atomic_and_evicted_result_cannot_reapply(self):
        self.create()
        self.join()
        snapshot = self.publish()
        request = self.action()
        self.request('POST', self.base + '/actions', request, self.guest)
        result = dict(commandId=request['commandId'], status=200, body={'ok': True})
        unknown = dict(commandId=str(uuid.uuid4()), status=200, body={})
        response = self.request('POST', self.base + '/host', {'results': [result, unknown], 'snapshot': dict(snapshot, revision=2)}, self.room['hostToken'])
        self.assertEqual(response[0], 409)
        self.assertEqual(self.request('GET', self.base + '/snapshot', token=self.guest)[1]['revision'], 1)
        self.assertEqual(self.request('POST', self.base + '/host', {'results': [result]}, self.room['hostToken'])[0], 200)
        with self.registry.condition:
            self.registry.rooms[self.room['roomId']].results.clear()
        self.assertEqual(self.request('POST', self.base + '/actions', request, self.guest)[0], 409)


if __name__ == '__main__':
    unittest.main()
