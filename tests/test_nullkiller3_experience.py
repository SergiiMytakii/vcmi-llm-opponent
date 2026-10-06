"""NK3's final own battle is durable even on an opponent turn."""
import os
import sys
import unittest
from test_native_experience import run_fixture


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires an ordinary private NK3 bundle')
class NativeStrategyExperienceTest(unittest.TestCase):
    def test_final_own_battle_win_is_collected_without_postgame_strategy(self):
        run_fixture(self,os.environ['VCMI_NK3_STRATEGY_CONFIG'],battle_win=True)

    def test_final_own_battle_loss_on_opponent_turn_is_collected(self):
        run_fixture(self,os.environ['VCMI_NK3_STRATEGY_CONFIG'],battle_loss=True)

    def test_two_native_players_keep_separate_own_episodes(self):
        run_fixture(self,os.environ['VCMI_NK3_STRATEGY_CONFIG'],two_players=True)


if __name__=='__main__':unittest.main()
