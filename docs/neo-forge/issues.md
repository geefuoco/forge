# Known issues and open delivery checks

## Upstream simulation can report failures as draws

Status: open upstream behavior, avoided by the evaluation design.

At the pinned upstream baseline, `SimulateMatch.simulateSingleMatch` catches `TimeoutException`, catches other exceptions and stack overflow, then calls `setGameOver(GameEndReason.Draw)` in `finally`. `Main.main` also ends command-line modes with `System.exit(0)`. The stock CLI therefore cannot provide the authoritative completion classification for our AI evaluation.

The separate evaluation runner must observe natural `Match.startGame` completion and its actual engine outcome. The supervisor owns timeout and crash classification. A forced cancellation must never gain a competitive winner or a natural-draw result.

## Hosted fork setup

Status: resolved by the user.

The user created [geefuoco/forge](https://github.com/geefuoco/forge) and pushed the `neo-forge` branch. It contains the evaluation runner and Jace targeting fix.

## Jace conversion rejected a disposable token

Status: fixed in `ba236861d3957005bb04f53e7722f2ea278e5872`.

The focused decision test reproduced Jace's exile-and-reveal ability returning `TargetingFailed` for a legal disposable token. The card script now uses the existing Polymorph AI hint. The regression covers selecting the token and declining to sacrifice a valuable creature. This fixes those positions. It does not establish overall deck quality.

## Custom desktop launcher omitted upstream Java options

Status: fixed in the baseline launcher.

The prior cloud session reproduced XStream gauntlet deserialization failing before the main frame appeared. The classpath launcher omitted the module-access options in Forge's desktop POM. The launcher now reads those options for the desktop JVM. Headless evaluation keeps its existing arguments. The [baseline report](ai-baseline-report.md) records verification and remaining checks.

## AI quality requires decision review and human play

Status: unverified product requirement.

Successful builds, unit tests, and completed CPU games do not establish strong casual play. Review each requested commander's central decisions and obtain a human playtest before accepting the quality requirement. Record weak decisions with exact fixtures, settings, seed, and position evidence available from the engine.
