# Installed NeoForge client

The client includes Forge, Java, card resources, and the deck and game interface. Players do not install Java, Maven, or Python. Windows is the first target, with Linux alongside it.

Extract the complete application archive. On Windows, start `NeoForge.exe`. On Linux, start `NeoForge/bin/NeoForge`. Keep the application directory intact. The executable opens the bundled interface in your system browser. Decks are stored in your private application profile and survive browser port changes.

For a local CPU game, import the starter decks or your own deck, open **Play**, select both decks, and start. No relay is needed.

For a friend game, open **Client info** and save the operator's HTTPS relay address before starting a game. The address survives application restarts. Select **A friend**, choose both decks, create the lobby, and select **Show invitation**. Send the complete invitation privately. Your friend starts the same release, selects **Join a friend**, and pastes the invitation. No router changes, VPN, or separately run companion are required.

**Clear relay** saves an empty address. **Use app default** removes your saved address and restores the address supplied with the application, if any. A `--relay` launch option takes precedence and prevents changes in Client info. Once you start or join any game, restart the application before changing the address. An invalid saved settings file produces a warning and disables hosting until you save or reset the address. Local CPU games remain available.

The host runs the authoritative game. The relay receives only the guest's projection and exchanges actions and results. The guest never simulates an independent game. Keep both applications open. Network reconnect and browser reload restore the view of the same live engine. Closing the host or restarting the relay ends the room. This version has no host migration or restart recovery. The host machine can inspect both hands and must be trusted.

## Build a native application

Build on each target operating system with Java 21, Maven, and Python 3. These are build-machine requirements only. From the checkout root, compile Forge and resolve the runtime classpath in the same reactor invocation:

```sh
mvn -B -pl forge-gui-desktop -am -DskipTests -Dcheckstyle.skip compile org.apache.maven.plugins:maven-dependency-plugin:3.1.2:build-classpath -DincludeScope=runtime -Dmdep.outputFile=/absolute/path/player-runtime-classpath.txt
```

Use a native absolute path on Windows. Generate the catalogue in a temporary directory so its tracked provenance file does not dirty the source checkout:

```sh
mkdir -p /tmp/neoforge-catalog/tools
cp web/neoforge/tools/generate-catalog.py /tmp/neoforge-catalog/tools/
python3 /tmp/neoforge-catalog/tools/generate-catalog.py --forge-root /path/to/forge
```

Package a clean commit with the matching catalogue. Set `JAVA_HOME` to the Java 21 JDK. The relay option supplies an optional default. Players can save a different address in Client info:

```sh
python3 tools/player-client/package.py --classpath-file /absolute/path/player-runtime-classpath.txt --output /new/output-directory --catalog-dir /tmp/neoforge-catalog/dist/data --relay-origin https://your-relay.example
```

`--output` must not exist. Release packaging refuses a dirty tree and catalogue provenance from another commit. `--allow-dirty` creates a distinct development identity. Clients with different identities cannot join the same room. The package retains the GPL license and dependency inventory. Distribution must also provide the corresponding GPL source. Keep the complete archive and source revision together.

The default application image produces a Windows ZIP or Linux tar.gz. Windows images include their own native executable and runtime. Linux images include `bin/NeoForge` and a bundled runtime. Native installers can be requested with `--type exe` on Windows or `--type deb` on Linux. Code signing is not configured.

The **Installed player client** GitHub Actions workflow builds native Windows and Linux archives and checks that each launcher serves its interface without development tools on PATH. It does not publish a release or sign the binaries. A workflow definition is not proof that the Windows build has run.

## Verify the implementation

Use the matching JDK and Maven classpath for the Java socket tests. The test source is `test/forge/browser/DesktopClientTest.java`. Compile it with the client and Bridge sources. It checks local origin boundaries, profile persistence across ports, and lost-acknowledgement behavior against a stub relay.

The combined probe uses the real relay, packaged executables, Chromium, and Forge:

```sh
python3 tools/player-client/tests/installed-game.py --image /path/to/NeoForge --work /tmp/neoforge-installed-proof
```

Run relay and packaging checks separately:

```sh
python3 -m unittest discover -s tools/player-relay/tests -v
python3 -m unittest discover -s tools/player-client/tests -v
```

See [the plan](../../docs/neo-forge/player-hosted-plan.md), [settings reference](../../docs/neo-forge/relay-settings.md), and [verification status](../../docs/neo-forge/player-hosted-status.md) for exact behavior and checks. The previous hosted-engine gateway is an earlier prototype, not a runtime dependency of this client.
