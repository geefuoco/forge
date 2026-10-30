# Player-hosted client and relay plan

Accepted direction, 2026-10-28. The user replaced the installation-free, cloud-hosted Java requirement with distributable Windows and Linux clients. Windows is the first release platform. The host player's computer runs Forge. A lightweight internet service relays the guest's actions and permitted game view. Players need no router changes, VPN, separately installed Java, or development tools.

## What players use

A player extracts the application bundle and starts NeoForge. The executable includes Java, Forge, card resources, and the existing deck and game interface. It opens that interface in the system browser on a loopback address. The application itself stays running. An embedded browser window is not required for the first build.

The host selects both decks and creates a friend lobby. The guest starts the same release of NeoForge, selects **Join a friend**, and pastes the invitation. Both applications make outbound HTTPS requests to the relay. The host's machine never opens an internet-facing game port. Local CPU games need no relay.

The installed client stores decks in its private user profile. Browser storage alone is insufficient because each launch can choose a different loopback port.

The installed interface also saves the relay address in that profile. The same binary can connect to an operator's relay without a new package. A launch option overrides the saved address, which overrides the packaged default. An explicit empty saved address disables hosting. Reset restores the packaged default. The client prevents changes after starting or joining a game, because the current application owns that game until exit.

## One engine decides the game

The host's `Bridge.MatchSession` owns the game. Forge retains all rules and CPU decisions. Each human has a separate `SeatView`, controller, prompt, handles, and snapshot. The host reads seat zero locally. Only seat one's projection goes to the relay. The guest runs no second simulation that can diverge.

Actions identify the engine match, prompt, and exact revision. The host validates them before dispatch. The relay assigns no rules outcome. A command identifier, the relay's pending mailbox, and the host's result cache prevent a repeated delivery from applying an action twice. Unknown results require a refresh rather than automatic resubmission.

The relay binds its room to one release identifier and protocol version. A mismatched client cannot consume the invitation. Invitations work once and produce a distinct guest credential. Host and guest capabilities authorize different endpoints. Tokens stay in application memory and do not enter browser responses or server logs.

## Reconnect and trust limits

A network drop preserves the same host engine and pending prompt. The guest reconnects with its existing credential and receives a complete current snapshot. Browser reloads reconnect to the local application. No disconnected player becomes a CPU automatically.

The host must keep the application and computer running. Host exit ends the room. Relay restart loses its transient room records. Neither event restores a game in this milestone. Save and restore, host migration, and recovery after application restart require a later durable-state milestone.

The host controls the authoritative process and can inspect both players' cards. This design is for trusted friends and does not prevent host cheating. The relay receives the guest projection and is trusted to protect it. Other remote players receive no credentials or private state for the room.

## Design decision

| Candidate | Consequence | Decision |
| --- | --- | --- |
| Relay native Forge multiplayer bytes | Reuses Netty and native reconnect, but changes online play to the native UI and requires authentication and serialization audits. | Rejected for this interface. |
| Relay typed actions and seat snapshots | Reuses the current browser board, prompt editors, Java rules, and private projections. | Selected. |

Two source explorations compared these designs. Their cross-judge selected the semantic relay. Release pinning and native platform checks carry over from the native-client alternative. Raw Java serialization is not exposed to remote guests.

## Delivery sequence and checks

1. Define the room protocol and ownership before implementation. Keep room, credential, snapshot, and command state bounded.
2. Implement the small relay independently of Forge. Check role isolation, one-use invites, mismatch rejection without token consumption, stale actions, duplicate delivery, timeout, host lease, and expiry.
3. Implement the Java local application over the existing Bridge. Check loopback Host and Origin boundaries, same-process reconnect, private projections, and command-result retention. Keep installed resources read-only and profiles writable.
4. Package Windows and Linux application images with a bundled runtime and exact dependencies. Launch Linux from an unrelated directory with Java, Maven, and Python absent from PATH. Native Windows launch is a separate required check.
5. Run two installed clients against the relay and a real Forge game. Check guest joins, both hands, actions, revision rejection, browser reload, and authoritative completion. A local loopback test does not establish separate-network play.
6. Assign exactly two independent initial verifiers. One covers relay, client, and engine boundaries. The other covers browser behavior, packaging, documentation, and the decision trail. Apply corrections and rerun affected checks before marking ready.
7. Publish a reviewable change and distribute artifacts only with their tested platform and limits stated. Deploy a relay only to an accessible host, then prove a separate-network game. Never label an undeployed relay as online service.

## Throughput checkpoint

The protocol and architecture comparison block implementation. Relay, Java client, and native packaging have separate owners and worktrees. The host owns engine mutation, the relay owns room and message records, and the browser owns only user edits. The lead owns frontend integration, specification changes, and combined checks. This avoids shared file writes while preserving one owner for each stateful boundary.

## HTTPS relay deployment follow-up

The next slice prepares one operator deployment on top of the saved relay settings change. Caddy terminates HTTPS and stores certificates in a persistent volume. The Python relay listens only on a private container network. The operator supplies the DNS name and host.

The relay resolves client identity through one immutable policy. Direct mode uses the TCP peer and ignores forwarding headers. Trusted mode accepts one configured proxy peer and one literal client IP that Caddy overwrites from its socket peer. The relay retains room and creation quotas. Players behind the same public IP share those quotas.

| Deployment design | Consequence | Decision |
| --- | --- | --- |
| Caddy and private relay with a trusted peer | Automatic certificate renewal and existing quotas by client IP. | Selected. |
| nginx with aggregate relay quotas | Avoids proxy identity but collapses all players into the four-room source quota. | Rejected. |

The deployment checks use verified local TLS and the actual Compose configuration. They cover authority rejection, client identity, protocol round trips, action waits, restart invalidation, and credential-safe logs. The operator probe checks a supplied HTTPS origin without disabling certificate verification. These checks prepare deployment. Public DNS, certificate issuance, and a game between separate networks remain release gates.

## Acceptance and release status

Implementation and verification results belong in `player-hosted-status.md`. The current published Site and previous hosted-engine code are earlier prototypes. This plan supersedes their installation-free goal. Public relay deployment, separate-network play, unsigned Windows distribution warnings, and native Windows launch must be reported explicitly. No paid hosting or code-signing purchase is authorized by this plan.
