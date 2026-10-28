"""Drive two packaged clients, a real relay, and Forge through browser controls."""
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
from urllib.parse import urlsplit, parse_qs

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('player_relay', ROOT / 'tools/player-relay/server.py')
r = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = r
spec.loader.exec_module(r)


def launch(image, profile, log):
    binary = image / ('NeoForge.exe' if os.name == 'nt' else 'bin/NeoForge')
    environment = dict(os.environ)
    environment['PATH'] = os.environ.get('SystemRoot', '') + '\\System32' if os.name == 'nt' else '/nonexistent'
    for variable in ('JAVA_HOME', 'JDK_HOME', 'MAVEN_HOME', 'CLASSPATH'):
        environment.pop(variable, None)
    stream = log.open('w')
    process = subprocess.Popen([str(binary), '--no-open', '--dev', '--profile', str(profile)],
                               cwd=profile.parent, env=environment, stdout=stream, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        text = log.read_text(errors='replace')
        for line in text.splitlines():
            if line.startswith('NeoForge client listening at '):
                return process, stream, line.split(' at ', 1)[1].strip()
        if process.poll() is not None:
            raise RuntimeError(text)
        time.sleep(.1)
    process.terminate()
    process.wait(timeout=20)
    raise TimeoutError('Packaged executable did not start')


def privacy(snapshot):
    if not snapshot.get('players'):
        return
    viewer = snapshot['viewerPlayerId']
    assert len([p for p in snapshot['players'] if 'hand' in p]) == 1
    for player in snapshot['players']:
        assert 'library' not in player
        if player['id'] != viewer:
            assert 'hand' not in player


def advance(page, snapshot):
    prompt = snapshot.get('prompt')
    if not prompt:
        return False
    kind = prompt['kind']
    if kind in ('priority', 'confirm'):
        enabled = [b for b in prompt.get('buttons', []) if b.get('enabled')]
        button = next((b for b in enabled if 'keep' in b['label'].lower()), None)
        button = button or next((b for b in enabled if b['id'] == 'ok'), None) or next(iter(enabled), None)
        if button:
            page.locator('[data-prompt-button="' + button['id'] + '"]').click(timeout=1500)
        else:
            own = next(p for p in snapshot['players'] if p['id'] == snapshot['viewerPlayerId'])
            assert own.get('hand'), 'Selection input has no available card'
            page.locator('[data-card="' + own['hand'][0]['id'] + '"]').click(timeout=1500)
    elif kind in ('choices', 'order'):
        for index in range(max(0, prompt.get('min', 0))):
            page.locator('input[name="choice"]').nth(index).check(timeout=1500)
        page.locator('[data-action="submit-choice"]').click(timeout=1500)
    elif kind == 'reveal':
        page.locator('[data-prompt-button="ok"]').click(timeout=1500)
    elif kind == 'manipulate':
        page.get_by_role('button', name='Confirm order', exact=True).click(timeout=1500)
    elif kind == 'input':
        if prompt.get('options') == []:
            page.locator('[data-action="cancel-input"]').click(timeout=1500)
        else:
            page.get_by_role('button', name='Confirm response', exact=True).click(timeout=1500)
    else:
        raise RuntimeError('Probe cannot answer ' + kind)
    return True


def main(image, work):
    image, work = image.resolve(), work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    registry = r.Registry('http://127.0.0.1:8080')
    server = r.RelayServer(('127.0.0.1', 0), registry, '')
    origin = f'http://127.0.0.1:{server.server_port}'
    registry.origin, server.authority = origin, urlsplit(origin).netloc
    threading.Thread(target=server.serve_forever, daemon=True).start()
    running = []
    checks, errors, snapshots = [], [], {}
    observing = {"enabled": True}
    try:
        clients = []
        for role in ('host', 'guest'):
            process, stream, local = launch(image, work / (role + '-profile'), work / (role + '.log'))
            running.append((process, stream))
            clients.append(local)
        checks.append('both native executables started without external runtime tools')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH', '/usr/bin/chromium'), args=['--no-sandbox'])
            contexts = [browser.new_context(viewport={'width': 1440, 'height': 1000}) for _ in clients]
            pages = [context.new_page() for context in contexts]
            def receive(role, response):
                if not observing['enabled'] or '/api/v1/' not in response.url:
                    return
                try:
                    data = response.json()
                    if 'players' in data:
                        privacy(data)
                        snapshots[role] = data
                except Exception as error:
                    if observing["enabled"]:
                        errors.append(str(error))
            for role, page, local in zip(('host', 'guest'), pages, clients):
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('response', lambda response, role=role: receive(role, response))
                page.goto(local)
                expect(page.locator('[data-nav="play"]')).to_be_visible()
            host, guest = pages
            for role, page in zip(('host', 'guest'), pages):
                page.locator('[data-action="connect"]').click()
                expect(page.locator('#relay-origin')).to_be_visible()
                if role == 'host':
                    page.locator('#relay-origin').fill('https://invalid.example/path')
                    page.locator('[data-action="save-relay"]').click()
                    expect(page.locator('#relay-error')).not_to_be_empty()
                    assert page.locator('#relay-origin').input_value() == 'https://invalid.example/path'
                page.locator('#relay-origin').fill(origin)
                page.locator('[data-action="save-relay"]').click()
                expect(page.locator('#relay-notice')).to_have_text('Relay saved.')
                expect(page.locator('#dialog-content')).to_contain_text(origin)
                if role == 'host':
                    page.screenshot(path=str(work / 'relay-settings.png'), full_page=True)
                page.locator('#dialog-content [data-action="close"]').click()
            checks.append('relay saved through Client info; invalid draft survives server error')
            process, stream = running[0]
            process.terminate()
            process.wait(timeout=20)
            stream.close()
            process, stream, clients[0] = launch(image, work / 'host-profile', work / 'host-restart.log')
            running[0] = process, stream
            host.goto(clients[0])
            host.locator('[data-action="connect"]').click()
            expect(host.locator('#relay-origin')).to_have_value(origin)
            expect(host.locator('#dialog-content')).to_contain_text('Saved in this app')
            host.locator('#dialog-content [data-action="close"]').click()
            checks.append('saved relay survives native restart and new local port')
            host.locator('[data-action="stocks"]').click()
            host.locator('[data-stock]').nth(0).click()
            host.locator('[data-stock]').nth(1).click()
            host.locator('#dialog-content [data-action="close"]').click()
            host.locator('[data-nav="play"]').click()
            host.locator('#match-mode').select_option('human')
            host.locator('#ai-deck').select_option(index=1)
            host.locator('[data-action="start"]').click()
            host.locator('[data-action="connect"]').click()
            expect(host.locator('#relay-origin')).to_be_disabled()
            expect(host.locator('#dialog-content')).to_contain_text('Restart the app')
            host.locator('#dialog-content [data-action="close"]').click()
            host.locator('[data-action="invite"]').click()
            invitation = host.locator('#invite-url').input_value()
            fragment = parse_qs(urlsplit(invitation).fragment)
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
            payload = {'protocolVersion': 1, 'buildId': 'wrong-release', 'inviteToken': fragment['invite'][0]}
            connection.request('POST', '/relay/v1/rooms/' + fragment['room'][0] + '/join', json.dumps(payload), {'Content-Type': 'application/json'})
            response = connection.getresponse()
            assert response.status == 409, response.read()
            response.read()
            connection.close()
            guest.locator('[data-nav="play"]').click()
            guest.locator('[data-action="join-friend"]').click()
            guest.locator('#friend-invitation').fill(invitation)
            guest.locator('[data-action="join-desktop"]').click()
            expect(guest.locator('#dialog')).not_to_be_visible(timeout=15000)
            checks += ['mismatched build cannot consume invitation', 'friend joins through installed interface', 'waiting host cannot change relay']
            seen = {}
            actions = 0
            deadline = time.monotonic() + 100
            while time.monotonic() < deadline:
                host.wait_for_timeout(100)
                for role, page in zip(('host', 'guest'), pages):
                    snapshot = snapshots.get(role, {})
                    assert snapshot.get('status') != 'error', snapshot.get('error')
                    if snapshot.get('revision') == seen.get(role):
                        continue
                    seen[role] = snapshot.get('revision')
                    try:
                        actions += int(advance(page, snapshot))
                    except Exception as error:
                        if 'Probe cannot' in str(error):
                            raise
                        seen[role] = None
                if all(snapshots.get(role, {}).get('turn', 0) >= 3 for role in ('host', 'guest')):
                    break
            else:
                raise TimeoutError('Two installed clients did not advance to turn 3')
            assert snapshots['host']['matchId'] == snapshots['guest']['matchId']
            assert snapshots['host']['viewerPlayerId'] != snapshots['guest']['viewerPlayerId']
            checks.append('real Forge game advances through both private seat views')
            match_id = snapshots['guest']['matchId']
            guest.reload()
            expect(guest.locator('[data-action="concede"]')).to_be_visible(timeout=10000)
            assert snapshots['guest']['matchId'] == match_id
            checks.append('browser reload reconnects to same host match')
            snapshot = snapshots['guest']
            stale = guest.evaluate('''async action => {
                const response = await fetch('/api/v1/action', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(action)});
                return response.status;
            }''', {'kind': 'ok', 'matchId': match_id, 'revision': 0, 'promptId': snapshot.get('prompt', {}).get('id', 'old')})
            assert stale == 409, stale
            checks.append('stale action rejected through relay')
            guest.locator('[data-action="concede"]').click()
            guest.locator('[data-action="confirm-concede"]').click()
            expect(guest.locator('.game-result')).to_be_visible(timeout=20000)
            expect(host.locator('.game-result')).to_be_visible(timeout=20000)
            for role, page in zip(('host', 'guest'), pages):
                assert snapshots[role]['result'], snapshots[role]
                expect(page.locator('[data-action="concede"]')).to_have_count(0)
                page.screenshot(path=str(work / (role + '-terminal.png')), full_page=True)
            assert any(p.get('lossReason') == 'Conceded' for p in snapshots['guest']['result']['participants'])
            checks.append('guest concession yields authoritative result in both clients')
            assert not errors, errors
            observing["enabled"] = False
            browser.close()
        result = {'scope': 'local packaged Linux clients and real relay, not public deployment', 'checks': checks,
                  'browserActions': actions, 'errors': errors,
                  'buildId': json.loads((image / ('app/client-config.json' if os.name == 'nt' else 'lib/app/client-config.json')).read_text())['buildId'],
                  'sourceRevision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()}
        (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result), flush=True)
    finally:
        for process, stream in reversed(running):
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            stream.close()
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    main(args.image, args.work)
