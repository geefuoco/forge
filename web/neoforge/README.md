# NeoForge Commander

A static Commander deck workspace with a local Forge companion for real human-versus-CPU play. The catalogue and decks work without the companion. Decks are stored in browser local storage; export a `.dck` file to keep or transfer a copy.

## Run locally

Serve the `dist` directory over HTTP, for example:

```sh
python3 -m http.server 8000 --directory dist
```

Open `http://localhost:8000`. The companion runs separately on the player's PC. Connect with its loopback address and pairing token through **Connect PC**. The token stays in page memory. The companion validates decks and owns all game rules. Browser draft checks are approximate.

## Data

`dist/data/cards.json` and `precons.json` are exported from Forge card scripts and stock Commander decks. To regenerate them from a Forge checkout:

```sh
python3 tools/generate-catalog.py --forge-root /path/to/forge
```

The generator records the checkout's full Git revision and catalogue hash in `dist/data/provenance.json`. It needs only Python 3 and Git. The browser has no build step or package dependencies.

The Site source repository includes generated assets. When using the copy in the Forge repository, generate the catalogue before serving it. To build the companion source download from a checkout containing `tools/browser-bridge`, run:

```sh
python3 tools/package-companion.py --forge-root /path/to/forge
```

Read `STATUS.md` for verified behavior and remaining work. The first launch through a fresh Maven dependency cache remains unverified.

## Checks

```sh
node --check dist/app.js
python3 -m py_compile tools/generate-catalog.py
```

With Python Playwright and Chromium at `/usr/bin/chromium`, run the allocation editor checks. The script serves the current `dist` directory and supplies mock companion decisions.

```sh
python3 tools/verify-allocations.py
```

Magic: The Gathering is a trademark of Wizards of the Coast. This fan project is not affiliated with Wizards of the Coast.
