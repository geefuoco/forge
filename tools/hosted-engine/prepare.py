#!/usr/bin/env python3
"""Bundle a compiled reactor and Maven's exact runtime dependency classpath."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def prepare(root, classpath_file, output, runtime_root=Path('/opt/neoforge')):
    root = root.resolve()
    entries = [root / 'forge-gui-desktop/target/classes']
    entries.extend(Path(entry) for entry in classpath_file.read_text().strip().split(os.pathsep) if entry)
    entries = list(dict.fromkeys(entry.resolve() for entry in entries))
    for entry in entries:
        if not entry.exists():
            raise FileNotFoundError(entry)
        if not entry.is_dir() and entry.suffix != '.jar':
            raise ValueError(f'Not a runtime classes directory or jar: {entry}')
    if output.exists():
        raise FileExistsError(f'Bundle output must be a new directory: {output}')
    output.mkdir(parents=True)
    classpath = []
    manifest = []
    for entry in entries:
        if entry.is_dir():
            relative = entry.relative_to(root)
            if relative.parts[-2:] != ('target', 'classes'):
                raise ValueError(f'Unexpected reactor classes directory: {entry}')
            destination = Path('runtime/classes') / relative.parts[0]
            shutil.copytree(entry, output / destination)
            manifest.append({'path': str(destination), 'module': relative.parts[0]})
        else:
            digest = hashlib.sha256(entry.read_bytes()).hexdigest()
            destination = Path('runtime/lib') / (digest + '-' + entry.name)
            (output / destination).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(entry, output / destination)
            manifest.append({'path': str(destination), 'sha256': digest})
        classpath.append(str(runtime_root / destination))
    bridge = output / 'runtime/bridge'
    bridge.mkdir()
    subprocess.run(['javac', '--release', '21', '-cp', os.pathsep.join(map(str, entries)),
                    '-d', str(bridge), str(root / 'tools/browser-bridge/src/forge/browser/Bridge.java')],
                   cwd=root / 'forge-gui-desktop', check=True)
    (output / 'runtime/classpath.txt').write_text(os.pathsep.join(classpath) + '\n')
    (output / 'runtime/manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--classpath-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runtime-root', type=Path, default=Path('/opt/neoforge'))
    args = parser.parse_args()
    prepare(args.root, args.classpath_file, args.output, args.runtime_root)
