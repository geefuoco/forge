# Known issues and open delivery checks

## Upstream simulation can report failures as draws

Status: open upstream behavior, avoided by the evaluation design.

At the pinned upstream baseline, `SimulateMatch.simulateSingleMatch` catches `TimeoutException`, catches other exceptions and stack overflow, then calls `setGameOver(GameEndReason.Draw)` in `finally`. `Main.main` also ends command-line modes with `System.exit(0)`. The stock CLI therefore cannot provide the authoritative completion classification for our AI evaluation.

The separate evaluation runner must observe natural `Match.startGame` completion and its actual engine outcome. The supervisor owns timeout and crash classification. A forced cancellation must never gain a competitive winner or a natural-draw result.

## Hosted fork setup

Status: resolved by the user.

The user created [geefuoco/forge](https://github.com/geefuoco/forge). The GitHub connection confirms the repository and owner permissions. The local checkout retains full Card-Forge history, with the user fork as `origin` and Card-Forge as `upstream`. Local credential-manager enumeration was rejected earlier and was not used. The browser implementation and allocation milestone have since merged into `neo-forge`.

## AI quality requires decision review and human play

Status: unverified product requirement.

Successful builds, unit tests, and completed CPU games do not establish strong casual play. Review each requested commander's central decisions and obtain a human playtest before accepting the quality requirement. Record weak decisions with exact fixtures, settings, seed, and position evidence available from the engine.

## Null action revision returns a server error

Status: fixed in the companion action-revision change.

Before the fix, an authenticated `POST /api/v1/action` with a live match and prompt but `"revision": null` returned HTTP 500 instead of a client validation error. The decision remained pending, its command queue stayed empty, and a subsequent valid answer succeeded. Normal browser submissions send numeric revisions.

Independent HTTP probes reproduced the same result with the exact bridge source from base `189fbcc83f81f149c7ef10b401a8e0aef46020f4` and feature `7e50ab041bd68ffb58de3308c5d9502454c02d5d`. The old `MatchSession.submit` called `getAsLong()` before checking the revision's JSON type. Gson threw `UnsupportedOperationException` for JSON null, which reached the generic HTTP 500 handler.

`MatchSession.submit` now validates an optional whole signed-long revision before either normal actions or concession can enqueue a command. Explicit null, non-numeric JSON values, fractions, and values outside the long range return a client error. Normal actions still require the current revision. Concession still permits an omitted revision.

`RevisionTest` exercises the real HTTP server and a pending `ProtocolGuiGame` confirmation. It checks malformed revisions on normal and concession actions, unchanged pending decisions, valid retry, duplicate rejection, and concession without a revision. The regression failed before the fix with `Expected client error for null revision on ok, got HTTP 500`.

## Card selection disappears when both buttons are disabled

Status: fixed in the hosted input lifecycle change.

A local real-engine browser probe stopped on turn 3 during cleanup. The game thread was waiting in `chooseCardsToDiscardToMaximumHandSize`, but the browser snapshot had no prompt. The hosted adapter had treated two disabled buttons as an inactive controller. Forge disables both buttons while the player must first select a card.

The adapter now derives active priority input from the engine's `awaitInput` pump. It exposes the pending card-selection prompt while that pump waits, even when both buttons are disabled. It hides priority input and rejects answers after that pump ends. `HostedTest` covers selection visibility, inactive action rejection, and prompt cleanup. The natural-game probe is rerun through the hosted gateway.

## Closed relay rooms consume admission capacity

Status: fixed in the installed-client verification correction.

Independent verification created and closed two rooms with `max_rooms=2`, then observed zero active rooms and a 503 on the third creation. Retired rooms still occupied the live registry. Closing now removes the live record and retains only a bounded, credential-free tombstone. The new HTTP regression repeats creation and closure beyond the configured capacity and checks that another room is admitted.

## Installed Join dialog does not submit

Status: fixed in the installed-client verification correction.

The first packaged two-client probe opened the guest's Join dialog, but clicking Join did nothing. The handler was attached to the main application element, while the dialog is its sibling. The submission handler now belongs to the dialog's event listener. The packaged real-relay probe checks the complete Host and Join flow.

## Native client CI cannot resolve Java setup action

Status: fixed after the first native workflow attempt.

The Windows and Linux jobs stopped in setup before compilation because the pinned `actions/setup-java` revision did not exist. The workflow now pins the verified commit referenced by the upstream v5 tag. The first failed run is https://github.com/geefuoco/forge/actions/runs/40782022228. Native Windows still requires a completed build and launcher check.

## Windows catalogue generation uses the system code page

Status: fixed after native Windows CI reached catalogue generation.

Forge compiled on Windows, but writing `cards.json` failed with a CP1252 `UnicodeEncodeError` for U+014D. The generator now reads precon lists as UTF-8 and writes all three JSON outputs as UTF-8. A subprocess regression with an ASCII default locale reproduces the failure before the fix and preserves a macron in both catalogue and precon data after the fix. The failed native run is https://github.com/geefuoco/forge/actions/runs/40782419954.
