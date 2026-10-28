# Hosting feasibility

Historical cloud-engine prototype. The accepted target is now [installed clients with a player-hosted relay](player-hosted-plan.md). This document does not describe the active release architecture.

Checked 2026-10-28. No hosting account is provisioned and no paid service has been selected or purchased.

## GPT Sites and the Java engine

The connected Sites runtime executes Cloudflare Workers with 128 MB per isolate. It supports the website and an HTTP proxy, but cannot execute the Java Forge process. The existing NeoForge Site remains the private companion prototype. The hosted implementation serves the same browser client and API from the gateway. Keeping GPT Sites as the public website requires a same-origin proxy to the future Java service and a published-origin test.

Players need no local Java, Forge, companion, VPN, tunnel, or running host PC. The additional machine belongs to the service operator.

## Initial local resource evidence

The real-service probe started one human-versus-human match and one human-versus-CPU match concurrently. Each used a separate Java 21 process, a separate profile, a 1024 MiB heap cap, and one active processor. One sampling point reported 417,888 KiB and 414,468 KiB of resident memory. Observed process high-water marks were 425,112 KiB and 414,468 KiB. These are setup samples, not full-game maxima or a capacity benchmark.

Run `python3 tools/hosted-engine/tests/real-service.py --output /tmp/neoforge-service-proof` to regenerate the machine-readable report. That check also verifies real seat projections, authenticated invitation redemption, reconnect, off-turn concession, and termination of one worker while another game survives.

A two-game deployment needs room for both heaps, native Java memory, profiles, and the gateway. The Compose example starts with a 4 GiB container limit. A single game on a 2 GiB host is a candidate for a measured trial. Neither size is a production capacity guarantee.

## Provider candidates

| Provider | Published capability and cost | Assessment |
| --- | --- | --- |
| GPT Sites | Cloudflare Worker runtime, 128 MB per isolate. | Keep the frontend here if desired. An external Java engine is still required. |
| Oracle Always Free Ampere A1 | Official documentation lists 1,500 OCPU-hours and 9,000 GB-hours monthly, equivalent to two OCPUs and 12 GB continuously. | Best free candidate to investigate. Account signup and regional capacity are required. ARM compatibility and a complete game on that host remain untested. Idle instances can be reclaimed. |
| Render free web service | Official compute plans list 0.1 CPU and 512 MB. | Insufficient headroom for this worker design. Do not call it a feasible free host from setup-only samples. |
| Render paid web service | A one-CPU, 2 GB plan supports a candidate single-game trial. | Requires paid service approval and a live cost check before provisioning. |
| Fly Machines | Current pricing page lists a 2 GB shared-CPU preset at US$17.55 per month continuously, plus storage and egress. | Candidate paid trial. The advertised preset is a price reference, not a measured cost for this application. |

Sources checked directly:

- [Oracle Always Free compute and reclamation rules](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).
- [Render compute plans](https://render.com/docs/compute-plans).
- [Fly pricing](https://fly.io/pricing/).

Prefer an Oracle free-capacity trial if signup and regional capacity are acceptable. Keep the container provider-neutral until measurements on a real host establish memory, CPU, startup, network use, and complete-game behavior. No advertised free tier guarantees capacity or uninterrupted games.

## Milestone 2 acceptance remains open

Public Java deployment requires an operator-owned hosting account. After provisioning, run a natural game from a clean browser and a friend invitation from a separate network. Stop the local prototype and verify that browser requests stay on the hosted origin. Check HTTPS session cookies, reconnect, both private views, concurrent matches, resource exhaustion, and worker failures on that deployment. Record billed or free usage from the selected account.

The current local checks cannot satisfy those deployment gates. Restart recovery, durable saves, and replay remain milestone 3.
