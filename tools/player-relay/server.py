#!/usr/bin/env python3
"""Memory-only capability relay. The installed host owns the game engine."""

import argparse
from collections import OrderedDict, deque
from dataclasses import dataclass, field
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import json
import math
import re
import secrets
import socket
from socketserver import ThreadingMixIn
import threading
import time
from urllib.parse import urlsplit
import uuid


MAX_BODY = 1024 * 1024
MAX_ACTION = 16 * 1024
MAX_RESULT = 64 * 1024
MAX_RESULTS = 128
MAX_COMMANDS = 8192
KINDS = frozenset(('ok', 'cancel', 'card', 'player', 'choice', 'number',
                   'concede', 'input', 'manipulate', 'allocation', 'skip'))
STARTING = dict(schemaVersion=1, status='starting', revision=0, players=[], stack=[], seat=1)


class Failure(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def encoded(value):
    return json.dumps(value, separators=(',', ':'), sort_keys=True, allow_nan=False).encode()


def digest(token):
    return hashlib.sha256(token.encode()).digest()


def whole(value):
    return type(value) in (int, float) and math.isfinite(value) and value == int(value) and 0 <= value <= 2**63 - 1


@dataclass
class Command:
    command_id: str
    action: dict
    payload: bytes
    status: int = 0
    body: object = None


@dataclass
class Room:
    room_id: str
    build_id: str
    owner_ip: str
    created: float
    touched: float
    heartbeat: float
    host_digest: bytes
    invite_digest: bytes | None
    guest_digest: bytes | None = None
    snapshot: dict = field(default_factory=lambda: dict(STARTING))
    match_id: str | None = None
    pending: Command | None = None
    results: OrderedDict = field(default_factory=OrderedDict)
    seen: set = field(default_factory=set)
    closed: bool = False
    requests: deque = field(default_factory=deque)


class Registry:
    def __init__(self, origin, max_rooms=64, offline_seconds=15, action_timeout=8,
                 idle_seconds=1800, lifetime_seconds=14400, invite_seconds=600):
        self.origin = origin
        self.max_rooms = max_rooms
        self.offline_seconds, self.action_timeout = offline_seconds, action_timeout
        self.idle_seconds, self.lifetime_seconds = idle_seconds, lifetime_seconds
        self.invite_seconds = invite_seconds
        self.rooms = {}
        self.closed_rooms = OrderedDict()
        self.creations = OrderedDict()
        self.condition = threading.Condition()

    def cleanup(self, now):
        for key, closed in list(self.closed_rooms.items()):
            if now - closed > self.idle_seconds:
                del self.closed_rooms[key]
        for key, room in list(self.rooms.items()):
            if now - room.touched > self.idle_seconds or now - room.created > self.lifetime_seconds:
                self.retire(room)
                del self.rooms[key]
        for ip, attempts in list(self.creations.items()):
            while attempts and now - attempts[0] >= 60:
                attempts.popleft()
            if not attempts:
                del self.creations[ip]

    def retire(self, room):
        room.closed = True
        room.host_digest = b''
        room.guest_digest = room.invite_digest = None
        room.snapshot = dict(STARTING)
        room.pending = None
        room.results.clear()
        room.seen.clear()
        self.condition.notify_all()

    def create(self, data, ip, now):
        self.compatible(data)
        build = data.get('buildId')
        attempts = self.creations.get(ip)
        if attempts is None:
            if len(self.creations) >= 1024:
                raise Failure(429, 'Room creation rate exceeded')
            attempts = self.creations[ip] = deque()
        if len(attempts) >= 10:
            raise Failure(429, 'Room creation rate exceeded')
        attempts.append(now)
        if len(self.rooms) >= self.max_rooms:
            raise Failure(503, 'Relay room capacity reached')
        if sum(r.owner_ip == ip and not r.closed for r in self.rooms.values()) >= 4:
            raise Failure(429, 'Room limit reached')
        room_id = secrets.token_hex(16)
        host, invite = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.rooms[room_id] = Room(room_id, build, ip, now, now, now, digest(host), digest(invite))
        return 201, dict(schemaVersion=1, roomId=room_id, hostToken=host, inviteToken=invite,
                         inviteUrl=f'{self.origin}/#room={room_id}&invite={invite}')

    def compatible(self, data, room=None):
        if type(data.get('protocolVersion')) is not int or data['protocolVersion'] != 1:
            raise Failure(409, 'Protocol version mismatch')
        build = data.get('buildId')
        if not isinstance(build, str) or not build.strip() or len(build) > 128:
            raise Failure(400, 'Invalid buildId')
        if room and build != room.build_id:
            raise Failure(409, 'Build version mismatch')

    def authenticate(self, room, token, role):
        expected = room.host_digest if role == 'host' else room.guest_digest
        if not token or not expected or not secrets.compare_digest(expected, digest(token)):
            raise Failure(401, 'Invalid capability')

    def online(self, room, now):
        if now - room.heartbeat > self.offline_seconds:
            raise Failure(503, 'Host disconnected')

    def snapshot_update(self, room, snapshot):
        if not isinstance(snapshot, dict) or type(snapshot.get('schemaVersion')) is not int or snapshot['schemaVersion'] != 1:
            raise Failure(400, 'Invalid snapshot schema')
        if type(snapshot.get('seat')) is not int or snapshot['seat'] != 1 or not whole(snapshot.get('revision')):
            raise Failure(400, 'Invalid snapshot seat or revision')
        if snapshot.get('status') not in ('starting', 'playing', 'finished', 'error'):
            raise Failure(400, 'Invalid snapshot status')
        match_id = snapshot.get('matchId')
        if match_id is None and snapshot['status'] != 'starting':
            raise Failure(400, 'Snapshot requires matchId')
        if match_id is not None and (not isinstance(match_id, str) or not match_id or len(match_id) > 128):
            raise Failure(400, 'Invalid snapshot matchId')
        if room.match_id and match_id != room.match_id:
            raise Failure(409, 'Cannot replace room match')
        previous = room.snapshot
        if snapshot['revision'] < previous['revision']:
            raise Failure(409, 'Stale snapshot revision')
        if snapshot['revision'] == previous['revision'] and snapshot != previous:
            raise Failure(409, 'Conflicting snapshot revision')
        return match_id

    def host(self, room, data, now):
        results = data.get('results', [])
        if not isinstance(results, list) or len(results) > MAX_RESULTS:
            raise Failure(400, 'Invalid results')
        updates = []
        acknowledged = set()
        for result in results:
            if not isinstance(result, dict):
                raise Failure(400, 'Invalid result')
            command_id = result.get('commandId')
            if not isinstance(command_id, str) or command_id in acknowledged:
                raise Failure(400, 'Invalid result commandId')
            acknowledged.add(command_id)
            command = room.results.get(command_id)
            if command is None and room.pending and room.pending.command_id == command_id:
                command = room.pending
            if command is None:
                raise Failure(409, 'Unknown result commandId')
            status = result.get('status')
            if type(status) is not int or not 200 <= status <= 599 or 'body' not in result:
                raise Failure(400, 'Invalid result status or body')
            if len(encoded(result['body'])) > MAX_RESULT:
                raise Failure(413, 'Result too large')
            if command.status and (command.status != status or encoded(command.body) != encoded(result['body'])):
                raise Failure(409, 'Conflicting result')
            updates.append((command, status, result['body']))
        match_id = room.match_id
        if 'snapshot' in data:
            match_id = self.snapshot_update(room, data['snapshot'])
        if 'snapshot' in data:
            room.snapshot, room.match_id = data['snapshot'], match_id
        for command, status, body in updates:
            command.status, command.body = status, body
            room.results[command.command_id] = command
            if room.pending is command:
                room.pending = None
            while len(room.results) > MAX_RESULTS:
                room.results.popitem(last=False)
        room.heartbeat = now
        self.condition.notify_all()
        commands = [] if room.pending is None else [dict(commandId=room.pending.command_id, action=room.pending.action)]
        return 200, dict(schemaVersion=1, guestJoined=room.guest_digest is not None, commands=commands)

    def action(self, room, data, now):
        command_id, action = data.get('commandId'), data.get('action')
        try:
            if str(uuid.UUID(command_id)) != command_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise Failure(400, 'commandId must be a canonical UUID') from None
        if not isinstance(action, dict) or action.get('kind') not in KINDS:
            raise Failure(400, 'Unknown action kind')
        payload = encoded(action)
        if len(payload) > MAX_ACTION:
            raise Failure(413, 'Action too large')
        command = room.results.get(command_id)
        if command is None and room.pending and room.pending.command_id == command_id:
            command = room.pending
        if command:
            if payload != command.payload:
                raise Failure(409, 'commandId payload mismatch')
        else:
            if command_id in room.seen:
                raise Failure(409, 'Action result expired; refresh the game')
            self.online(room, now)
            if not whole(action.get('revision')):
                raise Failure(400, 'Revision must be a whole number within range')
            snapshot = room.snapshot
            if not room.match_id or action.get('matchId') != room.match_id or action['revision'] != snapshot['revision']:
                raise Failure(409, 'Stale match or revision')
            prompt = snapshot.get('prompt')
            expected_prompt = prompt.get('id') if isinstance(prompt, dict) else None
            if action['kind'] != 'concede' and (not expected_prompt or action.get('promptId') != expected_prompt):
                raise Failure(409, 'Stale prompt')
            if action['kind'] == 'concede' and 'promptId' in action and action['promptId'] != expected_prompt:
                raise Failure(409, 'Stale prompt')
            if snapshot.get('status') != 'playing':
                raise Failure(409, 'Match is not playing')
            if room.pending:
                raise Failure(409, 'An action is already pending')
            if len(room.seen) >= MAX_COMMANDS:
                raise Failure(503, 'Room command capacity reached')
            command = Command(command_id, action, payload)
            room.pending = command
            room.seen.add(command_id)
        deadline = time.monotonic() + self.action_timeout
        while not command.status:
            if room.closed:
                raise Failure(410, 'Room closed')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Failure(504, 'Action status unknown; refresh the game before retrying')
            self.condition.wait(min(remaining, 1))
        return command.status, command.body

    def dispatch(self, method, path, data, token, ip):
        with self.condition:
            now = time.monotonic()
            self.cleanup(now)
            if method == 'GET' and path == '/health':
                return 200, dict(schemaVersion=1, status='ready')
            if method == 'POST' and path == '/relay/v1/rooms':
                return self.create(data, ip, now)
            match = re.fullmatch(r'/relay/v1/rooms/([a-f0-9]{32})/(join|host|snapshot|actions|close)', path)
            if not match:
                raise Failure(404, 'Not found')
            room_id, endpoint = match.groups()
            room = self.rooms.get(room_id)
            if room is None:
                if room_id in self.closed_rooms:
                    raise Failure(410, 'Room closed')
                raise Failure(404, 'Unknown room')
            if room.closed:
                raise Failure(410, 'Room closed')
            if method != ('GET' if endpoint == 'snapshot' else 'POST'):
                raise Failure(405, 'Method not allowed')
            if endpoint == 'join':
                self.compatible(data, room)
                if room.guest_digest:
                    raise Failure(409, 'Guest already joined')
                if now - room.created > self.invite_seconds:
                    room.invite_digest = None
                    raise Failure(410, 'Invite expired')
                invite = data.get('inviteToken')
                if not isinstance(invite, str) or not room.invite_digest or not secrets.compare_digest(room.invite_digest, digest(invite)):
                    raise Failure(401, 'Invalid invite')
                guest = secrets.token_urlsafe(32)
                room.guest_digest, room.invite_digest = digest(guest), None
                room.touched = now
                return 200, dict(schemaVersion=1, roomId=room_id, guestToken=guest)
            self.authenticate(room, token, 'host' if endpoint in ('host', 'close') else 'guest')
            while room.requests and now - room.requests[0] > 1:
                room.requests.popleft()
            if len(room.requests) >= 60:
                raise Failure(429, 'Room request rate exceeded')
            room.requests.append(now)
            room.touched = now
            if endpoint == 'host':
                return self.host(room, data, now)
            if endpoint == 'close':
                self.retire(room)
                del self.rooms[room_id]
                self.closed_rooms[room_id] = now
                while len(self.closed_rooms) > self.max_rooms * 2:
                    self.closed_rooms.popitem(last=False)
                return 200, dict(schemaVersion=1, status='closed')
            if endpoint == 'snapshot':
                self.online(room, now)
                return 200, room.snapshot
            return self.action(room, data, now)


class RelayServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, address, registry, authority, max_threads=32):
        self.registry, self.authority = registry, authority
        self.slots = threading.BoundedSemaphore(max_threads)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\nCache-Control: no-store\r\n\r\n')
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        pass


class Handler(BaseHTTPRequestHandler):
    server_version = 'NeoForgeRelay'
    sys_version = ''
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self.handle_api()

    def do_POST(self):
        self.handle_api()

    def do_OPTIONS(self):
        self.respond(405, dict(error='Method not allowed'))

    def send_error(self, code, message=None, explain=None):
        self.respond(code, dict(error='Invalid HTTP request'))

    def handle_api(self):
        try:
            if len(self.headers.get_all('Host', [])) != 1 or self.headers['Host'] != self.server.authority:
                raise Failure(403, 'Invalid Host')
            origins = self.headers.get_all('Origin', [])
            if origins and (len(origins) != 1 or origins[0] != self.server.registry.origin):
                raise Failure(403, 'Invalid Origin')
            if '?' in self.path or '#' in self.path:
                raise Failure(400, 'Query strings are not accepted')
            if self.headers.get('Transfer-Encoding'):
                raise Failure(400, 'Transfer encoding is not accepted')
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) > 1:
                raise Failure(400, 'Invalid Content-Length')
            length = int(lengths[0]) if lengths else 0
            if length < 0 or length > MAX_BODY:
                raise Failure(413, 'Request body too large')
            data = {}
            if self.command == 'POST':
                if self.headers.get_content_type() != 'application/json':
                    raise Failure(415, 'Expected application/json')
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise Failure(400, 'Incomplete body')
                def unique(pairs):
                    result = {}
                    for key, value in pairs:
                        if key in result:
                            raise ValueError('Duplicate JSON key')
                        result[key] = value
                    return result
                data = json.loads(raw, object_pairs_hook=unique,
                                  parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
                if not isinstance(data, dict):
                    raise Failure(400, 'Expected JSON object')
            elif length:
                raise Failure(400, 'GET body is not accepted')
            authorization = self.headers.get_all('Authorization', [])
            if len(authorization) > 1:
                raise Failure(401, 'Invalid capability')
            auth = authorization[0] if authorization else ''
            token = auth[7:] if auth.startswith('Bearer ') and len(auth) <= 128 else ''
            status, body = self.server.registry.dispatch(self.command, self.path, data, token, self.client_address[0])
            self.respond(status, body)
        except Failure as error:
            self.respond(error.status, dict(error=error.message))
        except (ValueError, TypeError, RecursionError, UnicodeError, OverflowError):
            self.respond(400, dict(error='Invalid request JSON or length'))
        except (OSError, socket.timeout):
            self.close_connection = True

    def respond(self, status, body):
        payload = encoded(body)
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(payload)
        except OSError:
            pass


def origin_value(value, dev):
    parsed = urlsplit(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/') or not parsed.hostname:
        raise ValueError('origin must contain only scheme and authority')
    parsed.port
    if dev:
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = parsed.hostname == 'localhost'
        if parsed.scheme != 'http' or not loopback:
            raise ValueError('--dev requires a loopback HTTP origin')
    elif parsed.scheme != 'https':
        raise ValueError('--origin requires HTTPS unless --dev is set')
    return f'{parsed.scheme}://{parsed.netloc}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--dev', action='store_true')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--max-rooms', type=int, default=64)
    parser.add_argument('--max-threads', type=int, default=32)
    args = parser.parse_args()
    try:
        origin = origin_value(args.origin, args.dev)
    except ValueError as error:
        parser.error(str(error))
    if not 1 <= args.max_rooms <= 1024 or not 1 <= args.max_threads <= 128:
        parser.error('room/thread bounds must be positive and at most 1024/128')
    server = RelayServer((args.host, args.port), Registry(origin, args.max_rooms), urlsplit(origin).netloc, args.max_threads)
    print(f'NeoForge relay listening on {args.host}:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
