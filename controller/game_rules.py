"""Public mechanics reference, separate from strategy recommendations."""
import json
from pathlib import Path
try:
    from .strategy_guide import ReferenceBundle
except ImportError:
    from strategy_guide import ReferenceBundle

DEFAULT_ROOT = Path(__file__).resolve().parent / 'game_rules'


class GameRules(ReferenceBundle):
    label = 'game rules'

    def __init__(self, root=DEFAULT_ROOT):
        super().__init__(root)

    def instructions(self):
        return ('\n# Game rules catalog\nMechanics reference: when mechanics are unclear, '
                'select available IDs through read_game_rules under the Native Instructions '
                'reference procedure. Each call accepts 1-3 IDs.\n'
                + json.dumps(self.catalog, ensure_ascii=False, separators=(',', ':')))


if __name__ == '__main__':
    import sys
    rules = GameRules(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ROOT)
    print(json.dumps({'bundle_sha256': rules.bundle_hash, 'files': rules.hashes,
                     'catalog': rules.catalog}, indent=2))
