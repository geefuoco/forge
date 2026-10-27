# NeoForge browser test version

The private Site project is `appgprj_6adfc16750848191bc9c8772a2008c1b`, slug `neoforge`. Reuse this identity. The Site source repository contains the deployable static application and its generated catalogue. The Java engine stays on the user's PC.

## Working in this version

- Browser-local deck library, draft editing, catalogue search and filters, mana curve, commander selection, import review, `.dck` export, and sample-hand draws.
- 34,129 unique first-face card names from the pinned Forge scripts. Both World Shaper and Multiverse Reforged stock lists resolve to 100 cards.
- Authenticated loopback companion, authoritative Forge Commander deck validation, real game setup, priority, card and player actions, confirmations, list choices, ordering, and concession.
- Browser-controlled combat damage and generic amounts, with companion validation of totals, target limits, blocker order, trample, deathtouch, planeswalker loyalty, and explicit deferral when allowed.
- Text input, listed options, and complete card-list ordering. The companion preserves exact strings and original card objects, validates allowed moves, and conceals hidden card names. Browser controls retain edits during polling and stale-revision recovery.
- Explicit viewer snapshots omit the CPU hand and library contents. The launcher uses a separate persistent profile and pairing tokens remain in page memory.
- The Help dialog provides a companion source download and an origin-specific launch command. Extract it into a built Forge checkout.

## Verified and limited

Independent browser verification covered deck workflows, file and paste round trips, reload persistence, storage failures, keyboard dialogs, filters, desktop and narrow layouts, mock prompt controls, and stale-action recovery. Independent Java verification covered auth, origin, host, stale actions, typed choices, ordering, private zones, real Commander play, and concession. Review found and fixed commander copy loss, desktop preference overwrite, and concession without an active prompt.

A separate browser-to-Java run paired through the actual website controls, started at 40 life, played a human land, answered a blocking choice, and conceded. This was a local HTTP preview with a real engine. The published private origin reaching the user's own PC remains a user-machine check and depends on browser local-network permission.

Allocation checks call the real `ProtocolGuiGame` combat and generic methods and verify the maps returned by the companion. They cover illegal payloads, combat rules, hidden labels, target identity, zero entries, stale actions, and allowed deferral. The Chromium allocation checks use mock companion responses and cover editing, polling retention, reset, stale recovery, keyboard submission, and a narrow layout. These checks do not establish that a complete game finishes.

Independent verification on 2026-10-27 also exercised actual Chromium against the companion over HTTP, then checked damage assignment and application through Forge's human controller and combat engine. Legacy trample, modern blocker splitting, and deathtouch produced the expected blocker damage and defender life. Generic shield allocation preserved the original engine targets, and concession cancelled a pending allocation. The normal match smoke check passed with both requested stock precons. Desktop and narrow browser checks also covered starter imports, deck edits, and reload persistence.

The interrupted launcher fix is complete. Maven now runs from the checkout root with the desktop POM selected explicitly, which resolves the reported relative settings-file error. Three launcher regression tests and real Maven module validation passed. Fresh-cache dependency resolution and native Windows startup remain unverified. Restart the companion from the updated checkout or extract the updated companion source download before using allocation prompts.

The text and card-list protocol checks pass through real `ProtocolGuiGame` calls. They cover exact strings, empty responses, cancellation, numeric hints, duplicate option labels, malformed answers, stale prompts, original card identities, hidden labels, every movement-flag combination, and empty lists. The endpoint validator also matches 201,452 comparisons against exhaustive desktop legal-move exploration for lists of zero through six entries. Chromium checks use mock companion responses and pass text, options, cancellation, caret and IME retention during polling, stale recovery, legal card moves, reset, keyboard controls, escaped labels, and narrow layouts. The existing protocol allocation checks and Chromium allocation checks still pass. These checks do not establish a complete natural game. Restart the updated companion before using the new dialogs.

Independent verification also paired Chromium with the real Java companion over HTTP and submitted text, empty text, cancellation, listed options, and a complete card order. Java assertions checked the exact returned values and original card references. Keyboard controls, narrow layouts, and newer prompts surviving delayed responses passed. A separate engine reviewer passed real HTTP boundary checks and stock-precon match smoke tests in both seat orders. Those matches exercised land play, blocking choices, private zones, stale actions, and concession. They were intentionally conceded, so natural game completion remains unverified. The checks used existing built Forge classes with freshly compiled bridge source. They do not establish a clean full-engine rebuild or native Windows startup.

Review reproduced an inherited malformed-action issue at both the base and feature revisions. A JSON-null action revision returns HTTP 500 while leaving the decision usable. The follow-up is recorded in `docs/neo-forge/issues.md` in the Forge repository.

## Remaining work

1. Verify a complete natural browser-driven game and handle any remaining required GUI decisions. Text input, card-list manipulation, combat damage, and generic amounts now have browser controls. Sideboarding and GUI-base dialogs remain outside this milestone. The bridge reports unsupported protocol decisions explicitly instead of choosing for the human.
2. Verify the published Site on the user's PC, including browser local-network permission and reconnect after a closed browser tab.
3. Continue the existing first-release milestones for remote invites, durable game save and restore, replay, stronger AI assessment, and measured rendering performance. No 60 FPS measurement is claimed for this version.
4. Improve the game-board layout and richer card presentation after the remaining decisions work.

GitHub Issues is disabled for this fork. This tracked list and the implementation PR preserve the outstanding work.
