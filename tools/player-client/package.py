#!/usr/bin/env python3
"""Build a self-contained native NeoForge application from compiled Forge classes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
import zipfile


def run(command, cwd=None):
    return subprocess.run([str(part) for part in command], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def build_identity(root, allow_dirty):
    commit = run(['git', 'rev-parse', 'HEAD'], root)
    dirty = bool(run(['git', 'status', '--porcelain', '--untracked-files=normal'], root))
    if dirty and not allow_dirty:
        raise ValueError('Release packaging requires a clean source tree; use --allow-dirty for development.')
    return commit + ('-dev-' + uuid.uuid4().hex if dirty or allow_dirty else '')


def relay_origin(value, development):
    if not value:
        return None
    parsed = urllib.parse.urlsplit(value)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or
            parsed.fragment or parsed.path not in ('', '/') or
            (parsed.scheme != 'https' and not (development and parsed.scheme == 'http' and
             parsed.hostname in ('localhost', '127.0.0.1', '::1')))):
        raise ValueError('Relay must be an HTTPS origin (loopback HTTP requires --allow-dirty).')
    parsed.port
    return value.rstrip('/')


def manifest(classpath):
    # JAR manifest lines are limited to 72 UTF-8 bytes including CRLF.
    value = 'Class-Path: ' + ' '.join(classpath)
    lines = ['Manifest-Version: 1.0', 'Main-Class: forge.browser.DesktopClient']
    while len(value) > 70:
        lines.append(value[:70])
        value = ' ' + value[70:]
    lines.append(value)
    return '\r\n'.join(lines) + '\r\n\r\n'


def jar_directory(source, target):
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())


def stage(root, payload, classpath, jdk, build_id, relay, catalog=None):
    entries = [Path(part).resolve() for part in classpath.read_text().strip().split(os.pathsep) if part]
    desktop = root / 'forge-gui-desktop/target/classes'
    if desktop.resolve() not in entries:
        entries.append(desktop.resolve())
    for entry in entries:
        if not entry.exists() or (entry.is_file() and entry.suffix != '.jar'):
            raise ValueError(f'Invalid runtime classpath entry: {entry}')
    if not entries:
        raise ValueError('Runtime classpath is empty')
    payload.mkdir()
    lib = payload / 'lib'
    lib.mkdir()
    names = []
    for index, entry in enumerate(entries):
        name = f'{index:03d}-' + (entry.name if entry.is_file() else entry.parent.parent.name + '.jar')
        target = lib / name
        if entry.is_dir():
            jar_directory(entry, target)
        else:
            shutil.copy2(entry, target)
        names.append('lib/' + urllib.parse.quote(name))
    with tempfile.TemporaryDirectory(prefix='neoforge-classes-') as temporary:
        compiled = Path(temporary)
        sources = [root / 'forge-gui/src/main/java/forge/localinstance/properties/ForgeProfileProperties.java',
                   root / 'tools/browser-bridge/src/forge/browser/Bridge.java',
                   root / 'tools/player-client/src/forge/browser/DesktopClient.java']
        run([jdk / 'bin' / executable('javac'), '--release', '21', '-cp',
             os.pathsep.join(map(str, entries)), '-d', compiled, *sources], root)
        jar_directory(compiled, payload / 'client.jar')
    with zipfile.ZipFile(payload / 'client.jar', 'a', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('META-INF/MANIFEST.MF', manifest(names))
    for relative in ('forge-gui/res', 'web/neoforge/dist'):
        source = root / relative
        if not source.is_dir():
            raise ValueError(f'Missing packaged resources: {source}')
        shutil.copytree(source, payload / relative)
    if catalog:
        shutil.copytree(catalog, payload / 'web/neoforge/dist/data', dirs_exist_ok=True)
    provenance = payload / 'web/neoforge/dist/data/provenance.json'
    if not provenance.is_file():
        raise ValueError('Generate the static card catalogue with provenance before packaging')
    if json.loads(provenance.read_text()).get('engineCommit') != build_id.split('-dev-', 1)[0]:
        raise ValueError('Catalogue provenance must match the packaged source commit')
    shutil.copy2(root / 'LICENSE', payload / 'LICENSE')
    config = {'schemaVersion': 1, 'buildId': build_id, 'development': '-dev-' in build_id}
    if relay:
        config['relayOrigin'] = relay
    (payload / 'client-config.json').write_text(json.dumps(config, indent=2) + '\n')
    inventory = {str(p.relative_to(payload)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(lib.iterdir())}
    (payload / 'runtime-dependencies.json').write_text(json.dumps(inventory, indent=2) + '\n')


def executable(name):
    return name + ('.exe' if os.name == 'nt' else '')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--classpath-file', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path, help='New destination directory')
    parser.add_argument('--java-home', type=Path, default=os.environ.get('JAVA_HOME'))
    parser.add_argument('--relay-origin')
    parser.add_argument('--catalog-dir', type=Path, help='Generated catalogue directory with provenance.json')
    parser.add_argument('--app-version', default='1.0.0')
    parser.add_argument('--type', choices=['app-image', 'exe', 'deb'], default='app-image')
    parser.add_argument('--allow-dirty', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    if output.exists():
        parser.error('Output directory already exists; choose a new destination')
    try:
        identity = build_identity(root, args.allow_dirty)
        relay = relay_origin(args.relay_origin, args.allow_dirty)
        if not args.java_home:
            raise ValueError('Set JAVA_HOME or --java-home to a Java 21 JDK')
        jdk = Path(args.java_home).resolve()
        version = run([jdk / 'bin' / executable('javac'), '-version'])
        if not version.startswith('javac 21'):
            raise ValueError('Packaging requires a Java 21 JDK')
        with tempfile.TemporaryDirectory(prefix='neoforge-package-') as temporary:
            payload = Path(temporary) / 'payload'
            stage(root, payload, args.classpath_file.resolve(), jdk, identity, relay, args.catalog_dir)
            pom = ET.parse(root / 'forge-gui-desktop/pom.xml')
            options = pom.findtext('{*}properties/{*}addopen.java.args', default='')
            command = [jdk / 'bin' / executable('jpackage'), '--type', args.type,
                       '--name', 'NeoForge', '--app-version', args.app_version,
                       '--vendor', 'NeoForge', '--input', payload, '--main-jar', 'client.jar',
                       '--main-class', 'forge.browser.DesktopClient', '--add-modules',
                       'ALL-MODULE-PATH', '--dest', output]
            for option in shlex.split(options):
                # jpackage expects one complete --add-opens option per java-options argument.
                if option == '--add-opens':
                    continue
                command += ['--java-options', '--add-opens=' + option]
            run(command, root)
        if args.type == 'app-image':
            image = output / 'NeoForge'
            archive = shutil.make_archive(str(output / 'NeoForge'),
                                          'zip' if os.name == 'nt' else 'gztar', output, image.name)
            print(archive)
        print('Build ID ' + identity)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n' + getattr(error, 'stderr', ''))


if __name__ == '__main__':
    main()
