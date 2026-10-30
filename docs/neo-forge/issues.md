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

## Relay container inherits unreadable source permissions

Status: fixed and checked in the actual non-root container.

A local image built from the managed checkout could not open `server.py` because the source file had mode 0600 and Docker preserved it. The non-root image user could not read the root-owned file. `COPY --chmod=0444` now gives the runtime a deterministic read-only script. The rebuilt container passed health, room creation, guest join, role refusal, and close revocation under the documented resource limits without Java installed.

## Game screen has no card artwork or spatial battlefield

Status: visual correction in progress.

The installed client exposed text buttons in large side-by-side zone panels. Engine and transport checks did not establish the intended game experience. The correction adds a spatial battlefield, visible-card artwork, a separate inspection control, and explicit visual acceptance checks. See `game-experience.md` for the acceptance boundary. Public artwork loading remains distinct from mocked browser layout checks.

## Face-down battlefield cards need a separate visibility gate

Status: fixed in the visible-card projection correction.

Forge's `canBeShownTo` permits a public battlefield card object even when its face is hidden. The projection now also checks `canFaceDownBeShownTo` before reading identity and rules fields. Opponent face-down cards retain only an opaque action ID, the hidden label, tapped state, and a face-down flag. Real CardView regression checks cover an opponent's face-down battlefield card, owner visibility, and the unchanged hidden-hand boundary.

## Browser prompt fixtures still require retired companion pairing

Status: corrected for the installed-client session flow.

Four browser checks attempted to fill `#host-token` and submit the removed pairing dialog. They failed before exercising prompts on the current client. Their fixtures now supply the actual session and profile-library responses, preserve the existing interaction and stale-response assertions, and use the current terminal board selectors. A browser CI job runs all five visual and prompt suites. Artwork is explicitly mocked in these checks.

## Deck builder renderer is shadowed by a prompt editor variable

Status: fixed in the visual table correction.

The local `editor` variable in `render()` hid the deck builder's `editor()` function. The prompt-control variable is now `promptEditor`, so navigating into deck editing calls the intended renderer. This correction preserves the existing prompt focus and composition handling.

## Polling resets scroll inside an open graveyard

Status: corrected; final verification in progress.

Independent browser review opened a 30-card graveyard, scrolled its `.zone` container to 150 pixels, advanced the snapshot revision, and observed a reset to zero. The renderer had preserved only the inner `.zone-cards` offsets. It now preserves both actual containers with distinct stable keys. The visual regression checks a long graveyard across polling as well as retaining the open pocket.

## Owner-visible face-down cards lose their allowed inspection text

Status: corrected; final verification in progress.

Fresh browser review supplied an owner-visible face-down card with authorized name and rules text. The inspector showed its known title but incorrectly replaced its text with an unknown-identity message. Presentation now separates unknown identity from physical face-down artwork state. Known owners retain their projected rules text, while all face-down cards keep cardbacks and make no artwork lookup. The visual regression checks both the allowed text and the absence of an artwork request.
