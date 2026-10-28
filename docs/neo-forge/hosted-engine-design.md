# Hosted engine design

The hosted service runs Forge on a server. Players use the website without Java, Forge, or a companion on their computers. This implementation has local verification. Public deployment and the milestone 2 acceptance checks remain open.

## Match and seat ownership

`tools/hosted-engine/server.py` owns the session, invitation, and match registries. A `MatchRecord` moves through `waiting`, `starting`, `running`, `finished`, or `failed`. Each record has one Java process, a private profile, and at most two authenticated human seats.

The gateway derives a seat from its HttpOnly session cookie. A browser cannot select another seat through a header or action body. The gateway injects the worker credential and seat into private loopback requests. Worker addresses and credentials never reach the browser.

`Bridge.MatchSession` retains the existing seat-zero API for development tests. Each human has a separate `SeatView` with its controller, prompt, action queue, handles, revision, and serialized snapshot. Both views refer to one authoritative Forge match. `HostedMatch` registers each human with its own `PumpGui` through the existing GUI-map overload. The rules and AI remain in Java.

Each projection contains its viewer's hand and public zones. Opponent hands and library contents are absent. Face-down labels use that viewer's visibility. Raw Forge views, deltas, and protocol events stay inside the worker. Off-turn concession enters a match-wide queue that the active engine input pump drains.

## Process isolation

One JVM per match keeps Forge's static model and GUI state out of other games. Separate processes also limit the effect of a worker crash. A shared JVM was rejected because concurrent mutation of Forge globals has not been proven safe. The two independent design explorations and their cross-judge agreed on process isolation.

The gateway bounds active matches, HTTP threads, requests, bodies, startup time, idle time, and total match lifetime. Each JVM has a configured heap and processor count. The Compose example adds container memory, CPU, and PID limits. A heap limit does not bound native memory, and the processes share an operating-system user. This is process isolation for trusted engine code, not a sandbox for hostile plugins.

## Browser API

All responses use schema version 1. Mutation requests require the exact configured origin and JSON content type. Host headers must match the configured public authority. Private responses use `Cache-Control: no-store`.

| Endpoint | Behavior |
| --- | --- |
| `GET /api/v1/status` | Reports service readiness without private game data. |
| `GET /api/v1/session` | Reports the current session and seat. |
| `POST /api/v1/session` | Checks the private service access key and grants match creation. |
| `POST /api/v1/logout` | Revokes this browser session. |
| `POST /api/v1/matches` | Creates a CPU match or a waiting friend lobby using two supplied decks. |
| `GET /api/v1/match` | Returns the authenticated seat's current projection. |
| `POST /api/v1/action` | Submits an existing Forge action for that seat. |
| `POST /api/v1/invites` | Creates or replaces a ten-minute invitation to the vacant friend seat. |
| `POST /api/v1/join` | Atomically consumes the invitation and binds a guest session. |

The private access key is an operator secret. It is not shipped in the website. This is private-service access for the feasibility milestone, not the full account system planned for milestone 4. Guests can control their claimed seat but cannot create matches. The creator supplies both decks in this version.

The invitation token travels in a URL fragment. The browser removes that fragment before any fetch and redeems it through a POST. Redemption creates a separate session credential. Reusing the invitation cannot take over the claimed seat.

## Reconnect and expiry

A page reload or network disconnect retains the HttpOnly session cookie. The browser restores its seat and pending prompt from the live worker. It never replaces a disconnected human with AI. Stale or ambiguous actions require a fresh snapshot rather than automatic resubmission.

The default session lasts five hours. Games expire after four hours or thirty minutes without a match request. Closing one browser does not stop a game if another participant remains connected. Explicit sign-out revokes that browser's credential. Engine or gateway restarts lose live matches in this milestone. Durable save and restore belong to milestone 3.

## Website hosting

The gateway can serve the existing static website and API under one HTTPS origin. GPT Sites can remain the frontend, but its Cloudflare Worker runtime cannot execute Java. Its current static deployment has no API proxy. A same-origin Site proxy to the external engine service must be configured and verified once that service has an HTTPS address. Direct third-party session cookies are avoided.

The existing Site identity and audience remain unchanged. The published companion prototype is not replaced with a website that points at an absent engine. See [hosting feasibility](hosting-feasibility.md) for the provider investigation and remaining deployment gate.
