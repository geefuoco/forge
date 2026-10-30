import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class CatalogEncodingTest(unittest.TestCase):
    def test_catalog_preserves_unicode_with_ascii_default_locale(self):
        source = Path(__file__).resolve().parents[3] / 'web/neoforge/tools/generate-catalog.py'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'forge'
            cards = root / 'forge-gui/res/cardsfolder/f'
            precons = root / 'forge-gui/res/quest/commanderprecons'
            cards.mkdir(parents=True)
            precons.mkdir(parents=True)
            name = 'Kōri, the Test Commander'
            (cards / 'kori.txt').write_text(f'Name:{name}\nManaCost:2 U\nTypes:Legendary Creature Test\nOracle:Draw a card.\n', encoding='utf-8')
            for filename in ('World Shaper [EOC] [2025].dck', 'Multiverse Reforged [FRC] [2026].dck'):
                (precons / filename).write_text(f'[Commander]\n1 {name}\n[Main]\n99 {name}\n', encoding='utf-8')
            subprocess.run(['git', 'init', '-q', root], check=True)
            subprocess.run(['git', '-C', root, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                            'commit', '--allow-empty', '-qm', 'fixture'], check=True)
            generator = Path(temporary) / 'catalog/tools/generate-catalog.py'
            generator.parent.mkdir(parents=True)
            shutil.copyfile(source, generator)
            environment = dict(os.environ, LC_ALL='C', LANG='C', PYTHONUTF8='0', PYTHONCOERCECLOCALE='0')
            result = subprocess.run([sys.executable, '-X', 'utf8=0', str(generator), '--forge-root', str(root)],
                                    env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
            data = generator.parent.parent / 'dist/data'
            self.assertEqual(json.loads((data / 'cards.json').read_text(encoding='utf-8'))[0]['name'], name)
            for deck in json.loads((data / 'precons.json').read_text(encoding='utf-8')):
                self.assertEqual(deck['entries'][0]['name'], name)
            self.assertEqual(json.loads((data / 'provenance.json').read_text(encoding='utf-8'))['catalogueCount'], 1)


if __name__ == '__main__':
    unittest.main()
