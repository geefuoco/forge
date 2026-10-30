"""Exercise table layout and interactions with explicit synthetic artwork fixtures."""
import copy
import functools
import http.server
import json
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1] / 'dist'
OUTPUT = Path('/tmp/neoforge-table-proof')
OUTPUT.mkdir(exist_ok=True)

class QuietServer(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietServer, directory=str(ROOT)))
threading.Thread(target=server.serve_forever, daemon=True).start()
origin = f'http://127.0.0.1:{server.server_port}'
names = ['Island', 'Swamp', 'Accursed Marauder', 'Ravenform', 'Chittering Rats', 'Fleshbag Marauder', 'Fellwar Stone', 'Vren, the Relentless', 'Hearthhull, the Worldseed', 'Missing Artwork', 'Transformed Fixture']
def card(index, name, **changes):
    return dict(id=str(index), name=name, type='Basic Land' if name in ('Island', 'Swamp') else 'Creature', text='Fixture rules text. This image is synthetic test artwork.', mana='{2}{U}', **changes)

snapshot = dict(schemaVersion=1, matchId='table-proof', revision=1, status='playing', turn=4, phase='MAIN1', activePlayerId='you', viewerPlayerId='you', players=[
    dict(id='you', name='You', life=37, handCount=7, libraryCount=82, hand=[card(i, name) for i, name in enumerate(names[:7])], battlefield=[card(20, 'Chittering Rats', pt='2 / 2', counters={'+1/+1': 2}), card(21, 'Fellwar Stone', tapped=True), card(22, 'Island', tapped=True), card(23, 'Swamp')], command=[card(30, 'Vren, the Relentless')], graveyard=[card(31, 'Missing Artwork')], exile=[]),
    dict(id='cpu', name='Forge CPU', life=40, handCount=5, libraryCount=83, battlefield=[card(40, 'Hearthhull, the Worldseed', pt='4 / 4'), card(41, 'Island'), card(42, 'Face-down card', faceDown=True)], command=[card(43, 'Hearthhull, the Worldseed')], graveyard=[], exile=[]),
], stack=[], prompt=dict(id='priority-one', kind='priority', message='Your priority. Play a card or pass.', buttons=[dict(id='ok', label='Pass priority', enabled=True)]), log=['You played Island.', 'Forge CPU passed priority.'])
requests, submissions, errors = [], [], []


def api(route):
    path = urlsplit(route.request.url).path.rsplit('/', 1)[-1]
    if path == 'session':
        data = dict(schemaVersion=1, authenticated=True, canCreate=True, seat=0, hasMatch=True, transport='desktop', relayConfigured=False)
    elif path == 'library':
        data = dict(schemaVersion=1, exists=True, decks=[])
    elif path == 'action':
        submissions.append(route.request.post_data_json)
        data = copy.deepcopy(snapshot)
    else:
        data = copy.deepcopy(snapshot)
    route.fulfill(json=data)


def metadata(route):
    name = parse_qs(urlsplit(route.request.url).query)['exact'][0]
    requests.append((name, time.monotonic()))
    if name == 'Missing Artwork':
        route.fulfill(status=404, json={'object': 'error'})
    elif name == 'Transformed Fixture':
        route.fulfill(json={'card_faces': [{'name': 'First Face', 'image_uris': {'normal': 'https://cards.scryfall.io/front.svg'}}, {'name': name, 'image_uris': {'normal': 'https://cards.scryfall.io/back.svg'}}]})
    else:
        route.fulfill(json={'image_uris': {'normal': 'https://cards.scryfall.io/' + str(names.index(name) if name in names else 50) + '.svg'}})


def image(route):
    number = int(urlsplit(route.request.url).path.strip('/').split('.')[0]) if urlsplit(route.request.url).path.strip('/').split('.')[0].isdigit() else 1
    colors = ['#447e96', '#776b82', '#716a52', '#55888a', '#596e55', '#8b6a64']
    tone = colors[number % len(colors)]
    route.fulfill(content_type='image/svg+xml', body=f'''<svg xmlns="http://www.w3.org/2000/svg" width="488" height="680"><rect width="488" height="680" rx="23" fill="#192d31"/><rect x="16" y="16" width="456" height="648" rx="16" fill="{tone}"/><rect x="30" y="31" width="428" height="48" rx="7" fill="#ddd5b9"/><text x="46" y="62" font-family="serif" font-size="22" fill="#273636">SYNTHETIC CARD FIXTURE</text><rect x="30" y="92" width="428" height="309" fill="#14313c"/><circle cx="265" cy="196" r="70" fill="{tone}"/><path d="M30 370L140 170L260 365L350 230L458 370Z" fill="#557c79"/><path d="M30 400L165 290L265 400L380 300L458 400Z" fill="#8c9b7d"/><rect x="30" y="420" width="428" height="218" fill="#ddd6bd"/><text x="48" y="452" font-size="21" font-family="serif" fill="#263c3f">Layout test image</text><text x="48" y="485" font-size="17" font-family="serif" fill="#263c3f">Not actual Magic artwork.</text><path d="M48 520H410M48 545H390M48 570H425M48 595H350" stroke="#8b9587" stroke-width="6"/></svg>''')


try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/data/cards.json', lambda route: route.fulfill(json=[dict(name=name, type='Basic Land' if name in ('Island', 'Swamp') else 'Creature', text='Synthetic fixture rules text.', mana='{2}{U}', identity='U', mv=3, commander=False) for name in names]))
        page.route('**/api/v1/**', api)
        page.route('https://api.scryfall.com/**', metadata)
        page.route('https://cards.scryfall.io/**', image)
        page.goto(origin)
        expect(page.locator('.game-table')).to_be_visible()
        expect(page.locator('.hand-zone [data-card]')).to_have_count(7)
        expect(page.locator('.opponent-hand .card-back')).to_have_count(5)
        expect(page.locator('.opponent-field .hand-zone')).to_have_count(0)
        expect(page.locator('[data-art-state="ready"]').first).to_be_visible(timeout=15000)
        expect(page.locator('[data-visible-card="30"] [data-art-state="ready"]')).to_have_count(1, timeout=15000)
        assert not any(name == 'Face-down card' for name, _ in requests)
        assert all(requests[i][1] - requests[i - 1][1] >= .17 for i in range(1, len(requests))), requests
        for name in {name for name, _ in requests}:
            assert len([x for x, _ in requests if x == name]) == 1
        expect(page.locator('[data-art-state="loading"]')).to_have_count(0, timeout=15000)
        first = page.locator('.hand-zone [data-card]').first
        first.focus()
        expect(page.locator('#card-inspection h3')).to_have_text('Island')
        assert not submissions
        page.locator('[data-inspect="30"]').click(force=True)
        expect(page.locator('#card-inspection h3')).to_have_text('Vren, the Relentless')
        assert not submissions
        page.locator('.hand-zone [data-card="0"]').click()
        assert submissions[-1]['kind'] == 'card' and submissions[-1]['cardId'] == '0'
        page.locator('[data-prompt-button="ok"]').click()
        assert submissions[-1]['kind'] == 'ok'
        page.locator('[data-inspect="30"]').click(force=True)
        hand_box = page.locator('.hand-zone').bounding_box()
        assert hand_box['y'] + hand_box['height'] <= 900, hand_box
        page.screenshot(path=str(OUTPUT / 'desktop-fixture.png'), full_page=True)
        snapshot['revision'] += 1
        before = len(requests)
        page.wait_for_timeout(1600)
        assert len(requests) == before, 'Polling repeated cached image lookups'
        page.locator('.local-field .zone-pocket').first.locator('summary').click()
        expect(page.locator('[data-visible-card="31"] [data-art-state="unavailable"]')).to_have_count(1, timeout=10000)
        expect(page.locator('[data-action="retry-art"]')).to_be_visible()
        page.locator('[data-action="retry-art"]').click()
        page.wait_for_timeout(500)
        assert len([name for name, _ in requests if name == 'Missing Artwork']) == 2
        snapshot['players'][0]['hand'].append(card(80, 'Transformed Fixture'))
        snapshot['revision'] += 1
        expect(page.locator('[data-visible-card="80"] img')).to_have_attribute('src', 'https://cards.scryfall.io/back.svg', timeout=12000)
        snapshot['players'][0]['battlefield'] += [card(100 + i, names[i % 7], tapped=i % 3 == 0) for i in range(22)]
        snapshot['revision'] += 1
        expect(page.locator('.local-field .table-card')).to_have_count(28)
        crowded_hand = page.locator('.hand-zone').bounding_box()
        assert crowded_hand['y'] + crowded_hand['height'] <= 900, crowded_hand
        page.screenshot(path=str(OUTPUT / 'crowded-fixture.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Desktop overflows'
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(OUTPUT / 'narrow-fixture.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Narrow table overflows'
        expect(page.locator('.decision-dock')).to_be_visible()
        snapshot['status'] = 'finished'
        snapshot['result'] = dict(kind='decided', endReason='Conceded', turns=4, participants=[dict(name='You', outcome='lost', lossReason='Conceded'), dict(name='Forge CPU', outcome='won')])
        snapshot['revision'] += 1
        expect(page.get_by_role('heading', name='You conceded', exact=True)).to_be_visible()
        expect(page.locator('[data-card], [data-player], [data-prompt-button], [data-action="concede"]')).to_have_count(0)
        assert not errors, errors
        browser.close()
    report = dict(status='passed', scope='Synthetic snapshot and artwork fixtures only. Does not verify real Scryfall artwork or Forge gameplay.', checks=['spatial board and private hand', 'rate-bound deduplicated artwork loading', 'cache retained across polling', 'inspection never dispatches; card and prompt controls dispatch', 'artwork unavailable and explicit retry', 'matching transformed face', 'crowded desktop and narrow layout', 'terminal controls inactive'], screenshots=[str(p) for p in OUTPUT.glob('*.png')])
    (OUTPUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
finally:
    server.shutdown()
