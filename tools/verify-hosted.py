"""Browser contract checks against a cookie gateway mock and existing prompt regressions."""
import functools
import http.server
import json
import re
import subprocess
import sys
import threading
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'web/neoforge/dist'
sessions = {}
requests = []
mode = 'cpu'
joined = False
fail_match = False


def snapshot(seat):
    if mode == 'human' and not joined:
        return dict(schemaVersion=1, status='waiting', matchId='lobby', revision=0, players=[], stack=[], seat=seat)
    return dict(schemaVersion=1, status='playing', matchId='engine', revision=1, seat=seat,
                players=[dict(id=str(i), name=f'Player {i}', life=40, handCount=1, libraryCount=90,
                              hand=[dict(id=f'card{i}', name=f'Secret {i}')]) for i in range(2)], stack=[],
                prompt=dict(id=f'prompt{seat}', kind='input', message=f'Decision for seat {seat}', initial='restored'))


class Gateway(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, data, status=200, cookie=None):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        if cookie:
            self.send_header('Set-Cookie', f'session={cookie}; HttpOnly; SameSite=Lax; Path=/')
        self.end_headers()
        self.wfile.write(json.dumps({"schemaVersion": 1, **data}).encode())

    def session(self):
        cookie = self.headers.get('Cookie', '').removeprefix('session=')
        return sessions.get(cookie)

    def do_GET(self):
        global fail_match
        if self.path == '/data/cards.json':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'[]')
            return
        if not self.path.startswith('/api/'):
            return super().do_GET()
        session = self.session()
        requests.append((self.path, self.headers, None))
        if self.path.endswith('/session'):
            self.reply(dict(authenticated=bool(session), canCreate=bool(session and session['creator']),
                            seat=session['seat'] if session else None, hasMatch=bool(session and session.get('match'))))
        elif fail_match:
            self.reply(dict(error='Worker unavailable'), 503)
        elif not session or not session.get('match'):
            self.reply(dict(status='idle', revision=0, players=[], stack=[]))
        else:
            self.reply(snapshot(session['seat']))

    def do_POST(self):
        global mode, joined
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        requests.append((self.path, self.headers, body))
        assert self.headers['Content-Type'] == 'application/json'
        assert self.headers['Origin'] == origin
        assert not self.headers.get('Authorization')
        if self.path.endswith('/session'):
            if body['accessKey'] != 'private':
                return self.reply(dict(error='Invalid access key'), 401)
            sessions['host'] = dict(creator=True, seat=0, match=False)
            return self.reply(dict(authenticated=True, canCreate=True, seat=0, hasMatch=False), cookie='host')
        if self.path.endswith('/join'):
            if joined:
                return self.reply(dict(error='Invitation already used'), 409)
            assert body == dict(token='one-use')
            joined = True
            sessions['guest'] = dict(creator=False, seat=1, match=True)
            return self.reply(snapshot(1), cookie='guest')
        session = self.session()
        assert session
        if self.path.endswith('/matches'):
            mode = body['mode']
            session['match'] = True
            assert body['humanDeck']['entries'] and body['aiDeck']['entries']
            return self.reply(snapshot(0))
        if self.path.endswith('/invites'):
            return self.reply(dict(inviteUrl=origin + '/#invite=one-use'))
        raise AssertionError(self.path)


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Gateway, directory=str(DIST)))
origin = f'http://127.0.0.1:{server.server_port}'
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        host_context = browser.new_context(permissions=['clipboard-read', 'clipboard-write'])
        host_context.add_init_script("localStorage.setItem('neoforge-library-v1', JSON.stringify({decks:[{id:'deck',name:'Test deck',entries:[{name:'Forest',quantity:100,section:'main'}]}]}))")
        host = host_context.new_page()
        errors = []
        host.on('pageerror', lambda e: errors.append(str(e)))
        host.goto(origin)
        host.locator('[data-nav="play"]').click()
        host.locator('[data-action="connect"]').first.click()
        host.locator('#access-key').fill('bad')
        host.locator('[data-action="login"]').click()
        expect(host.locator('#connect-error')).to_contain_text('Invalid access key')
        host.locator('#access-key').fill('private')
        host.locator('[data-action="login"]').click()
        expect(host.locator('#match-mode')).to_be_visible()
        host.locator('[data-action="start"]').click()
        expect(host.locator('#prompt-input')).to_have_value('restored')
        expect(host.get_by_text('Secret 0', exact=True)).to_be_visible()
        expect(host.get_by_text('Secret 1', exact=True)).to_have_count(0)
        host.reload()
        expect(host.locator('#prompt-input')).to_have_value('restored')
        fail_match = True
        expect(host.locator('[data-action="reconnect"]')).to_be_visible(timeout=5000)
        fail_match = False
        host.locator('[data-action="reconnect"]').click()
        expect(host.locator('#prompt-input')).to_have_value('restored')
        sessions['host']['match'] = False
        host.reload()
        host.locator('[data-nav="play"]').click()
        host.locator('#match-mode').select_option('human')
        host.locator('[data-action="start"]').click()
        expect(host.get_by_role('heading', name='Waiting for your friend')).to_be_visible()
        host.locator('[data-action="invite"]').click()
        expect(host.locator('#invite-url')).to_have_value(origin + '/#invite=one-use')
        host.locator('[data-action="copy-invite"]').click()
        assert host.evaluate('navigator.clipboard.readText()') == origin + '/#invite=one-use'
        guest_context = browser.new_context()
        guest = guest_context.new_page()
        guest.on('pageerror', lambda e: errors.append(str(e)))
        guest.add_init_script("window.fetch = new Proxy(window.fetch, {apply(target, self, args) { if(location.hash) throw Error('Fragment still present during request'); return Reflect.apply(target,self,args); }});")
        guest.goto(origin + '/#invite=one-use')
        expect(guest.locator('#prompt-input')).to_have_value('restored')
        assert guest.url == origin + '/'
        expect(guest.get_by_text('Secret 1', exact=True)).to_be_visible()
        expect(guest.get_by_text('Secret 0', exact=True)).to_have_count(0)
        expect(guest.locator('section').filter(has_text='Your seat').first).to_contain_text('Player 1')
        guest.reload()
        expect(guest.locator('#prompt-input')).to_have_value('restored')
        replay = browser.new_page()
        replay.goto(origin + '/#invite=one-use')
        expect(replay.locator('.flash')).to_contain_text('Invitation already used')
        assert not errors, errors
        assert all(not headers.get('Authorization') for _, headers, _ in requests)
        assert any(path.endswith('/match') and 'session=guest' in headers.get('Cookie', '') for path, headers, _ in requests)
        browser.close()
    print('PASS hosted login, CPU/human creation, invite copy/join/replay, private seat orientation, cookie reload and reconnect')
finally:
    server.shutdown()

for name in ['inputs', 'allocations', 'completion', 'terminal-action']:
    path = ROOT / f'web/neoforge/tools/verify-{name}.py'
    source = path.read_text()
    source = re.sub(r'^.*page\.locator\(.*(?:data-action="connect"|#host-token|data-action="pair").*\n', '', source, flags=re.M)
    if name == 'terminal-action':
        source = source.replace('        if path == "status":', '        if path == "session":\n            await route.fulfill(json={"schemaVersion":1,"authenticated":True,"canCreate":True,"seat":0,"hasMatch":True})\n            return\n        if path == "status":')
    else:
        source = source.replace('    if path == "status":', '    if path == "session":\n        data = {"schemaVersion":1,"authenticated":True,"canCreate":True,"seat":0,"hasMatch":True}\n    elif path == "status":')
    result = subprocess.run([sys.executable, '-c', f'__file__ = {str(path)!r}\n' + source], cwd=ROOT)
    if result.returncode:
        raise SystemExit(result.returncode)
