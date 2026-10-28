import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SPEC = importlib.util.spec_from_file_location('player_package', Path(__file__).parents[1] / 'package.py')
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


class PackageTests(unittest.TestCase):
    def test_release_identity_rejects_dirty_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', root], check=True)
            subprocess.run(['git', '-C', root, '-c', 'user.name=Test', '-c',
                            'user.email=test@example.invalid', 'commit', '--allow-empty', '-qm', 'base'], check=True)
            head = package.run(['git', 'rev-parse', 'HEAD'], root)
            self.assertEqual(package.build_identity(root, False), head)
            (root / 'untracked').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'clean source tree'):
                package.build_identity(root, False)
            first = package.build_identity(root, True)
            self.assertTrue(first.startswith(head + '-dev-'))
            self.assertNotEqual(first, package.build_identity(root, True))

    def test_relay_origin_boundary(self):
        self.assertEqual(package.relay_origin('https://relay.example/', False), 'https://relay.example')
        self.assertEqual(package.relay_origin('http://127.0.0.1:8080', True), 'http://127.0.0.1:8080')
        for origin in ['http://relay.example', 'https://user@relay.example',
                       'https://relay.example/path', 'https://relay.example/#secret',
                       'https://relay.example/?x=1', 'file:///tmp/x']:
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                package.relay_origin(origin, True)
        with self.assertRaises(ValueError):
            package.relay_origin('http://localhost:8080', False)

    def test_payload_has_precompiled_code_exact_dependencies_resources_and_no_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ['forge-core/target/classes', 'forge-gui-desktop/target/classes',
                             'forge-gui/res', 'web/neoforge/dist/data']:
                (root / relative).mkdir(parents=True)
            (root / 'forge-core/target/classes/Engine.class').write_bytes(b'compiled-engine')
            (root / 'forge-gui-desktop/target/classes/Desktop.class').write_bytes(b'compiled-desktop')
            (root / 'forge-gui/res/cards.dat').write_text('cards')
            (root / 'web/neoforge/dist/index.html').write_text('site')
            (root / 'web/neoforge/dist/data/provenance.json').write_text(json.dumps({'engineCommit': 'exact-commit'}))
            (root / 'LICENSE').write_text('GPL')
            dependency = root / 'dependency.jar'
            with zipfile.ZipFile(dependency, 'w') as archive:
                archive.writestr('Library.class', b'compiled-library')
            cp = root / 'classpath.txt'
            cp.write_text(os.pathsep.join([str(root / 'forge-core/target/classes'), str(dependency)]))
            def compile_stub(command, cwd):
                target = Path(command[command.index('-d') + 1])
                (target / 'DesktopClient.class').write_bytes(b'compiled-client')
            payload = root / 'payload'
            with patch.object(package, 'run', side_effect=compile_stub):
                package.stage(root, payload, cp, root / 'jdk', 'exact-commit', None)
            self.assertEqual(json.loads((payload / 'client-config.json').read_text())['buildId'], 'exact-commit')
            self.assertEqual(len(list((payload / 'lib').glob('*.jar'))), 3)
            with zipfile.ZipFile(payload / 'client.jar') as archive:
                self.assertIn('DesktopClient.class', archive.namelist())
                manifest = archive.read('META-INF/MANIFEST.MF').decode()
                self.assertIn('Main-Class: forge.browser.DesktopClient', manifest)
                self.assertIn('Class-Path: lib/000-forge-core.jar', manifest)
            self.assertTrue((payload / 'forge-gui/res/cards.dat').is_file())
            self.assertTrue((payload / 'web/neoforge/dist/index.html').is_file())
            self.assertFalse(list(payload.rglob('*.java')))
            self.assertFalse(list(payload.rglob('*.py')))
            self.assertFalse(list(payload.rglob('pom.xml')))

    def test_manifest_folding_obeys_jar_limit(self):
        result = package.manifest(['lib/' + 'a' * 100 + '.jar'])
        self.assertTrue(all(len(line.encode()) <= 70 for line in result.split('\r\n')))
        self.assertIn('\r\n ', result)


if __name__ == '__main__':
    unittest.main()
