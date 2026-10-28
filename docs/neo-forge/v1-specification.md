# First-release specification draft

Updated 2026-10-28. The user subsequently accepted installed Windows-first and Linux clients with a player-hosted engine and lightweight relay. See [the accepted implementation plan](player-hosted-plan.md). This supersedes the earlier installation-free requirement. Accepted requirements come from the requirements discussion. Items marked proposed remain available for review. Source evidence and detailed questions are in [product discovery](product-discovery.md).

The user accepted the proposed direction and added World Shaper and Multiverse Architect to the initial AI evaluation. Begin with the stock World Shaper precon led by Hearthhull, the Worldseed, and interpret Multiverse Architect as Multiverse Reforged led by Jace, Multiverse Architect. Pinned starting fixtures and their provenance are in [the AI evaluation directory](../../evaluation/ai/README.md).

## Product goal

Build a private Commander application for the user and friends. A user can build or import a deck, play an enjoyable game against a capable CPU or a remote friend, and watch CPU games with useful analysis controls. The playing experience should resemble MTG Arena's clarity and interaction flow, with minimal animation and smooth rendering.

Distribute executable Windows and Linux clients with Java, Forge, resources, and the interface included. The host player's application runs the authoritative engine. A lightweight internet relay connects a friend through outbound HTTPS. No player installs Java or development tools separately. The host must keep the application running.

Launch with two player seats. Support one human against a CPU, two remote humans, and two CPUs with spectators. Expand to four seats after the two-player experience is reliable.

## Accepted scope

| Area | First-release requirement |
| --- | --- |
| Engine | Fork Card-Forge/forge. Retain the rules, AI, required shared controllers, and resources. |
| Client | Installed Windows-first and Linux application bundles. The executable opens the bundled interface in the system browser. |
| Engine hosting | One player runs the authoritative Java Forge engine through the installed client. The relay runs no engine. Preserve upstream rules and AI. |
| Rules | Standard Commander rules, including 40 life and the normal setup differences for starting player count. |
| Deckbuilding | Create and edit decks using all engine-supported cards without collection ownership restrictions. |
| Interchange | Manually import through clipboard paste or file upload, and export decks. |
| CPU decks | Select a user's deck or a curated deck, or choose a random option. |
| CPU quality | Strong casual opponents across varied decks. Establish actual ability early. |
| Automation | Automatic mana payment with manual override, configurable priority stops, and repeated-trigger shortcuts. |
| Remote play | Friends paste one-use invitations into installed clients. The host keeps the application running. Both clients use outbound relay connections without VPN, tunnels, or router configuration. |
| Spectating | Watch CPU games, inspect all hands, pause, change speed, and step. |
| Recovery | Reconnect to the same live host after browser or network interruptions. Durable host-owned saves and restore across application restarts follow in milestone 3. |
| Replay | Record games for later review. |
| Rendering | At least 60 FPS on an ordinary integrated-graphics laptop under agreed representative conditions. |
| CPU waiting | Initial targets of about one second for ordinary decisions and up to five seconds for difficult decisions. |
| Hosting cost | Prefer a free lightweight relay host. No Java engine runs in the cloud. Evaluate the relay runtime, capacity, and cost before selecting a paid service. |
| Upstream | Repeatable, isolated updates for card changes and bug fixes, with provenance and preservation checks. |

## Proposed defaults for the remaining details

These defaults complete the draft without requiring the user to select every control or file format now.

- Begin deck interchange with plain-text card lists and Forge `.dck` files. Preserve card quantities and commander assignments. Resolve unknown entries visibly. Other interchange formats can follow evidence from actual imports.
- Build a deck editor with commander selection, name and rules-text search, color identity, type and mana-value filters, an editable list, legality feedback, and autosave. Allow incomplete drafts to be saved while clearly identifying what prevents play.
- Keep automatic payment visible and overridable before committing the spell. Preserve a way to hold priority and make explicit choices. Do not automate a new optional decision without an agreed policy.
- Select random CPU decks from the combined eligible user and curated library. Clearly distinguish card support from CPU competence. Validate a small initial curated suite before describing a deck as tested.
- Show public information to spectators of human games by default. Omniscient inspection is accepted for CPU-only games. Keep each viewer's permissions explicit in the server and replay data.
- Request manual saves whenever desired, then commit a consistent checkpoint at a supported game boundary. Autosave at tested consistent boundaries. Never claim an incomplete save is usable. Determine through the engine spike whether pending choices and RNG state can be restored faithfully.
- On a human disconnect, preserve the game and allow the same seat to reconnect. Do not silently replace the human with a CPU or reveal private information.
- For live spectating, define a step as the next supported meaningful decision or priority boundary and label it accurately. Validate whether action-level stepping is feasible before promising that behavior.
- Begin replay with open, play, pause, speed, and forward-step controls. Backward seeking and resuming play from a replay are not assumed. A recording and a resumable save remain separate artifacts.
- Use Chrome and Edge at 1080p as a proposed initial performance setup. Select and record a real integrated-graphics reference machine. Test card inspection, targeting, crowded boards, trigger bursts, replay speed, and CPU thinking. Record frame-time distributions and visible stalls as well as average FPS.
- Treat CPU timing as a responsiveness goal rather than a rule that forfeits the CPU's turn. Investigate overruns and expose a thinking state. Specify any search-budget change only after observing its effect on move quality.
- Keep the host application authoritative for rules, CPU decisions, and saves. Authenticate relay roles and enforce per-viewer projection at the host. The installed application includes its runtime. The host remains running throughout play. Trusted-friend hosting does not prevent host cheating.
- Bound relay rooms, request bodies, pending commands, memory, idle time, and total lifetime. Bind each room to one host process and release identifier. Evaluate public relay hosting independently of client runtime packaging.
- Review upstream update candidates on demand initially. The repeatable process must exist before adding any unattended schedule. Preserve an active game's engine and resource version until it ends.

## Early milestone must establish CPU quality

The first technical milestone evaluates Forge before substantial custom UI work. A running CPU game alone does not establish that the opponent is worthwhile.

1. Establish a reproducible upstream build at a pinned commit. Record resource versions, runtime, AI profile, and search configuration.
2. Select a small varied suite of legal Commander decks. Include the requested World Shaper and Jace, Multiverse Architect decks, alongside combat, tokens, spells, and graveyard coverage. Start the requested decks from the stock precon fixtures in the evaluation directory. Verify deck legality and implementation support before drawing conclusions about the AI.
3. Run repeatable two-seat CPU games with recorded seeds and seat swaps. Record completion, crashes, decision stalls, unsupported interactions, and reasons for abnormal results. Do not treat a simulation timeout as a completed competitive game.
4. Review saved positions for basic competence. Check legal payment and targets, attacks and blocks, responses to threats, use of commander abilities, and the ability to execute each deck's central plan. Preserve concrete failures as reproducible cases.
5. Compare relevant upstream AI configurations with the same positions, decks, seeds, and time budgets. Match the configuration intended for the application. Do not infer human-level strength from self-play win rates.
6. Provide a runnable baseline for the user to play against. Collect whether the games are challenging and enjoyable and retain the decisions that undermine that experience.
7. Deliver an evidence-based verdict. Describe which decks and decisions work, the observed weaknesses, and whether targeted AI work is needed. Do not silently narrow the requested deck support or claim strong casual play before that verdict.

This milestone can produce a finding that Forge's current AI is insufficient. That finding requires revisiting the AI plan before investing in a polished interface. No AI-quality or timing result exists yet.

## Feasibility checks for the rest of the product

- Prove an engine-to-browser human prompt and answer without launching the desktop application. Handle input waiting, cancellation, and a complete two-seat game.
- Demonstrate a complete game through installed clients with bundled Java and Forge. Start the packaged executable without Java, Maven, or Python on PATH. Local interface requests use loopback, and the relay connections use outbound HTTPS.
- Demonstrate an authenticated invitation between installed clients on separate networks. Check seat ownership, reconnect, version mismatch refusal, and viewer permissions without tunnels, VPN, or router configuration.
- Save a game, stop the host application, restart it, and continue from host-owned saved state. Cover a representative stack and pending choice or document the supported boundary precisely.
- Record and reopen a replay. Confirm its visibility rules and playback controls independently of save restoration.
- Build realistic board mockups and compare their usability before fixing the frontend framework and layout. Use the agreed 60 FPS requirement throughout implementation.

## Delivery order

| Milestone | Reviewable result |
| --- | --- |
| 0. Engine and AI | Reproducible build, representative decks, decision evidence, a user-playable baseline, and an honest quality verdict. |
| 1. Browser protocol feasibility | One complete browser-driven game and validated input and visibility boundaries. The local companion can prove this development milestone. |
| 2. Installed clients and player-hosted relay | Package Windows and Linux clients with bundled runtimes. Connect two clients through a lightweight relay. Prove authoritative synchronization, one-use invites, private seat views, version checks, duplicate rejection, and live-host reconnect. Verify public separate-network play before calling remote service ready. |
| 3. Durable state | Host-owned save and restore survive application restarts. Replay works independently of resumable saves. |
| 4. Core experience | Website deck management, accounts and access, game sessions, and the complete two-seat interface, with Arena-inspired interaction and measured responsiveness. |
| 5. Release checks | All agreed user stories pass in native Windows and Linux bundles without separately installed runtimes. Two networks connect through the deployed relay. Host-loss limits and update compatibility are explicit. |
| Later. Four seats | Additional multiplayer rules, layouts, AI behavior, and network cases pass before four-seat support is declared ready. |

Use exactly two independent initial verifier agents for pstack swarm verification, assigning all required checks between them. Fix-forward rounds use at most two and cover the changed scope. The earlier research explorers stopped at an account usage limit; their partial reports are not independent implementation verification.

## Current state

The user fork and private Site now contain a Commander deck workspace and browser client backed by a local Forge companion. Real protocol, browser-to-Java HTTP, private-zone, allocation, text, and card-order checks have passed. A natural-game probe exposed an informational reveal blocker, which now has a dedicated acknowledgement flow. The current source also projects authoritative completion results and validates malformed action revisions. See the tracked browser status for exact verification limits.

The earlier installation-free requirement was replaced on 2026-10-28 after discussing Sites runtime limits. Installed clients and a lightweight relay are now the target. The previous hosted-engine service remains a prototype and is not the active deployment plan.

One passive stock-deck game has completed naturally through the browser. Hosted engine deployment, authenticated remote invites, durable save and restore, replay, the AI-quality verdict, measured rendering performance, and native Windows startup remain unverified. This draft remains the first-release target rather than a claim that those milestones are complete.
