# Local browser bridge

The bridge runs Forge on your computer for the private NeoForge Site. It binds to `127.0.0.1:8787` and accepts requests only from the configured HTTPS Site origin. Keep the terminal open while playing. The pairing token is printed once on startup; enter it in the Site and keep it private. Restarting the bridge revokes the token.

Install a JDK matching this Forge checkout, Python 3, and Maven. From the root of this Forge checkout, build and install its modules into your local Maven cache:

```sh
mvn -pl forge-gui-desktop -am install -DskipTests -Dcheckstyle.skip
```

Then run this command from the checkout on Windows, macOS, or Linux. Replace the origin with the exact origin of your private Site, without a path.

```sh
python tools/browser-bridge/launch.py --origin https://your-site.example
```

The launcher resolves the desktop module's dependencies, compiles the bridge, and starts it from Forge's desktop directory so it can find its assets. Java and Maven must be on `PATH`. On some systems the Python command is `python3` or `py -3`. The bridge uses its own persistent profile in `.neoforge/bridge-profile` beneath your home directory. Set `--profile /path/to/profile` to choose another location. Your desktop Forge profile and its custom profile file are not loaded by the bridge.

The Forge card database loads when the first match starts, which can take time. Decks are resolved and validated by the installed Forge database. The bridge reports unsupported decisions instead of making them automatically.

Combat damage and generic amounts use an allocation editor in the browser. Assign each target's amount, then confirm. Combat checks include blocker order, lethal damage before trample, deathtouch, and free division when the ability allows it. Generic amounts respect per-target limits and minimums. When Forge permits deferring a combat assignment, **Assign another creature first** leaves that attacker for later.

The companion validates the complete assignment before passing the original target objects back to Forge. Invalid or stale submissions leave the decision pending. Hidden cards remain labelled **Face-down card**. Other synchronous dialogs, including text input and card-list manipulation, remain unsupported. A complete browser-driven game is not verified.

A secure browser may restrict requests from the hosted Site to a local HTTP service. The bridge responds to private-network preflights, but availability depends on the browser's local-network policy. Keep the token out of URLs and shared logs. This bridge is a work in progress; not every Forge decision type is supported yet.

## Check prompt handling

Set `FORGE_BRIDGE_CLASSPATH` to the built desktop module classes and its resolved dependency classpath. Use the matching JDK on `PATH`. Run the protocol checks from the checkout root.

```sh
python tools/browser-bridge/tests/run-prompts.py
```

The checks call `ProtocolGuiGame` with combat and generic allocation decisions. They verify the returned target maps and rejection of invalid assignments. They do not prove a complete match.
