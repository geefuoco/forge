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
