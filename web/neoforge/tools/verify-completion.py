import os
import copy
import functools
import http.server
import threading
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

root = Path(__file__).resolve().parents[1] / "dist"
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root)))
threading.Thread(target=server.serve_forever, daemon=True).start()
origin = f"http://127.0.0.1:{server.server_port}"
snapshot = {
    "schemaVersion": 1, "matchId": "completion-test", "revision": 1, "status": "playing",
    "turn": 13, "phase": "MAIN1", "players": [], "stack": [],
    "prompt": {"id": "reveal-one", "kind": "reveal", "message": "Transformed cards", "items": ["Akroma, Angel of Fury", "Face-down card", "<img src=x onerror=alert(1)>"], "buttons": [{"id": "ok", "label": "Continue", "enabled": True}]},
}
submissions = []


def api(route):
    request = route.request
    headers = {"Access-Control-Allow-Origin": origin, "Access-Control-Allow-Headers": "Authorization, Content-Type"}
    if request.method == "OPTIONS":
        route.fulfill(status=204, headers=headers)
        return
    path = request.url.rsplit("/", 1)[-1]
    if path == "session":
        data = {"schemaVersion": 1, "authenticated": True, "canCreate": True, "seat": 0, "hasMatch": True, "transport": "desktop"}
    elif path == "library":
        data = {"schemaVersion": 1, "exists": True, "decks": []}
    elif path == "action":
        submissions.append(request.post_data_json)
        snapshot.pop("prompt", None)
        snapshot["revision"] += 1
        data = {"schemaVersion": 1, "accepted": True}
    else:
        data = copy.deepcopy(snapshot)
    route.fulfill(json=data, headers=headers)


try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH", "/usr/bin/chromium"), headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/data/cards.json", lambda route: route.fulfill(json=[]))
        page.route("**/api/v1/**", api)
        page.route("https://api.scryfall.com/**", lambda route: route.fulfill(status=404, json={"object": "error"}))
        page.goto(origin)
        expect(page.get_by_role("heading", name="Transformed cards")).to_be_visible()
        expect(page.locator(".revealed-items li")).to_have_count(3)
        expect(page.locator('.prompt input, .prompt [data-card], .prompt img')).to_have_count(0)
        expect(page.get_by_role("button", name="Submit selection")).to_have_count(0)
        assert not submissions, "Reveal advanced without acknowledgement"
        snapshot["revision"] += 1
        page.wait_for_timeout(1300)
        assert not submissions, "Polling acknowledged reveal"
        page.get_by_role("button", name="Continue", exact=True).focus()
        page.keyboard.press("Enter")
        expect(page.locator(".revealed-items")).to_have_count(0)
        assert len(submissions) == 1 and submissions[0]["kind"] == "ok"
        assert "choiceIds" not in submissions[0]
        snapshot["players"] = [{"id": "human", "name": "You", "life": 40, "handCount": 1, "libraryCount": 80, "hand": [{"id": "card", "name": "Known card"}], "battlefield": []}, {"id": "cpu", "name": "<img src=x onerror=alert(1)>", "life": 40, "handCount": 3, "libraryCount": 70, "battlefield": [{"id": "opponent-card", "name": "Public card"}]}]
        snapshot["status"] = "finished"
        snapshot["prompt"] = {"id": "stale", "kind": "confirm", "message": "Old prompt"}
        snapshot["result"] = {"kind": "decided", "endReason": "WinsGameSpellEffect", "turns": 13, "participants": [{"name": "You", "outcome": "won"}, {"name": "<img src=x onerror=alert(1)>", "outcome": "lost", "lossReason": "Milled"}]}
        snapshot["revision"] += 1
        expect(page.get_by_role("heading", name="You won", exact=True)).to_be_visible()
        expect(page.locator(".game-result")).to_contain_text("Drew from an empty library")
        expect(page.locator(".game-result img")).to_have_count(0)
        expect(page.locator(".game-result")).to_contain_text("<img src=x onerror=alert(1)>")
        expect(page.locator('[data-player], [data-card], [data-prompt-button], [data-action="concede"]')).to_have_count(0)
        expect(page.get_by_role("heading", name="Old prompt")).to_have_count(0)
        expect(page.locator('[data-visible-card="card"]')).to_contain_text("Known card")
        expect(page.locator('[data-visible-card="opponent-card"]')).to_contain_text("Public card")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Narrow result overflows"
        snapshot["result"]["participants"][0] = {"name": "You", "outcome": "lost", "lossReason": "LifeReachedZero"}
        snapshot["result"]["participants"][1] = {"name": "CPU", "outcome": "won"}
        snapshot["revision"] += 1
        expect(page.get_by_role("heading", name="You lost", exact=True)).to_be_visible()
        expect(page.locator(".game-result")).to_contain_text("Life reached zero")
        snapshot["result"]["participants"][0]["lossReason"] = "Conceded"
        snapshot["revision"] += 1
        expect(page.get_by_role("heading", name="You conceded", exact=True)).to_be_visible()
        snapshot["result"]["kind"] = "draw"
        snapshot["result"]["participants"] = [{"name": "You", "outcome": "draw", "lossReason": "IntentionalDraw"}, {"name": "CPU", "outcome": "lost", "lossReason": "<unknown reason>"}]
        snapshot["revision"] += 1
        expect(page.get_by_role("heading", name="Draw", exact=True)).to_be_visible()
        expect(page.locator(".game-result")).to_contain_text("Agreed draw")
        expect(page.locator(".game-result")).not_to_contain_text("<unknown reason>")
        snapshot.pop("result")
        snapshot["revision"] += 1
        expect(page.get_by_role("heading", name="Game finished", exact=True)).to_be_visible()
        expect(page.locator(".game-result")).to_contain_text("Result unavailable")
        expect(page.get_by_role("heading", name="Draw", exact=True)).to_have_count(0)
        snapshot["status"] = "error"
        snapshot["error"] = "Unsupported decision"
        snapshot["revision"] += 1
        expect(page.locator(".game-result")).to_have_count(0)
        expect(page.locator('[role="alert"]')).to_contain_text("Unsupported decision")
        expect(page.locator('[data-player], [data-card], [data-prompt-button], [data-action="concede"]')).to_have_count(0)
        snapshot["status"] = "playing"
        snapshot.pop("error")
        snapshot["matchId"] = "fresh-match"
        snapshot["prompt"] = {"id": "new-reveal", "kind": "reveal", "message": "New match", "items": ["Card"]}
        snapshot["revision"] += 1
        expect(page.get_by_role("heading", name="New match", exact=True)).to_be_visible()
        expect(page.locator(".game-result")).to_have_count(0)
        expect(page.locator('[data-action="concede"]')).to_have_count(1)
        assert len(submissions) == 1, "Terminal rendering submitted an action"
        assert not errors, errors
        browser.close()
    print("Passed browser reveals, authoritative result labels, terminal controls, privacy, polling and keyboard checks")
finally:
    server.shutdown()
    server.server_close()
