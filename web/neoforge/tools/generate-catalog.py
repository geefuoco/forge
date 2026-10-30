import argparse
import subprocess
import hashlib
import json
import re
from pathlib import Path

parser = argparse.ArgumentParser(description='Export NeoForge card data from a Forge checkout.')
parser.add_argument('--forge-root', type=Path, required=True, help='Path to the Forge checkout')
args = parser.parse_args()
forge_root = args.forge_root.resolve()
source = forge_root / 'forge-gui/res'
output = Path(__file__).resolve().parents[1] / 'dist/data'
engine_commit = subprocess.check_output(['git', '-C', str(forge_root), 'rev-parse', 'HEAD'], text=True).strip()
output.mkdir(parents=True, exist_ok=True)
cards = []
for path in sorted((source / 'cardsfolder').rglob('*.txt')):
    raw = path.read_text(encoding='utf-8-sig', errors='replace')
    faces = []
    for block in re.split(r'(?m)^ALTERNATE\s*$', raw):
        fields = {}
        for line in block.splitlines():
            key, sep, value = line.partition(':')
            if sep:
                fields.setdefault(key, []).append(value.strip())
        if 'Name' not in fields:
            continue
        name = fields['Name'][0]
        mana = fields.get('ManaCost', [''])[0].replace('no cost', '')
        types = fields.get('Types', [''])[0]
        oracle = fields.get('Oracle', [''])[0].replace('\\n', '\n')
        faces.append({'name': name, 'mana': mana, 'type': types, 'text': oracle,
                      'pt': fields.get('PT', [''])[0], 'loyalty': fields.get('Loyalty', [''])[0],
                      'colors': fields.get('Colors', [''])[0]})
    if not faces:
        continue
    face = faces[0]
    identity = set()
    for f in faces:
        identity.update(re.findall(r'[WUBRG]', f['mana']))
        for symbol in re.findall(r'\{([^}]+)\}', re.sub(r'\([^)]*\)', '', f['text'])):
            identity.update(re.findall(r'[WUBRG]', symbol))
        for color, letter in [('White', 'W'), ('Blue', 'U'), ('Black', 'B'), ('Red', 'R'), ('Green', 'G')]:
            if color.lower() in f['colors'].lower() or color in f['type'].split():
                identity.add(letter)
        for land, letter in [('Plains', 'W'), ('Island', 'U'), ('Swamp', 'B'), ('Mountain', 'R'), ('Forest', 'G')]:
            if land in f['type'].split():
                identity.add(letter)
    mv = 0
    for token in face['mana'].split():
        if token.isdigit():
            mv += int(token)
        elif token not in ('X', 'Y', 'Z'):
            mv += 2 if token.startswith('2/') else 1
    cards.append({'name': face['name'], 'mana': face['mana'], 'type': face['type'],
                  'text': '\n\n'.join(f['name'] + '\n' + f['text'] for f in faces) if len(faces) > 1 else face['text'],
                  'identity': ''.join(c for c in 'WUBRG' if c in identity), 'mv': mv,
                  'pt': face['pt'], 'loyalty': face['loyalty'],
                  'commander': ('Legendary' in face['type'] and any(t in face['type'] for t in ['Creature', 'Vehicle', 'Spacecraft'])) or 'can be your commander' in raw.lower()})
by_name = {card['name']: card for card in cards}
cards = sorted(by_name.values(), key=lambda card: card['name'].casefold())
(output / 'cards.json').write_text(json.dumps(cards, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
precons = []
for name, filename, subtitle, colors in [
    ('World Shaper', 'World Shaper [EOC] [2025].dck', 'Sacrifice lands. Grow something bigger.', 'BRG'),
    ('Multiverse Reforged', 'Multiverse Reforged [FRC] [2026].dck', 'Rewrite the board with Jace.', 'WUBR')]:
    text = (source / 'quest/commanderprecons' / filename).read_text(encoding='utf-8-sig')
    section = ''
    entries = []
    for line in text.splitlines():
        if line.startswith('['):
            section = line.strip('[]').lower()
        elif section in ('main', 'commander') and line.strip():
            match = re.match(r'(\d+)\s+(.+?)(?:\|.*)?$', line)
            if match:
                entries.append({'name': match[2], 'quantity': int(match[1]), 'section': section})
    precons.append({'id': name.lower().replace(' ', '-'), 'name': name, 'subtitle': subtitle,
                    'colors': colors, 'entries': entries, 'source': filename})
(output / 'precons.json').write_text(json.dumps(precons, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
(output / 'provenance.json').write_text(json.dumps({'engineCommit': engine_commit, 'catalogueCount': len(cards),
    'catalogueSha256': hashlib.sha256((output / 'cards.json').read_bytes()).hexdigest(),
    'source': 'Card-Forge/forge card scripts and stock Commander precons',
    'notice': 'Magic: The Gathering is a trademark of Wizards of the Coast. This fan project is not affiliated with Wizards.'}, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'cards': len(cards), 'precons': [{'name': d['name'], 'count': sum(e['quantity'] for e in d['entries']),
    'unknown': [e['name'] for e in d['entries'] if e['name'] not in by_name]} for d in precons]}))
