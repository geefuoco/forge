# Run a public HTTPS relay

This bundle runs Caddy and the Python relay on one Linux Docker host. The host player still runs Forge. Rooms disappear when the relay restarts. This setup does not provision hosting or establish that players on separate networks can complete a game.

## Prepare the host

Install Docker Engine and Docker Compose 2.24.4 or newer. Point a domain's DNS record at the host. Allow inbound TCP ports 80 and 443. Caddy uses outbound HTTPS for certificate issuance and renewal. Do not place another reverse proxy or CDN in front of Caddy with this configuration. Client quotas use the actual socket peer seen by Caddy.

The private Docker subnet is `172.30.92.0/29`. Check for a network collision before starting. To change it, update both service addresses, the subnet, and the relay's `--trusted-proxy-peer` address together in `compose.yaml`.

## Start the relay

From this directory, copy `.env.example` to `.env` and set `RELAY_DOMAIN` to your hostname. Supply only the hostname, with no scheme, path, or port. This bundle uses the standard HTTPS port 443.

```sh
cp .env.example .env
docker compose up -d --build
python3 -B probe.py --origin https://relay.example.com --output relay-check.json
```

Caddy obtains and renews the public certificate automatically. Both certificate and configuration data use persistent Docker volumes. Keep the volumes when upgrading. Run `docker compose down` to stop the service. Adding `--volumes` deletes certificate storage and can cause certificate-issuance rate limits on repeated starts.

Set the same HTTPS address in both installed clients through **Client info**. Use matched client release identifiers. Complete a real game from two separate networks before calling internet play ready.

## Verify and operate

`probe.py` creates one disposable room, checks compatibility and role isolation, publishes a synthetic projection, acknowledges a queued action, and closes the room. It verifies TLS with system roots and refuses redirects. The parent process enforces a 45-second deadline, including DNS, headers, and slow responses. Its JSON report contains no room credentials or game projections. A failed or interrupted probe can leave a room until expiry. `--ca-file` is for a staging certificate authority, never for disabling verification.

Run `python3 -B smoke.py --output /tmp/relay-https.json` to test the same Compose services with a temporary local certificate. The smoke test checks rejection of untrusted certificates and mismatched Host and Origin headers, forwarding-header spoofing, action timeouts, backend isolation, log canaries, and restart behavior. It needs Docker, Compose, Python, and OpenSSL. It creates an isolated Compose project and removes only that project's resources. The fixed private subnet prevents concurrent smoke projects on one Docker daemon.

Both request access logs and Caddy runtime logs are discarded because upstream errors can include request metadata. Use `/health`, the protocol probe, Docker process status, and host resource monitoring for diagnostics. Inspect `docker compose ps` when startup fails. TLS issuance errors are also suppressed, so verify DNS, firewall rules, and outbound HTTPS before restarting. Do not enable request logging with live capabilities.

The relay runs as an unprivileged user on a read-only filesystem. Only Caddy publishes ports. The Python backend has only the internal network, and accepts client identity from Caddy's exact private address. Caddy overwrites every `X-Relay-Client-IP` claim with its direct socket peer. Players behind one public IP share creation quotas. Defaults permit four live rooms per client IP and ten attempts per minute. Resource limits are starting bounds, not a measured capacity claim.

Allow more than eight seconds for guest action requests. Caddy waits ten seconds for upstream response headers and does not retry requests. A 504 action response means the outcome is unknown. The pending command remains available to the host, and clients must retain its command ID when retrying.

Upgrade by pulling the intended source revision, rebuilding, and running the protocol probe again. Relay replacement ends active rooms. Schedule upgrades with players and preserve the Caddy volumes.
