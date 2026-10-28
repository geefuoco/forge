"""Launch a native bundle without build tools and start a real Forge CPU game."""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPCookieProcessor, ProxyHandler, Request


def run(image):
    binary = image / ('NeoForge.exe' if os.name == 'nt' else 'bin/NeoForge')
    with tempfile.TemporaryDirectory(prefix='neoforge-native-smoke-') as temporary:
        root = Path(temporary)
        log = root / 'launcher.log'
        environment = dict(os.environ)
        environment['PATH'] = os.environ.get('SystemRoot', '') + '\\System32' if os.name == 'nt' else '/nonexistent'
        for name in ('JAVA_HOME', 'JDK_HOME', 'MAVEN_HOME', 'CLASSPATH'):
            environment.pop(name, None)
        with log.open('w', encoding='utf-8') as output:
            process = subprocess.Popen([str(binary), '--no-open', '--profile', str(root / 'profile')],
                                       cwd=root, env=environment, stdout=output, stderr=subprocess.STDOUT)
            try:
                origin = None
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    for line in log.read_text(encoding='utf-8', errors='replace').splitlines():
                        if line.startswith('NeoForge client listening at '):
                            origin = line.split(' at ', 1)[1].strip()
                    if origin:
                        break
                    if process.poll() is not None:
                        raise RuntimeError(log.read_text(encoding='utf-8', errors='replace'))
                    time.sleep(.1)
                assert origin, 'Native launcher did not report readiness'
                client = build_opener(ProxyHandler({}), HTTPCookieProcessor(http.cookiejar.CookieJar()))

                def request(path, body=None):
                    data = None if body is None else json.dumps(body).encode('utf-8')
                    headers = {} if body is None else {'Origin': origin, 'Content-Type': 'application/json'}
                    message = Request(origin + path, data=data, headers=headers)
                    try:
                        with client.open(message, timeout=20) as response:
                            return response.status, json.load(response)
                    except HTTPError as error:
                        return error.code, json.load(error)

                assert client.open(origin + '/').status == 200
                assert request('/api/v1/session')[1]['transport'] == 'desktop'
                decks = request('/data/precons.json')[1]
                assert request('/api/v1/matches', {'mode': 'cpu', 'humanDeck': decks[0], 'aiDeck': decks[1]})[0] == 202
                deadline = time.monotonic() + 120
                conceded = False
                setup_verified = False
                while time.monotonic() < deadline:
                    status, snapshot = request('/api/v1/match')
                    assert status == 200, snapshot
                    assert snapshot['status'] != 'error', snapshot.get('error')
                    if snapshot.get('result'):
                        assert setup_verified and conceded and snapshot['status'] == 'finished', snapshot['status']
                        assert any(p.get('lossReason') == 'Conceded' for p in snapshot['result']['participants'])
                        print(json.dumps({'nativeLauncher': 'passed', 'realEngine': 'passed',
                                          'completion': 'authoritative concession', 'platform': os.name}))
                        return
                    players = snapshot.get('players', [])
                    if players:
                        assert len(players) == 2
                        if not setup_verified:
                            assert all(p['life'] == 40 for p in players)
                            setup_verified = True
                        own = snapshot.get('viewerPlayerId')
                        assert all('library' not in p and ('hand' not in p or p['id'] == own) for p in players)
                    prompt = snapshot.get('prompt')
                    if not conceded and snapshot.get('turn', 0) >= 1:
                        payload = dict(kind='concede', matchId=snapshot['matchId'], revision=snapshot['revision'])
                    elif not conceded and prompt:
                        payload = dict(matchId=snapshot['matchId'], revision=snapshot['revision'], promptId=prompt['id'])
                        if prompt['kind'] in ('confirm', 'priority'):
                            payload['kind'] = 'ok'
                        elif prompt['kind'] in ('choices', 'order'):
                            payload.update(kind='choice', choiceIds=[c['id'] for c in prompt['choices'][:max(0, prompt.get('min', 0))]])
                        else:
                            raise RuntimeError('Unexpected game setup prompt ' + prompt['kind'])
                    else:
                        time.sleep(.1)
                        continue
                    code, result = request('/api/v1/action', payload)
                    assert code in (202, 409), result
                    if code == 202 and payload['kind'] == 'concede':
                        conceded = True
                    time.sleep(.1)
                raise TimeoutError('Native engine did not complete the bounded setup/concession probe')
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
    run(parser.parse_args().image.resolve())
