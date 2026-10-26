# Commander AI evaluation fixtures

The user requested World Shaper and Multiverse Architect in addition to the proposed combat, token, spells, and graveyard evaluation coverage.

Use the stock World Shaper precon led by Hearthhull, the Worldseed. Interpret Multiverse Architect as the stock Multiverse Reforged precon led by Jace, Multiverse Architect. This interpretation is the starting default, rather than a request for a custom upgraded list.

The `.dck` files are byte-identical copies from Card-Forge/forge at the commit recorded in [deck-manifest.json](deck-manifest.json). That manifest records the original paths, SHA-256 hashes, official decklist sources, and verification status. The copied files retain the upstream repository's GPL-3.0 licensing. Keep stock fixtures unchanged; create separately named variants for future upgrades.

## Fixtures

| Fixture | Commander | Official source |
| --- | --- | --- |
| [World Shaper](decks/world-shaper.dck) | Hearthhull, the Worldseed | [Wizards decklist](https://magic.wizards.com/en/news/announcements/edge-of-eternities-commander-decklists) |
| [Multiverse Reforged](decks/multiverse-reforged.dck) | Jace, Multiverse Architect | [Wizards decklist](https://magic.wizards.com/en/news/announcements/reality-fracture-multiverse-reforged-commander-decklist) |

A structural check found 99 main-deck cards and one expected commander in each file. Engine validation loads all 100 cards and accepts both Commander setups. The copies match the pinned upstream bytes. The [baseline report](../../docs/neo-forge/ai-baseline-report.md) records execution evidence and remaining AI-quality checks. Validation does not establish complete card support or competent decisions.

## Proposed decision cases

These cases come from inspection of the pinned commander scripts. They are hypotheses about useful test coverage, not passed tests or claims about AI ability.

For World Shaper, observe station activation against the value of leaving creatures available for combat. Check reaching useful station thresholds, paying and activating the land-sacrifice draw ability, making the additional land play, recovering sacrificed lands, and handling the resulting triggers. Preserve positions where the AI misses the deck's central plan or gives away a defensible board.

For Multiverse Reforged, observe the choice between Jace's draw ability and the exile-and-reveal ability. Include positions with a disposable token and a valuable creature so the target choice matters. Check hand-bottoming decisions, protecting the planeswalker, and the opponent's choice to pay the combat tax. Verify each interaction's rules implementation before classifying a bad result as an AI mistake.

Run both decks in each seat, including mirror games and cross-deck games. Add the other archetypes before making a broad quality claim. Record seed, profile, search settings, engine version, end reason, decision timing, and any saved failure position. Review decisions and human playtests alongside self-play outcomes. A timeout classified by the simulation as a draw is not a normally completed game.
