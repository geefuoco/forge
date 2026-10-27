#!/usr/bin/env python3
"""Exercise the bridge against two Commander decks from a precons JSON file."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("precons", type=Path)
parser.add_argument("--forge-root", type=Path, default=Path(__file__).resolve().parents[3])
args = parser.parse_args()
root = args.forge_root.resolve()
classpath = os.environ["FORGE_BRIDGE_CLASSPATH"]
source = Path(__file__).resolve().parents[1] / "src/forge/browser/Bridge.java"
origin = "https://bridge-test.example"
decks = json.loads(args.precons.read_text())[:2]
assert len(decks) == 2

with tempfile.TemporaryDirectory(prefix="forge-bridge-test-") as temp:
    subprocess.run(["javac", "-cp", classpath, "-d", temp, str(source)], check=True)
    log = open(Path(temp) / "engine.log", "w+")
    process = subprocess.Popen(["java", "-Duser.home=" + temp, "-cp", temp + os.pathsep + classpath,
                                "forge.browser.Bridge", origin], cwd=root / "forge-gui-desktop",
                               stdout=log, stderr=subprocess.STDOUT)
    try:
        token = None
        for _ in range(100):
            time.sleep(.1)
            log.seek(0)
            for line in log:
                if line.startswith("Pairing token: "):
                    token = line.split(": ", 1)[1].strip()
            if token:
                break
            if process.poll() is not None:
                raise AssertionError("Bridge exited during startup")
        assert token, "Bridge did not start"

        def request(path, body=None, auth=token, site=origin):
            headers = {"Origin": site, "Authorization": "Bearer " + auth, "Content-Type": "application/json"}
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request("http://127.0.0.1:8787/api/v1/" + path, data=data, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as error:
                return error.code, json.load(error)

        assert request("status")[1]["engine"] == "Forge"
        assert request("status", auth="bad")[0] == 401
        assert request("status", site="https://other.example")[0] == 403
        code, start = request("matches", {"humanDeck": decks[0], "aiDeck": decks[1]})
        assert code == 202 and start["status"] == "starting"
        last_revision, played_land, answered_choice, ignored_click = None, False, False, False
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            time.sleep(.25)
            snap = request("match")[1]
            assert snap["status"] != "error", snap.get("error")
            prompt = snap.get("prompt")
            if not prompt or snap["revision"] == last_revision:
                continue
            last_revision = snap["revision"]
            human = next((player for player in snap["players"] if player["name"] == "You"), None)
            cpu = next((player for player in snap["players"] if player["name"] == "CPU"), None)
            if cpu:
                assert "hand" not in cpu and "library" not in cpu
            action = {"matchId": snap["matchId"], "revision": snap["revision"], "promptId": prompt["id"]}
            if played_land and answered_choice and human and human["battlefield"]:
                action["kind"] = "concede"
            elif prompt["kind"] == "choices":
                action["kind"] = "choice"
                action["choiceIds"] = [c["id"] for c in prompt["choices"][:prompt["min"]]]
                answered_choice = True
            elif prompt["kind"] == "confirm":
                action["kind"] = "ok"
            elif prompt["kind"] == "priority":
                action["kind"] = "ok"
                if human and not played_land and snap["phase"] == "MAIN1" and snap.get("activePlayerId") == human["id"]:
                    lands = [c for c in human.get("hand", []) if "Land" in c.get("type", "")]
                    if not ignored_click and cpu and cpu["command"]:
                        action.update(kind="card", cardId=cpu["command"][0]["id"])
                        ignored_click = True
                    elif lands:
                        action.update(kind="card", cardId=lands[0]["id"])
                        played_land = True
            else:
                raise AssertionError("Unsupported prompt: " + prompt["kind"])
            stale = dict(action, revision=0)
            assert request("action", stale)[0] == 409
            code, result = request("action", action)
            if code == 409:
                continue
            assert code == 202, result
            if action["kind"] == "concede":
                for _ in range(100):
                    time.sleep(.1)
                    final = request("match")[1]
                    if final["status"] == "finished":
                        assert ignored_click
                        print("Passed: auth, origin, stale actions, ignored click, hidden zones, land, choice, and concession")
                        break
                else:
                    raise AssertionError("Concession did not finish the game")
                break
        else:
            raise AssertionError("Match did not reach a land and blocking choice")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log.close()
