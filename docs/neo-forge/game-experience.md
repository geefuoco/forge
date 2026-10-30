# Commander game experience

The installed client's game screen must be evaluated as a playing interface. Successful engine requests alone do not establish that experience.

## Current implementation target

Use a spatial table with the opponent above the local player, the local hand along the bottom, and a separate decision and card inspection rail. Collapse workspace navigation during a game. Keep life, turn, phase, public zones, and the current decision visible.

Render printed card images for visible cards. Preserve names, rules text, and actions when artwork is unavailable. Artwork loads asynchronously from Scryfall and its image CDN. Lookup traffic must be bounded and deduplicated. Never request images for hidden cards or use stack ability descriptions as card identities.

Clicking a card sends the existing authoritative Forge action. Hover, keyboard focus, and the separate inspection button inspect without submitting an action. Do not describe a card as playable or a legal target unless Forge supplies that information. Preserve the existing choice, text, reveal, ordering, and allocation editors.

Current power and toughness, counters, tapped state, and combat flags must come from Forge. Printed artwork is not authoritative for modified statistics. A face-down card's hidden identity must not enter the snapshot or artwork requests.

## Acceptance evidence

- A real packaged application reaches the opening hand, accepts mulligan and priority decisions, plays a land, and displays the authoritative result.
- Existing prompt and stale-response regressions still pass.
- Desktop, crowded battlefield, and narrow-window checks show readable controls without horizontal page overflow.
- Inspection does not submit game actions. Actual card activation retains the authoritative card and prompt identifiers.
- Hidden opponent hands and unseen face-down cards produce no artwork identity requests.
- Provider success, missing artwork, timeouts, repeated rendering, and retry behavior have distinct checks.
- Screenshots identify whether the engine and artwork provider were real or mocked. Mock artwork cannot establish successful public artwork loading.

This change does not establish MTGA feature parity, measured 60 FPS, broad Commander interaction coverage, AI quality, save recovery, or public separate-network play. Those remain explicit project acceptance work.
