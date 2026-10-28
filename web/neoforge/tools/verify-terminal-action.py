import asyncio
import copy
import functools
import http.server
import threading
from pathlib import Path

from playwright.async_api import async_playwright, expect

root = Path(__file__).resolve().parents[1] / "dist"
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root)))
threading.Thread(target=server.serve_forever, daemon=True).start()
origin = f"http://127.0.0.1:{server.server_port}"
initial = {
    "schemaVersion": 1, "matchId": "terminal-test", "revision": 10, "status": "playing",
    "turn": 7, "phase": "MAIN1", "players": [], "stack": [],
    "prompt": {"id": "old-prompt", "kind": "confirm", "message": "Original decision", "buttons": [{"id": "ok", "label": "Yes", "enabled": True}]},
}


def snapshot(status="finished", **changes):
    value = {**copy.deepcopy(initial), "revision": 11, "status": status, **changes}
    if status in ("finished", "error"):
        value.pop("prompt", None)
    return value


async def check(browser, name, error="Match is over", refresh=None, poll=None, timing=None, expected=None):
    context = await browser.new_context()
    page = await context.new_page()
    await page.add_init_script("window.setInterval = callback => { window.testPoll = callback; return 1; }; window.clearInterval = () => {};")
    errors = []
    page.on("pageerror", lambda item: errors.append(str(item)))
    poll_started = asyncio.Event()
    recovery_started = asyncio.Event()
    post_started = asyncio.Event()
    release_poll = asyncio.Event()
    release_post = asyncio.Event()
    release_recovery = asyncio.Event()
    actions = []
    gets = 0

    async def api(route):
        nonlocal gets
        request = route.request
        headers = {"Access-Control-Allow-Origin": origin, "Access-Control-Allow-Headers": "Authorization, Content-Type"}
        path = request.url.rsplit("/", 1)[-1]
        if request.method == "OPTIONS":
            await route.fulfill(status=204, headers=headers)
            return
        if path == "status":
            await route.fulfill(json={"schemaVersion": 1, "status": "ready"}, headers=headers)
            return
        if path == "action":
            actions.append(request.post_data_json)
            post_started.set()
            if timing == "before-post":
                await release_post.wait()
            await route.fulfill(status=409 if error != "Server unavailable" else 503, json={"schemaVersion": 1, "error": error}, headers=headers)
            return
        gets += 1
        if gets == 1:
            data = initial
        elif poll is not None and gets == 2:
            poll_started.set()
            await release_poll.wait()
            data = poll
        else:
            recovery_started.set()
            if timing == "during-refresh":
                await release_recovery.wait()
            if refresh == "fail":
                await route.fulfill(status=503, json={"schemaVersion": 1, "error": "Refresh unavailable"}, headers=headers)
                return
            data = refresh if refresh is not None else snapshot()
        await route.fulfill(json=copy.deepcopy(data), headers=headers)

    await page.route("**/data/cards.json", lambda route: route.fulfill(json=[]))
    await page.route("**/api/v1/**", api)
    try:
        await page.goto(origin)
        await page.locator('[data-action="connect"]').click()
        await page.locator("#host-token").fill("test-token")
        await page.locator('[data-action="pair"]').click()
        await page.locator('[data-nav="play"]').click()
        await expect(page.locator(".prompt")).to_contain_text("Original decision")
        if poll is not None:
            await page.evaluate("window.testPoll()")
            await asyncio.wait_for(poll_started.wait(), 3)
        await page.get_by_role("button", name="Yes", exact=True).click()
        await asyncio.wait_for(post_started.wait(), 3)
        if timing == "before-post":
            release_poll.set()
            if poll["status"] in ("finished", "error"):
                await expect(page.locator(".eyebrow", has_text="finished")).to_be_visible()
            else:
                await expect(page.locator(".prompt")).to_contain_text("New decision")
            release_post.set()
        elif timing == "during-refresh":
            await asyncio.wait_for(recovery_started.wait(), 3)
            release_poll.set()
            if poll["status"] in ("finished", "error"):
                await expect(page.locator(".eyebrow", has_text="finished")).to_be_visible()
            else:
                await expect(page.locator(".prompt")).to_contain_text("New decision")
            release_recovery.set()
        if expected == "terminal":
            await expect(page.locator(".eyebrow", has_text="finished")).to_be_visible()
            await expect(page.locator(".prompt")).to_have_count(0)
            await expect(page.locator('[data-action="concede"]')).to_have_count(0)
        elif expected == "error-terminal":
            await expect(page.locator(".panel-head").last).to_contain_text("Engine stopped")
        elif expected == "active":
            await expect(page.locator(".prompt")).to_contain_text("Original decision")
            await expect(page.locator(".flash")).to_contain_text("Action failed: Match is over")
        elif expected == "refresh-failure":
            await expect(page.locator(".flash")).to_contain_text("Could not refresh game: Refresh unavailable")
        elif expected == "unrelated":
            await expect(page.locator(".flash")).to_contain_text("Action failed: Server unavailable")
        elif expected == "stale":
            await expect(page.locator(".flash")).to_contain_text("Review the current prompt")
        elif expected == "newer":
            await expect(page.locator(".prompt")).to_contain_text("New decision")
        await page.wait_for_timeout(100)
        if expected in ("terminal", "error-terminal", "newer"):
            assert await page.locator(".flash").filter(has_text="Action failed").count() == 0, f"{name}: obsolete action produced a failure toast"
            assert await page.locator(".flash").filter(has_text="Review the current prompt").count() == 0, f"{name}: terminal or superseded action requested retry"
        assert len(actions) == 1, f"{name}: action was resubmitted"
        assert not errors, errors
        print(f"Passed {name}")
    finally:
        release_poll.set()
        release_post.set()
        release_recovery.set()
        await context.close()


async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        try:
            await check(browser, "terminal conflict refresh", expected="terminal")
            await check(browser, "stale conflict refreshes terminal", error="Stale revision", expected="terminal")
            await check(browser, "error terminal refresh", refresh=snapshot("error", error="Engine stopped"), expected="error-terminal")
            await check(browser, "active refresh preserves terminal refusal", refresh=snapshot("playing"), expected="active")
            await check(browser, "lower revision terminal cannot replace active", refresh=snapshot(revision=9), expected="active")
            await check(browser, "mismatched match cannot replace current", refresh=snapshot(matchId="other-match"), expected="active")
            await check(browser, "refresh failure remains visible", refresh="fail", expected="refresh-failure")
            await check(browser, "unrelated action failure remains visible", error="Server unavailable", expected="unrelated")
            await check(browser, "stale active refresh keeps retry", error="Stale prompt", refresh=snapshot("playing"), expected="stale")
            newer = snapshot("playing", prompt={**initial["prompt"], "id": "new-prompt", "message": "New decision"})
            other = {**newer, "matchId": "new-match"}
            await check(browser, "newer prompt before POST rejection", poll=newer, timing="before-post", expected="newer")
            await check(browser, "newer match before POST rejection", poll=other, timing="before-post", expected="newer")
            await check(browser, "newer prompt during refresh", poll=newer, timing="during-refresh", expected="newer")
            await check(browser, "newer match during refresh", poll=other, timing="during-refresh", expected="newer")
            await check(browser, "refresh failure cannot toast over newer prompt", refresh="fail", poll=newer, timing="during-refresh", expected="newer")
            terminal_with_prompt = {**snapshot(), "prompt": initial["prompt"]}
            await check(browser, "terminal poll with retained prompt keeps refresh failure visible", refresh="fail", poll=terminal_with_prompt, timing="during-refresh", expected="refresh-failure")
        finally:
            await browser.close()


try:
    asyncio.run(main())
finally:
    server.shutdown()
    server.server_close()
