# Installed client verification status

Recorded 2026-10-28. The accepted target is [the player-hosted client and relay plan](player-hosted-plan.md). The current published Site is the earlier companion prototype. This change does not deploy a public relay.

## Verified locally

The packaged Linux build `f36843920bfcf35411e3fa72e4daef11d008d25d` launches from an unrelated directory with no external Java, Maven, or Python on PATH. Its bundled Java runtime is version 21.0.12.1. The interface loads the 34,129-card catalogue. An independent browser check saved a starter deck, restarted the executable on a different port, and restored the same deck from its private profile. All 93 recorded runtime dependency hashes matched.

The [combined real-engine report](verification/player-relay-linux.json) records two installed Linux clients against the actual Python relay and Forge. The host and guest joined through the interface, advanced to turn 3, and retained separate private views. A mismatched build could not consume the invitation. Browser reload reconnected the guest to the same engine match. A stale action was rejected. Guest concession produced the authoritative completed result in both clients. The run submitted 35 browser actions and recorded no browser or response errors. This is a conceded game, not a natural-game or competitive-AI result.

The relay HTTP suite passes ten tests. The Java client socket checks pass for local origin boundaries, profile persistence across ports, and lost acknowledgement behavior using a stub relay. Four packaging tests pass for release identity, relay URL validation, manifest folding, and exact payload contents. Existing hosted browser and prompt regressions also pass.

## Independent verification

Exactly two initial independent verifiers covered engine and relay boundaries, then browser and packaging behavior. They found a Join dialog event-routing defect and a closed-room capacity leak. Both corrections passed an independent fix-forward round with two reviewers. A separate loopback probe confirmed that closing a room wakes a pending guest action with HTTP 410, releases capacity, and revokes its credentials. The installed-browser reviewer confirmed the corrected dialog forwards exactly one native relay request and displays a relay rejection without losing the form.

The final CI adjustment checks out the exact source head on both platforms so their release identifiers match. The workflow runs on relay, engine, resource, dependency, license, interface, and packaging changes. Native Windows execution must be credited from an actual Windows run, never from the workflow definition alone.

## Remaining release gates

A public HTTPS relay, a genuinely separate-network game, and native Windows launch remain required before offering the online product as ready. The current Linux bundle supports local CPU play; online hosting requires a configured relay. Windows and Linux clients must use the same release identifier.

Host exit and relay restart end the live room. Durable saves, replay, host migration, broad natural-game coverage, AI quality, and measured rendering performance remain outside this implementation's verified claims. No paid hosting, code-signing certificate, or release publication was purchased or performed.
