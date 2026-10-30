#!/usr/bin/env python3
"""Bounded same-origin gateway for isolated Forge match workers."""
import argparse
from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import shlex
import signal
import socketserver
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit, unquote
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
COOKIE = 'neoforge_session'
BODY_LIMIT = 1024 * 1024

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

class Failure(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message

@dataclass
class Session:
    digest: str
    expiry: float
    can_create: bool = False
    match_id: str | None = None
    seat: int | None = None

@dataclass
class Invite:
    digest: str
    match_id: str
    expiry: float

@dataclass
class MatchRecord:
    id: str
    mode: str
    decks: dict
    created: float
    last_activity: float
    state: str = 'waiting'
    seats: dict = field(default_factory=dict)
    worker: object = None
    invite_digest: str | None = None

class Worker:
    def __init__(self, origin, config):
        self.origin, self.config = origin, config
        self.token = secrets.token_urlsafe(32)
        self.process = None
        self.port = None
        self.profile = tempfile.TemporaryDirectory(prefix='neoforge-worker-')
        self.stopped = threading.Event()
        self.lifecycle_lock = threading.Lock()
        self.opener = build_opener(ProxyHandler({}))

    def start(self, decks):
        desktop = ROOT / 'forge-gui-desktop'
        classes = os.environ.get('FORGE_BRIDGE_CLASSES', str(desktop / 'target/browser-bridge'))
        cp = os.environ.get('FORGE_BRIDGE_CLASSPATH')
        if not cp:
            cpfile = desktop / 'target/browser-bridge/classpath.txt'
            cp = str(desktop / 'target/classes') + os.pathsep + cpfile.read_text().strip()
        options = ET.parse(desktop / 'pom.xml').findtext('m:properties/m:addopen.java.args', default='', namespaces={'m': 'http://maven.apache.org/POM/4.0.0'})
        env = dict(os.environ, FORGE_BRIDGE_HOSTED='1', FORGE_BRIDGE_WORKER_TOKEN=self.token,
                   APPDATA=self.profile.name + '/AppData/Roaming', LOCALAPPDATA=self.profile.name + '/AppData/Local')
        command = ['java', *shlex.split(options), '-Xmx' + self.config.heap, '-XX:ActiveProcessorCount=1',
                   '-Duser.home=' + self.profile.name, '-cp', classes + os.pathsep + cp,
                   'forge.browser.Bridge', self.origin, '0']
        with self.lifecycle_lock:
            if self.stopped.is_set():
                raise RuntimeError('Worker stopped')
            self.process = subprocess.Popen(command, cwd=desktop, env=env, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, start_new_session=True)
        selector = selectors.DefaultSelector()
        selector.register(self.process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + self.config.startup_timeout
        pending = b''
        try:
            while time.monotonic() < deadline and not self.stopped.is_set():
                if self.process.poll() is not None:
                    raise RuntimeError('Worker exited')
                if not selector.select(.2):
                    continue
                chunk = os.read(self.process.stdout.fileno(), 4096)
                if not chunk:
                    raise RuntimeError('Worker output closed')
                pending += chunk
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    ready = re.fullmatch(rb'Forge worker listening at http://127\.0\.0\.1:(\d+)\r?', line)
                    if ready:
                        self.port = int(ready[1])
                        if not 0 < self.port < 65536:
                            raise RuntimeError('Invalid worker port')
                        # Drain without retaining private game output or blocking the JVM.
                        threading.Thread(target=self.drain, daemon=True).start()
                        self.request('POST', '/matches', decks, 0)
                        return
                if len(pending) > 16384:
                    pending = b''
            raise RuntimeError('Worker startup timed out')
        finally:
            selector.close()

    def drain(self):
        try:
            while self.process.stdout.read(8192):
                pass
        except (OSError, ValueError):
            pass

    def request(self, method, path, payload, seat):
        if self.stopped.is_set() or not self.process or self.process.poll() is not None:
            raise Failure(503, 'Match worker unavailable')
        data = None if payload is None else json.dumps(payload).encode()
        request = Request('http://127.0.0.1:%d/api/v1%s' % (self.port, path), data=data, method=method,
                          headers={'Authorization': 'Bearer ' + self.token, 'Origin': self.origin,
                                   'X-Forge-Seat': str(seat), 'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=10) as response:
                return json.loads(response.read(BODY_LIMIT + 1))
        except HTTPError as error:
            if error.code in (400, 409, 422):
                message = 'Action rejected by engine'
                try:
                    detail = json.loads(error.read(BODY_LIMIT + 1)).get('error')
                    if detail in ('Stale revision', 'Stale prompt', 'Stale match', 'Match is over',
                                  'An action is already in flight'):
                        message = detail
                except (ValueError, AttributeError):
                    pass
                raise Failure(error.code, message) from None
            raise Failure(503, 'Match worker unavailable') from None
        except Exception:
            raise Failure(503, 'Match worker unavailable') from None

    def close(self):
        with self.lifecycle_lock:
            if self.stopped.is_set():
                return
            self.stopped.set()
        if self.process:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
            except ProcessLookupError:
                pass
        self.profile.cleanup()

@dataclass
class Config:
    origin: str
    host: str = '127.0.0.1'
    port: int = 8080
    dev: bool = False
    max_workers: int = 2
    startup_timeout: int = 120
    idle_timeout: int = 1800
    max_lifetime: int = 14400
    heap: str = '1024m'
    static_root: Path = ROOT / 'web/neoforge/dist'

class Gateway:
    def __init__(self, config, access_key, worker_factory=Worker):
        parsed = urlsplit(config.origin)
        if (parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.path or parsed.query or parsed.fragment
                or parsed.username or parsed.password):
            raise ValueError('Origin must be an exact HTTP(S) origin')
        if parsed.scheme != 'https' and not (config.dev and parsed.hostname in ('127.0.0.1', 'localhost', '::1') and config.host in ('127.0.0.1', 'localhost', '::1')):
            raise ValueError('HTTP requires explicit loopback development mode')
        if not access_key or not 1 <= config.max_workers <= 32 or not re.fullmatch(r'[1-9][0-9]*[mg]', config.heap):
            raise ValueError('Access key and bounded worker configuration required')
        if min(config.startup_timeout, config.idle_timeout, config.max_lifetime) <= 0:
            raise ValueError('Lifecycle timeouts must be positive')
        self.config, self.authority = config, parsed.netloc
        self.key_digest = digest(access_key)
        self.worker_factory = worker_factory
        self.sessions, self.matches, self.invites = {}, {}, {}
        self.rates = OrderedDict()
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.reaper = threading.Thread(target=self.reap_loop, daemon=True)
        self.reaper.start()

    def rate(self, key, limit):
        now = time.monotonic()
        with self.lock:
            count, start = self.rates.get(key, (0, now))
            if now - start > 60:
                count, start = 0, now
            self.rates[key] = count + 1, start
            self.rates.move_to_end(key)
            while len(self.rates) > 4096:
                self.rates.popitem(last=False)
            if count >= limit:
                raise Failure(429, 'Request limit reached')

    def session(self, cookie):
        try:
            jar = SimpleCookie(cookie or '')
            token = jar[COOKIE].value
        except Exception:
            return None
        with self.lock:
            session = self.sessions.get(digest(token))
            return session if session and session.expiry > time.time() else None

    def info(self, session):
        if session and session.match_id and session.match_id not in self.matches:
            session.match_id, session.seat = None, None
        return dict(authenticated=bool(session), canCreate=bool(session and session.can_create),
                    seat=session.seat if session else None, hasMatch=bool(session and session.match_id))

    def issue(self, can_create=False):
        if len(self.sessions) >= 4096:
            raise Failure(503, 'Session capacity reached')
        token = secrets.token_urlsafe(32)
        session = Session(digest(token), time.time() + self.config.max_lifetime + 3600, can_create)
        self.sessions[session.digest] = session
        return session, token

    def membership(self, session):
        if not session or not session.match_id or session.match_id not in self.matches:
            raise Failure(403, 'Match membership required')
        record = self.matches[session.match_id]
        if record.seats.get(session.seat) != session.digest:
            raise Failure(403, 'Match membership required')
        record.last_activity = time.time()
        return record

    def snapshot(self, record, seat):
        if record.state == 'failed':
            raise Failure(503, 'Match worker unavailable')
        if record.state in ('waiting', 'starting'):
            return dict(status=record.state, matchId=record.id, revision=0, players=[], stack=[],
                        message='Waiting for your friend' if record.state == 'waiting' else 'Starting match', seat=seat)
        try:
            snapshot = record.worker.request('GET', '/match', None, seat)
        except Failure as error:
            if error.code == 503:
                with self.lock:
                    record.state = 'failed'
            raise
        if snapshot.get('status') in ('finished', 'error'):
            with self.lock:
                record.state = 'finished' if snapshot['status'] == 'finished' else 'failed'
        return snapshot

    def launch(self, record):
        record.state = 'starting'
        worker = self.worker_factory(self.config.origin, self.config)
        record.worker = worker
        def start():
            try:
                worker.start(record.decks)
                with self.lock:
                    if not self.closed.is_set() and record.id in self.matches:
                        record.state = 'running'
            except Exception:
                with self.lock:
                    record.state = 'failed'
                worker.close()
        threading.Thread(target=start, daemon=True).start()

    def api(self, method, path, body, session, remote):
        token = None
        with self.lock:
            if method == 'GET' and path == '/status':
                return dict(status='ready', hosting='server'), token
            if method == 'GET' and path == '/session':
                return self.info(session), token
            if method == 'POST' and path == '/session':
                self.rate(('login', remote), 10)
                key = body.get('accessKey')
                if not isinstance(key, str) or not secrets.compare_digest(digest(key), self.key_digest):
                    raise Failure(403, 'Invalid access key')
                if session:
                    session.can_create = True
                else:
                    session, token = self.issue(True)
                return self.info(session), token
            if method == 'POST' and path == '/logout':
                if session:
                    self.sessions.pop(session.digest, None)
                return self.info(None), ''
            if method == 'POST' and path == '/join':
                self.rate(('join', remote), 20)
                value = body.get('token')
                invite = self.invites.get(digest(value)) if isinstance(value, str) else None
                if session and session.match_id in self.matches:
                    raise Failure(409, 'Browser already owns a match seat')
                if not invite or invite.expiry < time.time():
                    raise Failure(409, 'Invite unavailable')
                record = self.matches.get(invite.match_id)
                if not record or record.state != 'waiting' or 1 in record.seats:
                    raise Failure(409, 'Invite unavailable')
                if not session:
                    session, token = self.issue()
                self.invites.pop(invite.digest)
                record.invite_digest = None
                session.match_id, session.seat = record.id, 1
                record.seats[1] = session.digest
                self.launch(record)
                return self.snapshot(record, 1), token
            if method == 'GET' and path == '/match' and (not session or not session.match_id):
                return dict(status='idle', revision=0, players=[], stack=[]), token
            if method == 'POST' and path == '/matches':
                if not session or not session.can_create:
                    raise Failure(403, 'Creator session required')
                self.rate(('create', session.digest), 5)
                previous = self.matches.get(session.match_id)
                if previous:
                    if previous.state not in ('finished', 'failed'):
                        raise Failure(409, 'Browser already owns a match seat')
                    self.matches.pop(previous.id)
                    if previous.worker:
                        threading.Thread(target=previous.worker.close, daemon=True).start()
                    session.match_id, session.seat = None, None
                if len(self.matches) >= self.config.max_workers:
                    completed = next((r for r in self.matches.values() if r.state in ('finished', 'failed')), None)
                    if completed:
                        self.matches.pop(completed.id)
                        if completed.worker:
                            threading.Thread(target=completed.worker.close, daemon=True).start()
                    else:
                        raise Failure(503, 'Match capacity reached')
                mode = body.get('mode', 'cpu')
                if mode not in ('cpu', 'human') or not all(isinstance(body.get(k), dict) for k in ('humanDeck', 'aiDeck')):
                    raise Failure(400, 'Two deck objects and valid mode required')
                now = time.time()
                record = MatchRecord(secrets.token_urlsafe(18), mode, {k: body[k] for k in ('humanDeck', 'aiDeck')} | {'mode': mode}, now, now)
                self.matches[record.id] = record
                session.match_id, session.seat = record.id, 0
                record.seats[0] = session.digest
                if mode == 'cpu':
                    self.launch(record)
                return self.snapshot(record, 0), token
            record = self.membership(session)
            if method == 'POST' and path == '/invites':
                if not session.can_create or session.seat != 0 or record.mode != 'human' or record.state != 'waiting':
                    raise Failure(403, 'Waiting lobby creator required')
                self.rate(('invite', session.digest), 10)
                if record.invite_digest:
                    self.invites.pop(record.invite_digest, None)
                value = secrets.token_urlsafe(32)
                record.invite_digest = digest(value)
                self.invites[record.invite_digest] = Invite(record.invite_digest, record.id, time.time() + 600)
                return dict(inviteUrl=self.config.origin + '/#invite=' + value), token
            if method == 'GET' and path == '/match':
                worker, seat = record, session.seat
            elif method == 'POST' and path == '/action':
                self.rate(('action', session.digest), 120)
                if record.state != 'running':
                    raise Failure(409 if record.state != 'failed' else 503, 'Match not ready')
                worker, seat = record, session.seat
            else:
                raise Failure(404, 'Endpoint unavailable')
        # Worker I/O must not hold the shared admission/session lock.
        if method == 'GET':
            return self.snapshot(worker, seat), token
        return worker.worker.request('POST', '/action', body, seat), token

    def reap_loop(self):
        while not self.closed.wait(1):
            now = time.time()
            with self.lock:
                expired = [r for r in self.matches.values() if now-r.created > self.config.max_lifetime or now-r.last_activity > self.config.idle_timeout]
                for record in expired:
                    self.matches.pop(record.id, None)
                    if record.invite_digest:
                        self.invites.pop(record.invite_digest, None)
                self.sessions = {k: v for k, v in self.sessions.items() if v.expiry > now}
                self.invites = {k: v for k, v in self.invites.items() if v.expiry > now}
            for record in expired:
                if record.worker:
                    record.worker.close()

    def close(self):
        self.closed.set()
        with self.lock:
            workers = [r.worker for r in self.matches.values() if r.worker]
        for worker in workers:
            worker.close()

class Server(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    request_queue_size = 32
    def __init__(self, address, gateway):
        self.gateway = gateway
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(False):
            request.close()
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            request.settimeout(10)
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, payload, token=None):
        data = json.dumps(dict(payload, schemaVersion=1)).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if token is not None:
            secure = '' if self.server.gateway.config.dev else '; Secure'
            age = self.server.gateway.config.max_lifetime + 3600 if token else 0
            self.send_header('Set-Cookie', '%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d%s' % (COOKIE, token, age, secure))
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.handle_request('GET')

    def do_POST(self):
        self.handle_request('POST')

    def handle_request(self, method):
        gateway = self.server.gateway
        try:
            if len(self.headers.get_all('Host', [])) != 1 or self.headers.get('Host') != gateway.authority:
                raise Failure(403, 'Untrusted host')
            gateway.rate(('request', self.client_address[0]), 600)
            body = None
            if method == 'POST':
                if self.headers.get_all('Origin', []) != [gateway.config.origin]:
                    raise Failure(403, 'Untrusted origin')
                if self.headers.get_content_type() != 'application/json':
                    raise Failure(415, 'JSON required')
                if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
                    raise Failure(400, 'Content length required')
                try:
                    length = int(self.headers['Content-Length'])
                except ValueError:
                    raise Failure(400, 'Invalid content length') from None
                if not 0 <= length <= BODY_LIMIT:
                    raise Failure(413, 'Request body too large')
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise Failure(400, 'Incomplete request body')
                try:
                    body = json.loads(raw)
                except (ValueError, UnicodeError):
                    raise Failure(400, 'Invalid JSON') from None
                if not isinstance(body, dict):
                    raise Failure(400, 'JSON object required')
            path = urlsplit(self.path).path
            if path.startswith('/api/v1/'):
                allowed = {'GET': {'/status', '/session', '/match'}, 'POST': {'/session', '/logout', '/matches', '/action', '/invites', '/join'}}
                endpoint = path[len('/api/v1'):]
                if endpoint not in allowed[method]:
                    raise Failure(404, 'Endpoint unavailable')
                result, token = gateway.api(method, endpoint, body, gateway.session(self.headers.get('Cookie')), self.client_address[0])
                self.reply(200, result, token)
                return
            if method != 'GET':
                raise Failure(404, 'Endpoint unavailable')
            root = gateway.config.static_root.resolve()
            target = (root / unquote(path).lstrip('/')).resolve()
            if not target.is_relative_to(root) or any(p.startswith('.') for p in target.relative_to(root).parts):
                raise Failure(404, 'File unavailable')
            if target.is_dir():
                target = (target / 'index.html').resolve()
            if not target.is_relative_to(root):
                raise Failure(404, 'File unavailable')
            if not target.is_file():
                raise Failure(404, 'File unavailable')
            import mimetypes
            data = target.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', mimetypes.guess_type(target)[0] or 'application/octet-stream')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)
        except Failure as error:
            self.close_connection = True
            self.reply(error.code, dict(error=error.message))
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception:
            self.close_connection = True
            self.reply(503, dict(error='Service unavailable'))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', default=8080, type=int)
    parser.add_argument('--dev', action='store_true')
    parser.add_argument('--max-workers', default=2, type=int)
    parser.add_argument('--startup-timeout', default=120, type=int)
    parser.add_argument('--idle-timeout', default=1800, type=int)
    parser.add_argument('--max-lifetime', default=14400, type=int)
    parser.add_argument('--heap', default='1024m')
    config = Config(**vars(parser.parse_args()))
    gateway = Gateway(config, os.environ.get('NEOFORGE_ACCESS_KEY'))
    server = Server((config.host, config.port), gateway)
    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        gateway.close()

if __name__ == '__main__':
    main()
