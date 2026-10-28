# Run the hosted engine service

This directory is an earlier cloud-engine prototype. The active product uses [installed clients](../player-client/README.md) and a [lightweight relay](../player-relay/README.md). This gateway is not a dependency of those clients.

These commands are for the server operator. Players need only the hosted website.

## Build the container

From the Forge checkout root, build the image with the exact source revision:

```sh
docker build -f tools/hosted-engine/Dockerfile --build-arg SOURCE_REVISION="$(git rev-parse HEAD)" -t neoforge-hosted .
```

In a managed environment with an HTTPS proxy certificate, add `--secret id=proxy_ca,src="$CODEX_PROXY_CERT"`. The build uses the inherited proxy and temporary CA trust. It removes the build certificate and temporary Maven settings before saving each image layer.

The image compiles Forge and the worker with Java 21. `prepare.py` copies the exact resolved runtime classpath, compiled modules, and worker classes. Maven caches and source files are unnecessary at runtime. The image includes the pinned Forge resources and generates the website card catalogue.

## Start behind an HTTPS proxy

Set `NEOFORGE_ORIGIN` to the exact public HTTPS origin. Set `NEOFORGE_ACCESS_KEY` through your host's secret manager. Do not put the key in source, a URL, or a browser configuration file.

The provider's TLS proxy must preserve the public Host header. Forward traffic to container port 8080. Run one gateway instance because sessions and match routing are in memory. Do not autoscale or restart active games until durable recovery exists.

The supplied Compose file binds only a server-local port. It limits the container to 4 GiB, two CPUs, and 256 processes. Supply the source revision and both environment variables, then run:

```sh
docker compose -f tools/hosted-engine/compose.yaml up --build -d
```

The default admission limit is two matches. Each worker has a 1024 MiB maximum Java heap. These are initial limits, not a measured capacity guarantee. A container-wide memory exhaustion can affect both games. Size the host from complete-game measurements before deployment.

Open the website, select **Sign in**, and enter the private service key. For a CPU game, select both decks and start. For a friend game, select **A friend**, create the lobby, and generate an invitation. The friend opens the invitation in a separate browser profile. Each session owns one seat.

## Verify locally with built Forge classes

Use the matching JDK on `PATH`. Set `FORGE_BRIDGE_CLASSPATH` to the desktop classes plus Maven's resolved dependency classpath. Compile `Bridge.java` into `forge-gui-desktop/target/browser-bridge` before starting the gateway, or set `FORGE_BRIDGE_CLASSES` to its compiled output directory.

For a development server, use an explicit loopback origin:

```sh
python3 tools/hosted-engine/server.py --dev --origin http://127.0.0.1:8080
```

Run the boundary, packaging, browser, real-engine, and natural-completion checks from the checkout root:

```sh
python3 -m unittest discover -s tools/hosted-engine/tests -v
python3 tools/browser-bridge/tests/run-prompts.py
python3 tools/verify-hosted.py
python3 tools/hosted-engine/tests/real-service.py --output /tmp/neoforge-service-proof
python3 tools/hosted-engine/tests/natural-game.py --work /tmp/neoforge-natural-proof
```

The real-service check starts two isolated JVMs and checks seat privacy, invite replay, reconnect, concession, and worker termination. The browser probe uses website controls and requires a natural outcome. Both checks use a local server. They do not prove public deployment, play from separate networks, AI quality, or recovery after service restart.
