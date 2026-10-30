import os
import copy
import functools
import http.server
import json
from pathlib import Path
import threading

from playwright.sync_api import sync_playwright, expect

root = Path(__file__).resolve().parents[1] / "dist"
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
origin = f"http://127.0.0.1:{server.server_port}"
snapshot = {
    "schemaVersion": 1, "matchId": "allocation-test", "revision": 1,
    "status": "playing", "turn": 4, "phase": "COMBAT_DAMAGE", "players": [], "stack": [],
    "prompt": {
        "id": "combat-one", "kind": "allocation", "allocationKind": "combat",
        "message": "Assign combat damage from Attacker", "total": 7,
        "amountLabel": "damage", "ordered": True, "divideFreely": False, "maySkip": True,
        "targets": [
            {"id": "first", "label": "First blocker", "min": 0, "max": 7, "lethal": 2, "defender": False},
            {"id": "second", "label": "Second blocker", "min": 0, "max": 7, "lethal": 3, "defender": False},
            {"id": "defender", "label": "Defender", "min": 0, "max": 7, "lethal": 0, "defender": True},
        ],
    },
}
submissions = []
reject_stale = False


def api(route):
    global reject_stale
    request = route.request
    headers = {"Access-Control-Allow-Origin": origin, "Access-Control-Allow-Headers": "Authorization, Content-Type"}
    path = request.url.rsplit("/", 1)[-1]
    if request.method == "OPTIONS":
        route.fulfill(status=204, headers=headers)
        return
    if path == "session":
        data = {"schemaVersion": 1, "authenticated": True, "canCreate": True, "seat": 0, "hasMatch": True, "transport": "desktop"}
    elif path == "library":
        data = {"schemaVersion": 1, "exists": True, "decks": []}
    elif path == "action":
        if reject_stale:
            reject_stale = False
            snapshot["revision"] += 1
            route.fulfill(status=409, json={"schemaVersion": 1, "error": "Stale revision"}, headers=headers)
            return
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
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/data/cards.json", lambda route: route.fulfill(json=[]))
        page.route("**/api/v1/**", api)
        page.route("https://api.scryfall.com/**", lambda route: route.fulfill(status=404, json={"object": "error"}))
        page.goto(origin)
        page.locator('[data-nav="play"]').click()
        inputs = page.locator('[name="allocation"]')
        expect(inputs).to_have_count(3)
        confirm = page.get_by_role("button", name="Confirm assignment")
        expect(confirm).to_be_disabled()
        inputs.nth(0).fill("1")
        inputs.nth(1).fill("4")
        inputs.nth(2).fill("2")
        expect(page.locator("#allocation-error")).to_contain_text("earlier blockers")
        expect(confirm).to_be_disabled()
        inputs.nth(0).fill("2")
        inputs.nth(1).fill("3")
        expect(confirm).to_be_enabled()
        inputs.nth(2).focus()
        snapshot["revision"] += 1
        page.wait_for_timeout(1300)
        expect(inputs.nth(0)).to_have_value("2")
        expect(inputs.nth(1)).to_have_value("3")
        expect(inputs.nth(2)).to_have_value("2")
        expect(inputs.nth(2)).to_be_focused()
        page.get_by_role("button", name="Reset", exact=True).click()
        expect(inputs.nth(0)).to_have_value("0")
        expect(confirm).to_be_disabled()
        for index, amount in enumerate([2, 3, 2]):
            inputs.nth(index).fill(str(amount))
        reject_stale = True
        confirm.click()
        expect(page.locator(".flash")).to_contain_text("game moved on")
        expect(inputs.nth(2)).to_have_value("2")
        inputs.nth(2).press("Enter")
        expect(page.locator("#allocation-form")).to_have_count(0)
        assert submissions[-1]["kind"] == "allocation"
        assert submissions[-1]["allocations"] == [
            {"id": "first", "amount": 2}, {"id": "second", "amount": 3}, {"id": "defender", "amount": 2},
        ]
        snapshot["prompt"] = {
            "id": "generic-two", "kind": "allocation", "allocationKind": "generic",
            "message": "Assign counters", "total": 4, "amountLabel": "counters",
            "ordered": False, "divideFreely": False, "maySkip": False,
            "targets": [
                {"id": "one", "label": "Face-down card", "min": 1, "max": 2, "lethal": 0, "defender": False},
                {"id": "two", "label": "<img src=x onerror=alert(1)>", "min": 1, "max": 4, "lethal": 0, "defender": False},
            ],
        }
        snapshot["revision"] += 1
        expect(inputs).to_have_count(2)
        expect(inputs.nth(0)).to_have_value("1")
        expect(page.get_by_role("button", name="Assign another creature first")).to_have_count(0)
        inputs.nth(0).fill("3")
        inputs.nth(1).fill("1")
        expect(confirm).to_be_disabled()
        inputs.nth(0).fill("0")
        expect(confirm).to_be_disabled()
        inputs.nth(0).fill("1.5")
        expect(confirm).to_be_disabled()
        inputs.nth(0).fill("")
        expect(confirm).to_be_disabled()
        inputs.nth(0).fill("2")
        inputs.nth(1).fill("2")
        expect(confirm).to_be_enabled()
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Allocation editor overflows a narrow screen"
        assert page.locator(".allocation-target img").count() == 0, "Target label was rendered as HTML"
        confirm.click()
        expect(page.locator("#allocation-form")).to_have_count(0)
        snapshot["prompt"] = {
            "id": "skip-three", "kind": "allocation", "allocationKind": "combat", "message": "Assign damage",
            "total": 1, "amountLabel": "damage", "ordered": False, "divideFreely": False, "maySkip": True,
            "targets": [{"id": "only", "label": "Blocker", "min": 0, "max": 1, "lethal": 2, "defender": False}],
        }
        snapshot["revision"] += 1
        page.get_by_role("button", name="Assign another creature first").click()
        expect(page.locator("#allocation-form")).to_have_count(0)
        assert submissions[-1]["kind"] == "skip"
        assert not errors, errors
        browser.close()
        print("Passed browser allocation editing, rules feedback, polling retention, reset, stale recovery, keyboard submission, target bounds, narrow layout, escaped labels, and skip")
finally:
    server.shutdown()
    server.server_close()
