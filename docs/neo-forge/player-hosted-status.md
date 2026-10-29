# Installed client verification status

Recorded 2026-10-28. The accepted target is [the player-hosted client and relay plan](player-hosted-plan.md). The current published Site is the earlier companion prototype. This change does not deploy a public relay.

## Verified locally

The packaged Linux build `f36843920bfcf35411e3fa72e4daef11d008d25d` launches from an unrelated directory with no external Java, Maven, or Python on PATH. Its bundled Java runtime is version 21.0.12.1. The interface loads the 34,129-card catalogue. An independent browser check saved a starter deck, restarted the executable on a different port, and restored the same deck from its private profile. All 93 recorded runtime dependency hashes matched.

The [combined real-engine report](verification/player-relay-linux.json) records two installed Linux clients against the actual Python relay and Forge. The host and guest joined through the interface, advanced to turn 3, and retained separate private views. A mismatched build could not consume the invitation. Browser reload reconnected the guest to the same engine match. A stale action was rejected. Guest concession produced the authoritative completed result in both clients. The run submitted 35 browser actions and recorded no browser or response errors. This is a conceded game, not a natural-game or competitive-AI result.

The relay HTTP suite passes ten tests. The Java client socket checks pass for local origin boundaries, profile persistence across ports, and lost acknowledgement behavior using a stub relay. Five packaging and catalogue tests pass for release identity, relay URL validation, manifest folding, exact payload contents, and Unicode catalogue output. Existing hosted browser and prompt regressions also pass.

## Saved relay settings follow-up

The [settings probe](verification/relay-settings-linux.json) records a clean Linux package at `7699c919d6bf10ed3cf9475d356a962880a50e46`. Both installed clients saved the relay through Client info. Invalid input retained its draft. The host retained the address after a full executable restart on a new local port. Saving succeeded while session requests were configured to fail. A waiting host could not change the address. Both clients then advanced a real Forge game, reconnected after browser reload, rejected a stale action, and received the authoritative concession result. The run submitted 35 browser actions with no recorded browser or response errors.

The same package passed native launcher, settings save/reset/clear, CPU-game settings lock, and real-engine concession checks without external runtime tools on PATH. The native socket suite passed launch override precedence, malformed saved-file recovery, broken saved-file links, persistence failures, and host and guest settings locks. Existing hosted browser regressions passed. Two independent initial reviewers found configuration-precedence, broken-file-link, and save-result presentation defects. Both correction reviews passed after the fixes. This follow-up's Windows settings checks are defined in the native workflow but have not yet been observed in Windows CI.

## Independent verification

Exactly two initial independent verifiers covered engine and relay boundaries, then browser and packaging behavior. They found a Join dialog event-routing defect and a closed-room capacity leak. Both corrections passed an independent fix-forward round with two reviewers. A separate loopback probe confirmed that closing a room wakes a pending guest action with HTTP 410, releases capacity, and revokes its credentials. The installed-browser reviewer confirmed the corrected dialog forwards exactly one native relay request and displays a relay rejection without losing the form.

The final CI adjustment checks out the exact source head on both platforms so their release identifiers match. The workflow runs on relay, engine, resource, dependency, license, interface, and packaging changes. The [native build record](verification/native-client-build.json) credits an actual successful Windows and Linux run at `e90c42b8cb8ac06d32ac5b96046d857e61c01c5f`. Both packages launched with no external runtime tools, started their bundled Forge engine at Commander life, preserved opponent-hand privacy, and completed an authoritative concession. The [workflow artifacts](https://github.com/geefuoco/forge/actions/runs/40783592421) contain both client archives.

## Remaining release gates

A public HTTPS relay and a genuinely separate-network game remain required before offering the online product as ready. Native Windows and Linux launcher and engine checks have passed. The current Linux bundle supports local CPU play; online hosting requires a configured relay. Windows and Linux clients must use the same release identifier.

Host exit and relay restart end the live room. Durable saves, replay, host migration, broad natural-game coverage, AI quality, and measured rendering performance remain outside this implementation's verified claims. No paid hosting, code-signing certificate, or release publication was purchased or performed.

The relay container also passed a local smoke check as a non-root user with a read-only filesystem, 256 MiB memory limit, and half a CPU. It created a room, admitted its guest, enforced role access, and revoked the room on close. Java was absent. This is a smoke configuration, not a measured capacity claim.
