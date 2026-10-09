"""Question outcomes after actual native partial admission, without a game process."""
import copy
import json
import subprocess
import unittest

from test_background_native import DRIVER, fixture, heroes_fixture


def signal(question, facts='original', critical=False):
    return dict(question=question, facts=facts, critical=critical)


def questions(case, refs):
    case['request']['routine_needs'] = [dict(ref=ref, kind='town' if ref == 'object:1' else 'hero') for ref in refs]
    case['request']['signals'] = [signal('routine:' + ref) for ref in refs]
    case['request']['signals'].append(signal('campaign_exhausted'))
    case['pending_questions'] = copy.deepcopy(case['request']['signals'])
    return case


@unittest.skipUnless(DRIVER.is_file(), 'requires built native value driver')
class BackgroundQuestionCoverageTest(unittest.TestCase):
    def admit(self, case):
        result = subprocess.run([str(DRIVER)], input=json.dumps(case), text=True,
                                capture_output=True, check=True, timeout=15)
        value = json.loads(result.stdout)
        self.assertTrue(value['accepted'], value)
        return value['questions']

    def test_partial_acceptance_closes_only_the_covered_participants(self):
        case = questions(heroes_fixture(), ['object:1', 'object:0', 'hero:2'])
        case['fresh']['forecasts']['routes'][1]['own_arrivals'][0]['end_turn_exposure']['status'] = 'unknown'
        result = self.admit(case)
        self.assertEqual(result['resolved'], [signal('routine:object:1'), signal('routine:object:0')])
        self.assertEqual(result['pending'], [signal('campaign_exhausted'), signal('routine:hero:2')])

    def test_full_coverage_closes_exhaustion_and_preserves_unrelated_live_question(self):
        case = questions(heroes_fixture(), ['object:1', 'object:0', 'hero:2'])
        case['pending_questions'].append(signal('defense:other-town', 'new threat', True))
        result = self.admit(case)
        self.assertEqual(result['resolved'], case['request']['signals'])
        self.assertEqual(result['pending'], [signal('defense:other-town', 'new threat', True)])

    def test_changed_facts_keep_the_live_question_and_critical_flag(self):
        case = questions(fixture(), ['object:1'])
        case['pending_questions'][0] = signal('routine:object:1', 'changed', True)
        result = self.admit(case)
        self.assertEqual(result['resolved'], [signal('campaign_exhausted')])
        self.assertEqual(result['pending'], [signal('routine:object:1', 'changed', True)])

    def test_uncovered_need_keeps_exhaustion_open_even_when_all_groups_pass(self):
        case = questions(fixture(), ['object:1', 'object:0'])
        result = self.admit(case)
        self.assertEqual(result['resolved'], [signal('routine:object:1')])
        self.assertEqual(result['pending'], [signal('campaign_exhausted'), signal('routine:object:0')])

    def test_covered_routine_need_does_not_close_a_stale_strategic_question(self):
        for strategic, changed, expected_closed in ((False, False, False), (True, False, True), (True, True, False)):
            with self.subTest(strategic=strategic, changed=changed):
                case = questions(fixture(), ['object:1'])
                case['request']['strategic_review'] = strategic
                case['request']['signals'].append(signal('checkpoint:allocation'))
                if strategic:
                    case['reply']['alternatives'] = [
                        dict(approach='economy', benefit='Build', cost='Funds', uncertainty='Enemy'),
                        dict(approach='offense', benefit='Conquest', cost='Army', uncertainty='Route')]
                if changed:
                    case['fresh']['heroes'][0]['army_value'] = 1
                result = self.admit(case)
                self.assertEqual(signal('checkpoint:allocation') in result['resolved'], expected_closed)
                self.assertEqual(signal('checkpoint:allocation') in result['pending'], not expected_closed)
                self.assertIn(signal('routine:object:1'), result['resolved'])

    def test_missing_pending_question_is_added_when_its_need_is_uncovered(self):
        case = questions(fixture(), ['object:0'])
        case['pending_questions'] = []
        result = self.admit(case)
        self.assertEqual(result['resolved'], [])
        self.assertEqual(result['pending'], [signal('campaign_exhausted'), signal('routine:object:0')])

    def test_changed_exhaustion_facts_are_not_erased_by_full_coverage(self):
        case = questions(fixture(), ['object:1'])
        case['pending_questions'][-1] = signal('campaign_exhausted', 'new revision')
        result = self.admit(case)
        self.assertEqual(result['resolved'], [signal('routine:object:1')])
        self.assertEqual(result['pending'], [signal('campaign_exhausted', 'new revision')])

    def test_rejection_does_not_produce_question_resolution(self):
        case = questions(fixture(), ['object:1'])
        case['fresh']['day'] = 3
        result = subprocess.run([str(DRIVER)], input=json.dumps(case), text=True,
                                capture_output=True, check=True, timeout=15)
        value = json.loads(result.stdout)
        self.assertFalse(value['accepted'])
        self.assertNotIn('questions', value)


if __name__ == '__main__':
    unittest.main()
