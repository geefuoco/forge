# Commander application discovery

Updated 2026-10-28. This is a working requirements record, not an approved implementation specification.

## Confirmed requirements

The application is dedicated to MTG Commander and uses a fork of [Card-Forge/forge](https://github.com/Card-Forge/forge).

- Open the hosted website and play without installing Forge, Java, a desktop client, or a local companion. Host the Java Forge engine on server infrastructure. This requirement, confirmed on 2026-10-28, supersedes the original local-engine deployment model.
- Serve the user and their friends as a private application.
- Launch with two-player Commander. Expand to four seats after the two-player experience works well.
- Allow remote friends to join the same game, with CPUs filling empty player seats.
- Let remote friends join through a browser invite. Avoid requiring invitees to install a VPN or configure a router. The connection mechanism still needs a feasibility check.
- Support creating decks and importing and exporting decks.
- Import decks manually through clipboard paste and file upload. The user has no current deck service or stored deck library to integrate.
- Allow every engine-supported card in deckbuilding without collection ownership restrictions.
- Offer imported user decks and a curated deck library for CPU seats. The user can select the CPU's deck or choose a random option.
- Target desktop and laptop browsers for the first release. Phone and tablet play is outside launch scope.
- Use standard Commander rules for the two-player release and eventual four-player games, including the rules that depend on starting player count.
- Provide Arena-style interaction automation: automatic mana payment with manual override, configurable priority stops, and shortcuts for repeated triggers.
- Support playing Commander against CPU opponents.
- Support watching games and CPU versus CPU games.
- Provide live spectator pause, speed changes, stepping, and all-hand inspection for CPU games.
- Support saving and resuming games and reviewing recorded replays.
- Provide server-owned autosave and manual saves that survive browser closure, disconnects, and hosted engine restarts.
- Target strong casual CPU play with varied decks.
- Treat CPU quality as an early feasibility requirement. The user needs an opponent worth playing against, not merely a game that completes.
- Choose the frontend technology for the quality of the experience.
- Use an Arena-inspired visual direction with minimal animation. Balance appearance with responsiveness and target at least 60 FPS on the agreed supported hardware and representative gameplay scenes.
- Use an ordinary laptop with integrated graphics as the initial hardware class for the 60 FPS requirement. A concrete reference machine still needs selection.
- Use initial CPU decision targets of roughly one second for ordinary decisions and up to five seconds for difficult decisions. These are accepted targets to test, not measured capability.
- Prefer free hosting and connectivity for this hobby project. Evaluate the user's ChatGPT Sites access as a candidate for hosting the web interface.
- Establish a repeatable process for upstream card changes and bug fixes.
- Discuss the user stories and agree on acceptance criteria before product implementation.

The initial table supports one human against one CPU, two remote humans, or two CPUs with a spectator. Four-player Commander is a later milestone, not a first-release acceptance requirement. The target engine runs on hosted infrastructure. No player must keep a host PC running or configure a local tunnel. Browser invites connect to authenticated hosted sessions. Provider choice, Java runtime support, match isolation, persistence, transport, resource limits, and cost need a feasibility proof. The local companion remains useful for development only.

## Questions currently open

1. Finalize the remaining archetype fixtures alongside the user-requested World Shaper and Jace, Multiverse Architect decks. Use the stock precons initially unless the user supplies a different list.
2. Which remaining defaults in the first-release draft need adjustment? Exact deck file formats, save boundaries, replay navigation, and spectator permissions for human games are still proposed.
3. Which concrete integrated-graphics laptop and browser should become the reproducible performance reference? The hardware class is accepted, but a device and stress fixtures have not been selected.

The user initially selected four seats, then explicitly reduced launch scope to two players. All other answers from that round remain in scope. The exact behavior of saving, resuming, replaying, and spectator stepping still needs acceptance criteria.

The user selected the same Commander rules across player counts and endorsed the proposed automation as similar to MTG Arena. This establishes the interaction direction, not a complete Arena visual specification. Clipboard and file imports are confirmed; exact file formats and export formats still need definition.

All supported cards are available without ownership checks. CPU deck selection includes imported and curated decks, plus a random option. The random deck pool, compatibility filtering, and any power matching remain to be defined. Desktop and laptop play is sufficient at launch.

The user accepted autosave and manual saves that survive restarts. The 2026-10-28 hosted-engine requirement moves this persistence to server-owned storage. Browser invitations are the desired remote joining experience. The user prefers MTG Arena's style but wants minimal animation and at least 60 FPS. This is a performance requirement, not a measured result or a framework choice.

The latest round accepts an ordinary integrated-graphics laptop as the initial hardware class, prefers free infrastructure for this hobby project, and accepts roughly one-second ordinary and five-second difficult CPU decisions as initial targets. The user raised ChatGPT Sites as a possible hosting option and emphasized that the CPU must be good enough to play against.

The user accepted the proposed direction and requested World Shaper and Multiverse Architect as additional evaluation decks. Official decklists identify World Shaper's face commander as Hearthhull, the Worldseed, and Multiverse Reforged's face commander as Jace, Multiverse Architect. Both stock decklists and commander scripts are present at the pinned Forge commit. Byte-preserved deck fixtures and provenance are recorded in [the AI evaluation directory](../../evaluation/ai/README.md). File structure and card counts were checked; runtime behavior and AI quality remain unverified.

## ChatGPT Sites feasibility check

The connected Sites listing returned no existing sites on 2026-10-25. That read does not establish remaining creation quota or prove a deployment would succeed. No Site was created or deployed.

The [official Sites documentation](https://learn.chatgpt.com/docs/sites) supports HTTP, HTTPS, and WebSockets. The [official app-hosting overview](https://learn.chatgpt.com/use-cases/build-and-deploy-internal-apps) describes static sites and full-stack JavaScript or TypeScript applications. The installed Sites skill describes its hosted server runtime as Cloudflare Workers. These sources support considering Sites for the web interface and connection service, not assuming it is a general Java process host.

The provisional split remains a local Java engine plus a browser interface. A Sites-hosted UI still needs a verified route to the local engine. An invite must route to the game host, not to the visitor's own localhost. A relay or outbound host connection is a hypothesis to test. Validate connection lifecycle, access, reconnect, usage limits, and lack of mandatory new hosting cost before selecting this option.

## Performance acceptance, to finish defining

The required rendering target is at least 60 FPS on the agreed baseline device, browser, display resolution, and refresh rate. A frame at 60 FPS has a time budget of about 16.7 milliseconds. No runtime measurement exists yet.

Test active board interactions and transitions, rather than inferring smoothness from an idle screen. The scenario set must include a crowded battlefield with tokens, counters, attachments, and a stack; card inspection and targeting; trigger bursts; replay at the maximum supported speed; and CPU computation while the user inspects the board. Record frame-time distributions and visible stalls as well as average FPS. Agree on the stress-scene size and treatment of occasional hitches before accepting results.

UI rendering, local action feedback, network round trips, and CPU decision time are separate acceptance categories. Meeting the rendering target does not establish that turns, saves, joins, or reconnects are responsive. CPU search must not make the browser unresponsive. Keep animation brief and permit it to be reduced or disabled. The exact animation settings remain a design proposal.

## Rules baseline

Use the normal Commander rules, including 40 starting life, rather than a dedicated duel ruleset. Apply player-count-dependent setup from the [official Comprehensive Rules effective September 25, 2026](https://media.wizards.com/2026/downloads/MagicCompRules%2020260925.txt), verified through the [official rules page](https://magic.wizards.com/en/rules) during this session.

- Rule 103.8a makes the starting player skip their first draw step in a two-player game.
- Rule 103.8c keeps every player's first draw step in the eventual free-for-all multiplayer game.
- Rule 103.5c gives a free first mulligan in multiplayer games. Ordinary two-player Commander does not receive that multiplayer exception.
- Rule 903.7 sets Commander starting life to 40.

The draw-step difference is correct but is not the only difference between two-player and multiplayer setup. No house-rule exception has been requested. Keep rules based on the game's starting player count, rather than changing setup rules when players are eliminated.

## Remaining grilling topics

Discuss these after the current questions rather than presenting every decision at once.

- Define a satisfying session and identify the frustrations in existing Commander applications that this application must solve.
- Specify the accepted Arena-style automation in detail, including priority stops, manual mana override, trigger ordering, target selection, and optional actions.
- Specify the Arena-inspired visual direction, minimum laptop screen size, keyboard support, text scaling, and minimal animation details. Visual direction and the 60 FPS target are confirmed.
- Specify clipboard, uploaded-file, and export formats. URL import is not an initial requirement.
- Define the deck editor's initial search, filtering, commander selection, legality feedback, autosave, organization, and revision needs.
- Define the random CPU deck pool and acceptable handling of unsupported cards or unreliable deck strategies. Both imported and curated deck selection are confirmed.
- Define what strong casual play means through representative decks, difficult decisions, and acceptable waiting time.
- Define save points, autosave frequency, pending-choice recovery, reconnect policy, and save compatibility across engine updates. Durable autosave and manual saves are confirmed.
- Define spectator information rules for human games separately from omniscient CPU-only analysis.
- Define supported Commander variants, partner arrangements, legality overrides, bans, and house rules.
- Define installation, startup, offline assets, updates, and deck backup expectations.
- Choose update cadence and how the user reviews update candidates.

## Source baseline and evidence

Research is pinned to upstream commit [`e5a0f8156da70ffc7866f923bed371c0111707cd`](https://github.com/Card-Forge/forge/commit/e5a0f8156da70ffc7866f923bed371c0111707cd). The public GitHub API resolved this commit from `master` during this session. Selected raw files were then downloaded at that exact commit. Local evidence is under `.audit/forge-source/`; `.audit/upstream-source-files.txt` lists the files.

This is source inspection. No Forge build, complete game, browser integration, AI evaluation, or independent implementation verification has run.

| Finding | Evidence | Consequence |
| --- | --- | --- |
| `forge-ai` directly depends on `forge-core` and `forge-game`. | [AI POM](https://github.com/Card-Forge/forge/blob/e5a0f8156da70ffc7866f923bed371c0111707cd/forge-ai/pom.xml) | Core and AI alone are insufficient. Retain the rules engine in `forge-game`. |
| `forge-gui` depends on all three engine modules and holds shared match orchestration and human input code. | [Shared GUI POM](https://github.com/Card-Forge/forge/blob/e5a0f8156da70ffc7866f923bed371c0111707cd/forge-gui/pom.xml), [HostedMatch](https://github.com/Card-Forge/forge/blob/e5a0f8156da70ffc7866f923bed371c0111707cd/forge-gui/src/main/java/forge/gamemodes/match/HostedMatch.java), [PlayerControllerHuman](https://github.com/Card-Forge/forge/blob/e5a0f8156da70ffc7866f923bed371c0111707cd/forge-gui/src/main/java/forge/player/PlayerControllerHuman.java) | Removing the GUI modules by name would remove useful behavior. Establish the actual browser integration boundary first. |
| Card scripts, tokens, editions, format data, and AI profiles live below `forge-gui/res`. | [ForgeConstants](https://github.com/Card-Forge/forge/blob/e5a0f8156da70ffc7866f923bed371c0111707cd/forge-gui/src/main/java/forge/localinstance/properties/ForgeConstants.java) | A package containing only Java engine source would miss required data. Card updates must account for related resources. |
| The lobby distinguishes AI and human slots, validates Commander decks, and constructs registered players for variants. Its general slot limit is eight. | [GameLobby](https://github.com/Card-Forge/forge/blob/e5a0f8156da70ffc7866f923bed371c0111707cd/forge-gui/src/main/java/forge/gamemodes/match/GameLobby.java) | Launch with two seats and design for a later four-seat milestone. Upstream capacity does not establish a usable layout or verified multiplayer behavior. |
| An all-AI match can register a spectator, and playback exposes pause, resume, single-step, and speed control. Pausing is handled at player-priority events. | [HostedMatch](https://github.com/Card-Forge/forge/blob/e5a0f8156da70ffc7866f923bed371c0111707cd/forge-gui/src/main/java/forge/gamemodes/match/HostedMatch.java), [FControlGamePlayback](https://github.com/Card-Forge/forge/blob/e5a0f8156da70ffc7866f923bed371c0111707cd/forge-gui/src/main/java/forge/gui/control/FControlGamePlayback.java) | Reuse candidates exist. A product requirement for stepping each action may need different behavior from upstream stepping between priority events. |
| A command-line simulation path accepts multiple decks, Commander format, seeds, AI profiles, and timeouts. It explicitly applies optional Monte Carlo settings rather than assuming GUI preferences. | [SimulateMatch](https://github.com/Card-Forge/forge/blob/e5a0f8156da70ffc7866f923bed371c0111707cd/forge-gui-desktop/src/main/java/forge/view/SimulateMatch.java) | Use this as a starting point for reproducible game checks. Match the actual application AI configuration before comparing quality or timing. |
| Deck recognition handles several text layouts and Commander sections. Serialization writes Forge deck sections and metadata. | [DeckRecognizer](https://github.com/Card-Forge/forge/blob/e5a0f8156da70ffc7866f923bed371c0111707cd/forge-core/src/main/java/forge/deck/DeckRecognizer.java), [DeckSerializer](https://github.com/Card-Forge/forge/blob/e5a0f8156da70ffc7866f923bed371c0111707cd/forge-core/src/main/java/forge/deck/io/DeckSerializer.java) | Reuse parsing and deck models where practical. This does not establish URL import support for any particular service. |
| `IGuiGame` includes synchronous choices, ordered lists, reveal prompts, selections, and waiting for input. `IGameController` handles player actions. | [IGuiGame](https://github.com/Card-Forge/forge/blob/e5a0f8156da70ffc7866f923bed371c0111707cd/forge-gui/src/main/java/forge/gui/interfaces/IGuiGame.java), [IGameController](https://github.com/Card-Forge/forge/blob/e5a0f8156da70ffc7866f923bed371c0111707cd/forge-gui/src/main/java/forge/interfaces/IGameController.java) | A browser adapter must carry prompts and answers while the engine waits. Sending board snapshots alone is insufficient. |
| Replay playback consumes recorded spectator messages through the existing client decoding path. | [ReplayPlayer](https://github.com/Card-Forge/forge/blob/e5a0f8156da70ffc7866f923bed371c0111707cd/forge-gui/src/main/java/forge/gamemodes/net/client/ReplayPlayer.java) | Replay is a reuse candidate. A recorded spectator stream does not establish that a game can be restored and continued. |
| Upstream CI runs Maven tests under a virtual display. The shared GUI POM selects `*Should.java` tests. | [Test workflow](https://github.com/Card-Forge/forge/blob/e5a0f8156da70ffc7866f923bed371c0111707cd/.github/workflows/test-build.yaml), [Shared GUI POM](https://github.com/Card-Forge/forge/blob/e5a0f8156da70ffc7866f923bed371c0111707cd/forge-gui/pom.xml) | Verify which tests a chosen Maven command discovers. A successful command alone does not prove that intended regression tests ran. |
| The parent build targets Java 17 and the repository declares GPL 3. | [Parent POM](https://github.com/Card-Forge/forge/blob/e5a0f8156da70ffc7866f923bed371c0111707cd/pom.xml) | Retain the upstream notices and record the baseline toolchain. Packaging requirements remain open. |

## Architecture recommendation, provisional

Retain the complete upstream Git history and source layout. Keep application code in clearly separate paths. Build and package only the modules and resources needed by this application. Avoid deleting unused upstream modes during initial setup.

| Approach | Benefit | Cost | Current judgment |
| --- | --- | --- | --- |
| Keep the full fork and add a local Java host plus browser UI. | Preserves upstream ancestry, resource paths, tests, and shared controllers. | Must bridge Forge input and state into a browser protocol. Shared initialization may bring additional dependencies. | Preferred starting point for a feasibility spike. |
| Extract core, game, AI, and selected shared code into a new source tree. | Gives direct control over the package. | Makes resource loading, dependency tracking, and upstream patch application our responsibility. | Reconsider only if evidence shows that retained shared code prevents a clean host. |
| Adapt the existing desktop UI. | Reuses its input and display integration. | Does not satisfy the confirmed browser UI requirement on its own. | Useful as a reference and baseline, rather than the selected product UI. |

Historical prototype proposal, superseded for deployment on 2026-10-28. The target runtime is now a browser connected to a hosted Java service. The original proposal was a browser connected to a local Java service. The service owns the game, legal decisions, CPU turns, and persistence. It sends each viewer the state and prompts that viewer is allowed to receive, then validates returned actions. Framework and transport choices remain open.

The first feasibility spike should demonstrate initialization without the desktop application, one browser-driven human choice, a complete two-seat CPU game, and spectator pause and resume. Confirm the adapter handles threads, pending prompts, and clean match cancellation. A subsequent check must demonstrate two remote human clients playing through the same authoritative host. Keep seats and per-viewer permissions explicit in the model so four-seat support can be added later. These are proposed checks, not completed work.

The Experience First principle shaped this recommendation. Choose the engine boundary and frontend through the playing experience and a narrow working prototype before investing in a broad interface.

## Upstream update process, proposed

Prefer regular upstream merges if application code stays separate and the retained engine remains close to upstream. Use selective cherry-picks for an urgent fix or a justified incompatible change. Avoid making selective import of individual card files the default.

1. Record an accepted upstream SHA, the fork SHA, and the packaged resource version. Keep the running release pinned while reviewing updates.
2. Fetch upstream and produce a candidate report since the accepted SHA. Classify engine, AI, card scripts, tokens, editions, formats, shared controllers, tests, build changes, and unrelated product modes. Track dependencies and reasons for omissions.
3. Assemble the candidate in an isolated integration worktree. Keep the user-facing release and user data untouched.
4. Integrate complete changes and their dependencies. A card script can rely on a new engine operation, AI logic, prompt behavior, token data, or a format update.
5. Run the relevant upstream build and tests. Prove that intended tests were discovered. Run application regressions and real browser behavior checks.
6. Check representative Commander decks, human input, CPU-only completion, hidden information, spectators, cancellation, reload or recovery behavior, and deck round trips. Preserve the accepted UI and product behavior explicitly.
7. For pstack swarm verification, use exactly two independent verifiers per initial round. Divide engine, rules, AI, and update checks from browser, deck, spectator, and preservation checks. Both report the exact candidate revision and evidence. Fix-forward rounds cover changed scope with at most two verifiers.
8. Publish a reviewable update report and promote only a passing candidate. Preserve the prior release and a coherent user-data backup for rollback. Do not replace the engine or card data during an active game.

This is a proposed workflow. There is no fork, update command, scheduled automation, or verified updater yet.

## Acceptance criteria to negotiate

| User story | Proposed observable acceptance |
| --- | --- |
| Build a Commander deck. | Select the commander arrangement, find cards, edit quantities, see actionable legality feedback, and reload without losing the saved deck. |
| Choose CPU decks. | Select a saved imported deck or a curated deck for a CPU seat, or request a random deck from the agreed eligible pool. Surface compatibility problems before starting rather than silently substituting cards or decks. |
| Use a laptop browser. | Complete deck editing and gameplay with readable cards and accessible controls at the agreed minimum laptop viewport. Phone and tablet layouts are not launch acceptance requirements. |
| Import and export a deck. | Each agreed format round-trips card identities, counts, and commander assignment. Unknown or unsupported entries remain visible for correction rather than disappearing. Decide which printing and metadata details must survive. |
| Use standard Commander rules. | Two-player games use 40 life and skip the starting player's first draw step. The standard multiplayer free-first-mulligan exception does not apply to a two-player start. Add multiplayer setup checks when expanding to four seats. |
| Play with Arena-style automation. | Preview automatic mana payment and allow manual override. Respect configured priority stops and repeated-trigger shortcuts. Define defaults and cancellation behavior before accepting these controls. |
| Start a game against CPUs. | Choose the table and decks, complete mulligans, cast and respond to spells, attack and block, and finish a representative game through the browser. |
| Play a remote friend. | A friend opens a browser invite from a separate machine and joins an authenticated hosted two-seat game without installing software or relying on a player host PC. Complete the agreed gameplay scenarios without requiring invitees to install a VPN or configure a router. Each client receives only its permitted information. Host setup, access controls, and reconnect behavior still need definition. |
| Read a complex board. | Identify the active player, priority, stack order, targets, relevant zones, commander damage, and the next required action at the agreed screen size. Validate with a realistic crowded board. |
| Watch a CPU game. | Start a two-CPU game with no human seats, inspect all hands, change speed, pause and resume, and leave without a stranded game thread. Define what a step advances before accepting stepping. |
| Save and resume a game. | Automatically save an unfinished game and support manual saves. After browser closure or a hosted engine restart, load and continue a server-owned saved game. Define supported save points, treatment of pending choices, autosave frequency, and engine-version compatibility before accepting this feature. |
| Keep gameplay smooth. | Meet the required 60 FPS rendering target on the agreed baseline setup during representative interaction and stress scenes, including while the CPU computes. Assess visible stalls and frame times as well as average FPS. Record CPU wait and network delay separately. |
| Review a replay. | Open a recorded game and review its sequence using the agreed playback controls. Define visibility, navigation, and storage expectations separately from resumable game saves. |
| Play against strong casual CPUs. | Agree on representative decks and decisions, then record decision quality, game completion, and actual waiting times under the application's AI configuration. No strength claim is established by a profile name or a running game. |
| Update the engine. | Apply an upstream candidate in isolation and pass both source-level checks and the same browser user stories. Keep decks, settings, and the previous release recoverable. |

The 60 FPS rendering target is confirmed. Baseline hardware and stress conditions, other responsiveness budgets, supported deck formats, the minimum representative deck set, and the definition of acceptable AI play are still open. They must be settled before these become release criteria.

## Next steps

Finish the requirements grilling, write the agreed first-release specification, and select the feasibility checks. Then establish the fork and implement the minimum engine-to-browser prototype. Product implementation has not started.

The consolidated [first-release draft](v1-specification.md) records accepted scope separately from proposed remaining defaults. Its first milestone evaluates engine feasibility and CPU quality before substantial UI work.
