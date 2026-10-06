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
        return ('\n# Game rules catalog\nThese cards explain mechanics, not which strategy to choose. '
                'When a decision depends on unclear mechanics, use nk3_game_rules.read_game_rules '
                'to read 1-3 relevant IDs. Use read_strategy_guide separately for strategic comparisons. '
                'Current observations, scenario/mod rules and native quotes govern actual values; '
                'the executor contract governs supported operations. Classic defaults do not fill '
                'missing observations or create capabilities. Continue with the normal decision.\n'
                + json.dumps(self.catalog, ensure_ascii=False, separators=(',', ':')))


if __name__ == '__main__':
    import sys
    rules = GameRules(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ROOT)
    print(json.dumps({'bundle_sha256': rules.bundle_hash, 'files': rules.hashes,
                     'catalog': rules.catalog}, indent=2))
