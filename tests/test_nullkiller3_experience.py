"""Real NK3 terminal evidence reaches the existing experience owner."""
import os
import sys
import unittest
import test_native_experience as native_experience


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires an ordinary private NK3 bundle')
class NativeStrategyExperienceTest(unittest.TestCase):
    def test_win_in_a_real_final_battle_reaches_learning_without_blocking_terminal_cleanup(self):
        native_experience.NativeExperienceTest.run_terminal(self,os.environ['VCMI_NK3_STRATEGY_CONFIG'],
            'Nullkiller3',battle_win_final=True)

    def test_defeat_in_a_real_battle_on_the_opponent_turn_reaches_terminal_learning(self):
        native_experience.NativeExperienceTest.run_terminal(self,os.environ['VCMI_NK3_STRATEGY_CONFIG'],
            'Nullkiller3',battle_loss_final=True)

    def test_own_terminal_result_is_assessed_after_game_commands_have_stopped(self):
        native_experience.NativeExperienceTest.run_terminal(self,os.environ['VCMI_NK3_STRATEGY_CONFIG'],'Nullkiller3')

    def test_stop_cancels_the_separate_postgame_model_after_game_command_cleanup(self):
        native_experience.NativeExperienceTest.run_terminal(self,os.environ['VCMI_NK3_STRATEGY_CONFIG'],'Nullkiller3',cancel_final=True)

    def test_two_native_players_reflect_only_their_separate_own_execution(self):
        native_experience.NativeExperienceTest.run_terminal(self,os.environ['VCMI_NK3_STRATEGY_CONFIG'],'Nullkiller3',native_opponent=True)

    def test_native_lessons_retain_the_public_rule_version_and_execution_mechanism(self):
        native_experience.NativeExperienceTest.run_terminal(self,os.environ['VCMI_NK3_STRATEGY_CONFIG'],'Nullkiller3',check_context=True)


if __name__=='__main__':unittest.main()
