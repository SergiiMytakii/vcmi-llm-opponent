"""Bounded reference bundles shared by strategy advice and game mechanics."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

DEFAULT_ROOT = Path(__file__).resolve().parent / 'strategy_guide'
CATALOG_LIMIT = 4096
CARD_LIMIT = 4096
RESULT_LIMIT = 8192


def _read(root, relative, limit):
    path = PurePosixPath(relative)
    if (not relative or path.is_absolute() or '..' in path.parts or '\\' in relative
            or str(path) != relative):
        raise ValueError('invalid reference relative path')
    target = root.joinpath(*path.parts)
    if not target.resolve().is_relative_to(root):
        raise ValueError('reference path escapes root')
    if any(root.joinpath(*path.parts[:i]).is_symlink() for i in range(1, len(path.parts)+1)):
        raise ValueError('reference symlink is not allowed')
    with target.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('reference file exceeds byte limit: ' + relative)
    raw.decode('utf-8')
    return raw


class ReferenceBundle:
    label = "reference"

    def __init__(self, root):
        self.root = Path(root).resolve()
        catalog = _read(self.root, 'catalog.json', CATALOG_LIMIT)
        value = json.loads(catalog)
        if (not isinstance(value, dict) or set(value) != {'version', 'cards'}
                or type(value['version']) is not int or value['version'] != 1
                or not isinstance(value['cards'], list) or not value['cards']):
            raise ValueError(f'invalid {self.label} catalog')
        self.cards = {}
        self.files = {'catalog.json': catalog}
        for card in value['cards']:
            if (not isinstance(card, dict) or set(card) != {'id','title','applicability','file','enabled'}
                    or not isinstance(card['id'], str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',card['id'])
                    or card['id'] in self.cards or type(card['enabled']) is not bool
                    or any(not isinstance(card[k],str) or not card[k].strip() for k in ('title','applicability','file'))
                    or len(card['title']) > 100 or len(card['applicability']) > 240):
                raise ValueError(f'invalid or duplicate {self.label} card')
            if (not card['file'].startswith('rules/') or not card['file'].endswith('.md')
                    or card['file'] in self.files):
                raise ValueError(f'invalid or duplicate {self.label} card file')
            self.files[card['file']] = _read(self.root, card['file'], CARD_LIMIT)
            self.cards[card['id']] = card
        self.hashes = {name:hashlib.sha256(raw).hexdigest() for name,raw in self.files.items()}
        self.bundle_hash = hashlib.sha256(json.dumps(self.hashes,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.catalog = [{k:c[k] for k in ('id','title','applicability')} for c in self.cards.values() if c['enabled']]
        if not self.catalog:raise ValueError(f'{self.label} has no enabled cards')
        if len(json.dumps(self.catalog,ensure_ascii=False).encode('utf-8')) > CATALOG_LIMIT:
            raise ValueError(f'{self.label} exposed catalog exceeds byte limit')
        # The largest permitted result must fit before any paid model call.
        sizes = sorted((len(json.dumps(self._section(c['id'],self.files[c['file']]),
                        ensure_ascii=False,separators=(',',':')).encode('utf-8'))
                        for c in self.cards.values() if c['enabled']),reverse=True)[:3]
        if 2 + sum(sizes) + len(sizes)-1 > RESULT_LIMIT:
            raise ValueError(f'{self.label} consultation exceeds byte limit in bundle preflight')

    def _section(self, name, raw):
        card = self.cards[name]
        return {'id':name,'text':raw.decode('utf-8'),'file':card['file'],
                'sha256':self.hashes[card['file']],'bytes':len(raw)}

    def consult(self, ids):
        allowed={c['id'] for c in self.catalog}
        if (not isinstance(ids,list) or not 1 <= len(ids) <= 3
                or any(not isinstance(i,str) or i not in allowed for i in ids) or len(set(ids)) != len(ids)):
            raise ValueError(f'invalid {self.label} requested IDs')
        sections = []
        for name in ids:
            card = self.cards[name]
            raw = _read(self.root, card['file'], CARD_LIMIT)
            if hashlib.sha256(raw).hexdigest() != self.hashes[card['file']]:
                raise ValueError(f'{self.label} changed during decision')
            sections.append(self._section(name,raw))
        text = json.dumps(sections,ensure_ascii=False,separators=(',',':'))
        if len(text.encode('utf-8')) > RESULT_LIMIT:
            raise ValueError(f'{self.label} consultation exceeds byte limit')
        return text, [{k:s[k] for k in ('id','file','sha256','bytes')} for s in sections]


class StrategyGuide(ReferenceBundle):
    label = "strategy guide"

    def __init__(self, root=DEFAULT_ROOT):
        super().__init__(root)

    def instructions(self):
        return ('\n# Strategy guide catalog\nStrategic choices: select available IDs '
                'using the reference triggers in Native Instructions. Each read_strategy_guide '
                'call accepts 1-3 IDs; continue with the normal reply in this conversation.\n'
                + json.dumps(self.catalog,ensure_ascii=False,separators=(',',':')))


if __name__ == '__main__':
    import sys
    guide = StrategyGuide(sys.argv[1] if len(sys.argv)>1 else DEFAULT_ROOT)
    print(json.dumps({'bundle_sha256':guide.bundle_hash,'files':guide.hashes,'catalog':guide.catalog},indent=2))
