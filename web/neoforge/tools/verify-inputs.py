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
    "schemaVersion": 1, "matchId": "input-test", "revision": 1, "status": "playing",
    "turn": 3, "phase": "MAIN1", "players": [], "stack": [],
    "prompt": {"id": "text-one", "kind": "input", "title": "Choose a number", "message": "Response", "initial": "001", "numeric": True},
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


def prompt(value):
    snapshot["prompt"] = value
    snapshot["revision"] += 1


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
        field = page.locator("#prompt-input")
        expect(field).to_have_value("001")
        expect(field).to_have_attribute("type", "text")
        expect(field).to_have_attribute("inputmode", "numeric")
        field.fill("  0007  ")
        field.evaluate("input => input.setSelectionRange(3, 5, 'backward')")
        snapshot["revision"] += 1
        page.wait_for_timeout(1300)
        expect(field).to_be_focused()
        assert field.evaluate("input => [input.selectionStart, input.selectionEnd, input.selectionDirection]") == [3, 5, "backward"]
        expect(field).to_have_value("  0007  ")
        field.evaluate("input => { window.imeInput = input; input.dispatchEvent(new CompositionEvent('compositionstart', {bubbles:true})); input.value = '文字'; input.dispatchEvent(new InputEvent('input', {bubbles:true,isComposing:true})); }")
        snapshot["revision"] += 1
        page.wait_for_timeout(1300)
        assert page.evaluate("window.imeInput === document.querySelector('#prompt-input')"), "Polling replaced an active IME input"
        field.evaluate("input => input.dispatchEvent(new CompositionEvent('compositionend', {bubbles:true}))")
        expect(field).to_have_value("文字")
        field.fill("  0007  ")
        reject_stale = True
        page.get_by_role("button", name="Confirm response").click()
        expect(page.locator(".flash")).to_contain_text("game moved on")
        expect(field).to_have_value("  0007  ")
        field.press("Enter")
        expect(page.locator("#input-form")).to_have_count(0)
        assert submissions[-1]["kind"] == "input" and submissions[-1]["value"] == "  0007  "

        prompt({"id": "empty-text", "kind": "input", "message": "Empty allowed", "initial": ""})
        expect(field).to_have_value("")
        field.press("Enter")
        expect(page.locator("#input-form")).to_have_count(0)
        assert submissions[-1]["value"] == "", "Empty text became cancellation"
        prompt({"id": "cancel-text", "kind": "input", "message": "Cancel allowed", "initial": "kept"})
        expect(field).to_have_value("kept")
        field.press("Escape")
        expect(page.locator("#input-form")).to_have_count(0)
        assert submissions[-1]["kind"] == "cancel" and "value" not in submissions[-1]

        prompt({"id": "options", "kind": "input", "message": "Select option", "initial": "Second", "options": [
            {"id": "first", "label": "<img src=x onerror=alert(1)>"}, {"id": "second", "label": "Second"}, {"id": "empty", "label": ""},
        ]})
        expect(field).to_have_value("second")
        field.select_option("empty")
        snapshot["revision"] += 1
        page.wait_for_timeout(1300)
        expect(field).to_have_value("empty")
        assert page.locator("#input-form img").count() == 0
        page.get_by_role("button", name="Confirm response").press("Enter")
        expect(page.locator("#input-form")).to_have_count(0)
        assert submissions[-1]["optionId"] == "empty" and "value" not in submissions[-1]
        prompt({"id": "no-options", "kind": "input", "message": "None", "initial": "", "options": []})
        expect(page.get_by_role("button", name="Confirm response")).to_be_disabled()
        expect(field).to_be_disabled()
        page.locator('[data-action="cancel-input"]').click()
        expect(page.locator("#input-form")).to_have_count(0)

        cards = [
            {"id": "a", "label": "<img src=x onerror=alert(1)>", "movable": True},
            {"id": "b", "label": "Face-down card", "movable": False},
            {"id": "c", "label": "Face-down card", "movable": False},
            {"id": "d", "label": "Visible card", "movable": True},
        ]
        prompt({"id": "cards", "kind": "manipulate", "message": "Arrange cards", "cards": cards, "toTop": True, "toBottom": True, "toAnywhere": False})
        source = page.locator("#manipulation-source")
        destination = page.locator("#manipulation-destination")
        expect(page.locator(".manipulation-list li")).to_have_count(4)
        assert source.locator("option").count() == 2
        assert page.locator("#manipulation-form img").count() == 0
        assert page.get_by_role("button", name="Cancel", exact=True).count() == 0
        source.select_option("d")
        assert destination.locator("option").evaluate_all("options => options.map(option => option.value)") == ["0", "1", "3"]
        destination.select_option("0")
        page.get_by_role("button", name="Move card", exact=True).press("Enter")
        expect(page.locator(".manipulation-list li").first).to_contain_text("Visible card")
        source.focus()
        snapshot["revision"] += 1
        page.wait_for_timeout(1300)
        expect(source).to_be_focused()
        expect(source).to_have_value("d")
        expect(page.locator(".manipulation-list li").first).to_contain_text("Visible card")
        page.get_by_role("button", name="Reset order").click()
        expect(page.locator(".manipulation-list li").first).to_contain_text("<img")
        destination.select_option("0")
        page.get_by_role("button", name="Move card", exact=True).click()
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Narrow layout overflows"
        page.get_by_role("button", name="Confirm order").press("Enter")
        expect(page.locator("#manipulation-form")).to_have_count(0)
        assert submissions[-1]["kind"] == "manipulate" and submissions[-1]["cardIds"] == ["d", "a", "b", "c"]

        prompt({"id": "immobile", "kind": "manipulate", "message": "Keep cards", "cards": cards, "toTop": False, "toBottom": False, "toAnywhere": False})
        expect(page.get_by_role("button", name="Move card", exact=True)).to_be_disabled()
        page.get_by_role("button", name="Confirm order").click()
        expect(page.locator("#manipulation-form")).to_have_count(0)
        assert submissions[-1]["cardIds"] == ["a", "b", "c", "d"]
        prompt({"id": "anywhere", "kind": "manipulate", "message": "Insert anywhere", "cards": cards, "toTop": False, "toBottom": False, "toAnywhere": True})
        expect(source).to_be_visible()
        source.select_option("a")
        destination.select_option("1")
        page.get_by_role("button", name="Move card", exact=True).click()
        page.get_by_role("button", name="Confirm order").click()
        expect(page.locator("#manipulation-form")).to_have_count(0)
        assert submissions[-1]["cardIds"] == ["b", "a", "c", "d"]
        assert not errors, errors
        browser.close()
        print("Passed browser text, options, cancellation, IME/caret polling, stale recovery, legal card moves, reset, keyboard, hidden labels and narrow layout checks")
finally:
    server.shutdown()
    server.server_close()
