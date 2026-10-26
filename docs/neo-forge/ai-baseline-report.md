# Commander engine baseline

Date: 2026-10-26.

This change resumes Milestone 0 after the Jace targeting fix. The pushed `neo-forge` branch contained the evaluation runner and both requested stock decks. The previous cloud session reported successful games and desktop startup, but its uncommitted fixes and evidence did not survive into this workspace. This report uses a fresh run of the restored code.

The restored runner selects native Java executable names and applies optional Maven settings to version checks and builds. The desktop launch reads Forge's module-access options from the pinned POM. The cleanup test recognizes stopped Linux zombies and still rejects a live process. Git preserves the original deck bytes. The [development guide](development.md) explains toolchain setup and commands.

## Verified checks

- All 16 runner tests pass. The independent portability reviewer also ran all 16 tests successfully.
- Both inherited Jace regression cases pass without failures, errors, or skips. The AI converts a disposable token and keeps a valuable creature in those positions.
- A fresh `clean package` build passes at engine baseline `ba236861d3957005bb04f53e7722f2ea278e5872`. The packaged JAR SHA-256 is `30719336b1254c10f6a02806807cad59740f59e48e6627ff4ad8a9c4f4999eb0`.
- Engine validation loads all 100 cards in each deck and accepts both Commander setups. Its writable profile, cache, decks, and logs resolve inside the validation directory.
- Both fixture files match their pinned upstream bytes and manifest SHA-256 values. Repeated setup preserves existing cache directories and links.

The checkout HEAD during these checks is `c4e4610809b8c0fc50f07e3b01d8d031217200aa`, with the restored source hashes recorded separately. Java is OpenJDK 21.0.12.1 and Maven is 3.9.11. The build is pinned by inputs. Its JAR hash records this build, rather than promising identical archive bytes across builds.

## Stock game suite

The plan uses the Default AI profile, `desktop-max` Monte Carlo search, seed `11025`, a five-second AI setting, a 180-second startup deadline, and a 120-second game deadline. Cheats and filtered hands are disabled. The AI setting is not a measured decision-latency guarantee.

The six attempts cover four distinct ordered matchup-and-seed inputs. Each mirror runs twice with identical deck order and seed. This is execution coverage, not six independent samples of opponent strength. A fixed seed does not establish deterministic replay under timed Monte Carlo search.

All six attempts reached natural wins with `AllOpponentsLost` as the engine end reason. No attempts timed out, crashed, or were rejected.

Last turn is the engine's individual-turn counter. The game log's outcome message divides that count by two and rounds up, so an engine count of 21 appears there as turn 11.

| Attempt | Seat 0 | Seat 1 | Winner seat | Last turn |
| --- | --- | --- | --- | --- |
| 001 | World Shaper | World Shaper | 0 | 21 |
| 002 | World Shaper | World Shaper | 0 | 21 |
| 003 | World Shaper | Multiverse Reforged | 1 | 16 |
| 004 | Multiverse Reforged | World Shaper | 0 | 21 |
| 005 | Multiverse Reforged | Multiverse Reforged | 1 | 14 |
| 006 | Multiverse Reforged | Multiverse Reforged | 1 | 14 |

The [saved evidence](../../evaluation/ai/reports/2026-10-26-stock-smoke.json) contains the exact build and source hashes, validation, game requests, matching setup and terminal receipts, and result summary. The [selected decision excerpts](../../evaluation/ai/reports/2026-10-26-decision-excerpts.txt) retain source line numbers. The [raw evidence archive](../../evaluation/ai/reports/2026-10-26-stock-smoke-raw.zip) preserves complete game logs, staged decks, receipts, and verification records. Its entries retain their repository-relative paths. The JSON records the archive hash and individual log hashes. The excerpts do not contain every decision.

The logs have no matches for `Exception`, `ERROR`, or `Error:`. They still contain upstream card metadata and spell-ability diagnostics. This text scan is not a claim that every interaction is correct.

## Decision evidence and limits

The focused Jace regression proves two target-selection decisions. It does not establish good draw choices, hand-bottoming, planeswalker protection, or combat-tax decisions throughout a game.

Cross-deck game 003 also records Jace targeting and exiling a Phyrexian Mite token. That shows the repaired conversion path executing in a full game.

The first World Shaper mirror records Hearthhull gaining station counters and activating the land-sacrifice draw ability. Those events show execution. Their tactical value, station threshold choices, additional land plays, and land recovery still need position review.

## Desktop launch

`node scripts/neo-forge.mjs play` reached a visible `Forge: 2.0.16-SNAPSHOT-10.26` main frame under Xvfb. The matching startup receipt identified a live Java process. The [screenshot](../../evaluation/ai/reports/2026-10-26-desktop.png) shows the main application and its first-start card-image download prompt. This command used the same runner source and packaged JAR as the game suite.

This verifies startup. Human gameplay and remote browser access from the cloud remain untested. Use the [development guide](development.md) to launch the baseline on a graphical machine.

## Remaining Milestone 0 work

1. Review representative positions for targeting, payment, combat, threat responses, and both commanders' central plans. Preserve concrete mistakes as regression cases.
2. Add combat, tokens, spells, and graveyard coverage beyond the two requested stock decks.
3. Compare relevant AI configurations using the same positions and budgets. Measure actual decision latency separately.
4. Run human games against the baseline and collect whether the opponent is challenging and enjoyable.
5. Deliver a quality verdict before investing in the custom interface.

The browser client, remote invite route, durable saves, replay, and rendering targets remain later feasibility work in the [specification](v1-specification.md). No Site has been created or deployed.
