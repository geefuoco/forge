"""Drive a packaged CPU game through the real board with artwork explicitly offline."""
import argparse
import hashlib
import importlib.util
import json
import os
import platform
from pathlib import Path
import subprocess
import time

from playwright.sync_api import expect, sync_playwright

spec = importlib.util.spec_from_file_location('installed_game', Path(__file__).with_name('installed-game.py'))
installed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installed)


def run(image, work):
    work.mkdir(parents=True, exist_ok=False)
    binary = image / ('NeoForge.exe' if os.name == 'nt' else 'bin/NeoForge')
    payload = image / ('app' if os.name == 'nt' else 'lib/app')
    log = work / 'launcher.log'
    environment = dict(os.environ)
    environment['PATH'] = os.environ.get('SystemRoot', '') + '\\System32' if os.name == 'nt' else '/nonexistent'
    for name in ('JAVA_HOME', 'JDK_HOME', 'MAVEN_HOME', 'CLASSPATH'):
        environment.pop(name, None)
    state = {'snapshot': {}, 'errors': [], 'actions': 0, 'closing': False}
    checks = []
    with log.open('w') as output:
        process = subprocess.Popen([str(binary), '--no-open', '--profile', str(work / 'profile')],
                                   cwd=work, env=environment, stdout=output, stderr=subprocess.STDOUT)
        try:
            origin = None
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                for line in log.read_text(errors='replace').splitlines():
                    if line.startswith('NeoForge client listening at '):
                        origin = line.split(' at ', 1)[1].strip()
                if origin:
                    break
                if process.poll() is not None:
                    raise RuntimeError('Native launcher exited; inspect launcher.log')
                time.sleep(.1)
            assert origin, 'Native launcher did not become ready'
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH', '/usr/bin/chromium'), args=['--no-sandbox'])
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                page.route('https://api.scryfall.com/**', lambda route: route.abort())
                def receive(response):
                    if state['closing'] or '/api/v1/' not in response.url:
                        return
                    try:
                        data = response.json()
                        if 'players' in data:
                            installed.privacy(data)
                            state['snapshot'] = data
                    except Exception as error:
                        if not state['closing']:
                            state['errors'].append(str(error))
                def request(request):
                    if request.method == 'POST' and request.url.endswith('/api/v1/action'):
                        state['actions'] += 1
                page.on('response', receive)
                page.on('request', request)
                page.on('pageerror', lambda error: state['errors'].append(str(error)))
                page.goto(origin)
                page.locator('[data-action="stocks"]').click()
                page.locator('[data-stock]').nth(0).click()
                page.locator('[data-stock]').nth(1).click()
                page.locator('#dialog-content [data-action="close"]').click()
                page.locator('[data-nav="play"]').click()
                page.locator('#human-deck').select_option(index=1)
                page.locator('#ai-deck').select_option(index=0)
                page.locator('[data-action="start"]').click()
                land_id = None
                deadline = time.monotonic() + 150
                while time.monotonic() < deadline:
                    page.wait_for_timeout(150)
                    snapshot = state['snapshot']
                    assert snapshot.get('status') != 'error', snapshot.get('error')
                    own = next((p for p in snapshot.get('players', []) if p['id'] == snapshot.get('viewerPlayerId')), None)
                    if not own or not snapshot.get('prompt'):
                        continue
                    if 'opening hand and private opponent hand' not in checks:
                        assert own.get('hand'), 'Opening hand is empty'
                        checks.append('opening hand and private opponent hand')
                        page.screenshot(path=str(work / 'opening-hand.png'), full_page=True)
                    if land_id and any(c['id'] == land_id for c in own.get('battlefield', [])):
                        checks.append('land played through card activation and confirmed by Forge')
                        break
                    prompt = snapshot['prompt']
                    if (not land_id and prompt['kind'] == 'priority' and snapshot.get('activePlayerId') == own['id']
                            and snapshot.get('phase') in ('MAIN1', 'MAIN2')):
                        land = next((c for c in own.get('hand', []) if 'Land' in c.get('type', '')), None)
                        if land:
                            land_id = land['id']
                            page.locator('.hand-zone [data-card="' + land_id + '"]').click()
                            continue
                    installed.advance(page, snapshot)
                else:
                    raise TimeoutError('Did not reach a confirmed human land play')
                inspected = page.locator('.hand-zone [data-card]').first
                before = state['actions']
                inspected.focus()
                expect(page.locator('#card-inspection h3')).not_to_be_empty()
                page.wait_for_timeout(200)
                assert state['actions'] == before, 'Inspecting a card submitted an action'
                checks.append('keyboard inspection does not activate a card')
                box = page.locator('.hand-zone').bounding_box()
                assert box['y'] + box['height'] <= 900, box
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(work / 'real-game-board.png'), full_page=True)
                checks.append('real board and hand fit the desktop viewport')
                page.locator('[data-action="concede"]').click()
                expect(page.get_by_role('heading', name='You conceded', exact=True)).to_be_visible(timeout=30000)
                assert state['snapshot'].get('result'), 'No authoritative completion result'
                expect(page.locator('[data-card], [data-player], [data-prompt-button], [data-action="concede"]')).to_have_count(0)
                page.screenshot(path=str(work / 'completion.png'), full_page=True)
                checks.append('authoritative concession and inactive completed board')
                assert not state['errors'], state['errors']
                state['closing'] = True
                browser.close()
            report = dict(status='passed', platform=platform.system(), scope='Real packaged client and Forge CPU game; artwork provider forced offline, no real image or natural-game claim.',
                          buildId=json.loads((payload / 'client-config.json').read_text())['buildId'],
                          checks=checks, browserActions=state['actions'], errors=state['errors'],
                          clientJarSha256=hashlib.sha256((payload / 'client.jar').read_bytes()).hexdigest())
            (work / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(report, indent=2))
        finally:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    run(args.image.resolve(), args.work.resolve())
