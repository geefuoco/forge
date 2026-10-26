# Run the Commander baseline

Use Node.js 22 or later, Java 21 with `javac`, and Maven 3.9. Run these commands from the repository root.

## Configure the toolchain

In the managed cloud environment, run:

```bash
bash scripts/setup-forge-cloud.sh
```

The script connects the checkout to the environment's installed Java, Maven, proxy settings, and dependency cache. It writes ignored configuration in `.tools/toolchain.json`. It does not install software or change the saved environment startup configuration.

For another machine, set `NEO_FORGE_JAVA_HOME` and `NEO_FORGE_MAVEN_HOME` to your installation directories. If Maven requires custom settings, set `NEO_FORGE_MAVEN_SETTINGS` to the settings XML file. Alternatively, create `.tools/toolchain.json` with `javaHome`, `mavenHome`, and an optional `mavenSettings` path. Use absolute paths.

## Build and validate the decks

```bash
node scripts/neo-forge.mjs build
node scripts/neo-forge.mjs validate
node scripts/neo-forge.test.mjs
```

The build prints the packaged JAR's SHA-256 hash. Validation prints a new evidence directory under `.audit/ai-runs/`. Its `validation.json` records the actual engine revision, build hashes, loaded decks, AI settings, and isolated writable paths.

Keep the stock deck fixtures byte-identical to the sources in `evaluation/ai/deck-manifest.json`. Their Git attributes disable line-ending conversion. If an older checkout already converted a fixture, restore its bytes from the pinned upstream path in that manifest before running validation.

## Run CPU games

```bash
node scripts/neo-forge.mjs evaluate
```

The stock plan runs six games with seed `11025`, including both deck mirrors and both cross-deck seat orders. Each game has a 180-second startup deadline and a 120-second game deadline. To run only the two cross-deck games, add `--pairing cross`.

Read the printed evidence directory's `summary.json` for outcomes. Each game directory contains its request, logs, setup receipt, and result. A completed game also has a terminal receipt. Timeouts, crashes, and rejected runs return a nonzero command status and never count as competitive draws.

## Open the desktop baseline

On a machine with a graphical desktop, run:

```bash
node scripts/neo-forge.mjs play
```

The launcher opens Forge with an isolated profile containing both requested Commander decks. Use this baseline for human playtests. A headless cloud session needs a graphical display before this command can open a usable window. The custom browser client is still pending.

See [the evaluation report](ai-baseline-report.md) for current results and remaining checks.
