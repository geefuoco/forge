import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('prepare', Path(__file__).resolve().parents[1] / 'prepare.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'source'
        classes = self.root / 'forge-gui-desktop/target/classes'
        classes.mkdir(parents=True)
        (classes / 'module.txt').write_text('module resource')
        source = self.root / 'tools/browser-bridge/src/forge/browser/Bridge.java'
        source.parent.mkdir(parents=True)
        source.write_text('''package forge.browser;
public class Bridge {
    public static void main(String[] args) throws Exception {
        for (String name : new String[]{"module.txt", "external.txt"}) {
            System.out.println(new String(Bridge.class.getResourceAsStream("/" + name).readAllBytes()));
        }
    }
}''')
        self.repository = self.base / 'm2'
        self.repository.mkdir()
        self.jar = self.repository / 'dependency.jar'
        with zipfile.ZipFile(self.jar, 'w') as archive:
            archive.writestr('external.txt', 'external resource')
        (self.repository / 'unrelated-secret.jar').write_text('must not ship')
        self.classpath = self.base / 'classpath.txt'
        self.classpath.write_text(str(self.jar))
        self.output = self.base / 'bundle'

    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK 21 required')
    def test_bundle_runs_without_source_or_maven_repository(self):
        manifest = prepare.prepare(self.root, self.classpath, self.output, self.output)
        shutil.rmtree(self.root)
        shutil.rmtree(self.repository)
        classpath = str(self.output / 'runtime/bridge') + os.pathsep + (self.output / 'runtime/classpath.txt').read_text().strip()
        result = subprocess.run(['java', '-cp', classpath, 'forge.browser.Bridge'], check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout.splitlines(), ['module resource', 'external resource'])
        self.assertEqual(len(list((self.output / 'runtime/lib').glob('*.jar'))), 1)
        self.assertEqual(json.loads((self.output / 'runtime/manifest.json').read_text()), manifest)
        self.assertNotIn(str(self.repository), (self.output / 'runtime/classpath.txt').read_text())

    def test_missing_runtime_dependency_fails_before_creating_bundle(self):
        self.jar.unlink()
        with self.assertRaises(FileNotFoundError):
            prepare.prepare(self.root, self.classpath, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_bundle_is_never_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / 'keep'
        sentinel.write_text('existing bundle')
        with self.assertRaises(FileExistsError):
            prepare.prepare(self.root, self.classpath, self.output)
        self.assertEqual(sentinel.read_text(), 'existing bundle')


if __name__ == '__main__':
    unittest.main()
