"""Independent rules and advice access through the controller and real MCP servers."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest
from codex_fixture import codex_fixture
from test_strategy_guide import MODEL, final_reply
from test_nullkiller3_controller import strategic_request

ROOT = Path(__file__).resolve().parents[1]


class GameRulesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name); self.request = strategic_request()
        self.env = {**os.environ, **codex_fixture(self.folder, MODEL),
            'CAPTURE': str(self.folder), 'FINAL_REPLY': json.dumps(final_reply(self.request)),
            'VCMI_EXPERIENCE_MODE': 'off', 'VCMI_STRATEGY_GUIDE_MODE': 'on',
            'VCMI_GAME_RULES_MODE': 'on', 'VCMI_PLAYTEST_DECISION_DIR': str(self.folder)}
        for key in ('VCMI_STRATEGY_GUIDE', 'VCMI_GAME_RULES', 'GUIDE_TEST_MODE', 'RULES_TEST_MODE'):
            self.env.pop(key, None)

    def exchange(self):
        return subprocess.run([sys.executable, str(ROOT/'controller/main.py')],
            input=json.dumps(self.request), text=True, capture_output=True, timeout=10, env=self.env)

    def test_rules_and_advice_have_separate_catalogs_tools_and_audits(self):
        self.env.update(RULES_TEST_MODE='consult', GUIDE_TEST_MODE='consult')
        result = self.exchange()
        self.assertEqual(result.returncode, 0, result.stderr)
        info = json.loads(result.stderr)
        self.assertEqual(info['game_rules']['requested_ids'], ['day_and_week', 'town_economy'])
        self.assertEqual(info['strategy_guide']['requested_ids'], ['opening', 'defense'])
        tools = json.loads((self.folder/'game_rules-tools.json').read_text())['result']['tools']
        self.assertEqual([t['name'] for t in tools], ['read_game_rules'])
        rules = json.loads(json.loads((self.folder/'rules-result.json').read_text())['result']['content'][0]['text'])
        self.assertEqual([r['id'] for r in rules], ['day_and_week', 'town_economy'])
        self.assertEqual(rules[0]['text'], (ROOT/'controller/game_rules/rules/day_and_week.md').read_text())
        instructions = json.loads((self.folder/'call-1.json').read_text())['instructions']
        self.assertIn('# Game rules catalog', instructions)
        self.assertIn('# Strategy guide catalog', instructions)
        self.assertNotIn(rules[0]['text'], instructions)
        self.assertEqual(len(list(self.folder.glob('call-*.json'))), 1)
        self.assertEqual(json.loads(result.stdout)['identity'], self.request['identity'])

    def test_rules_can_be_read_with_strategy_guide_off(self):
        self.env.update(VCMI_STRATEGY_GUIDE_MODE='off', RULES_TEST_MODE='consult')
        result = self.exchange()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stderr)['strategy_guide']['mode'], 'off')
        instructions = json.loads((self.folder/'call-1.json').read_text())['instructions']
        self.assertIn('# Game rules catalog', instructions)
        self.assertNotIn('# Strategy guide catalog', instructions)

    def test_strategy_guide_can_be_read_with_rules_off(self):
        self.env.update(VCMI_GAME_RULES_MODE='off', GUIDE_TEST_MODE='consult')
        result = self.exchange()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stderr)['game_rules']['mode'], 'off')
        instructions = json.loads((self.folder/'call-1.json').read_text())['instructions']
        self.assertNotIn('# Game rules catalog', instructions)
        self.assertIn('# Strategy guide catalog', instructions)

    def test_strategy_ids_are_not_accepted_by_rules_tool(self):
        self.env.update(RULES_TEST_MODE='consult', RULES_TEST_IDS='["opening"]')
        result = self.exchange()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('error', json.loads((self.folder/'rules-result.json').read_text()))

    def test_invalid_rules_bundle_blocks_model_before_any_call(self):
        rules = self.folder/'rules'; shutil.copytree(ROOT/'controller/game_rules', rules)
        (rules/'rules/day_and_week.md').write_bytes(b'x'*4097)
        self.env['VCMI_GAME_RULES'] = str(rules)
        result = self.exchange()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertEqual(list(self.folder.glob('call-*.json')), [])


class GameRulesRunsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.run = self.root/'run'
        data = self.root/'profile/Library/Application Support/vcmi'
        (data/'Maps').mkdir(parents=True); (data/'config').mkdir()
        (data/'Maps/Test.h3m').write_bytes(b'test'); (data/'config/settings.json').write_text('{}')
        self.rules = self.root/'rules'
        shutil.copytree(ROOT/'controller/game_rules', self.rules)
        self.settings = dict(version=1, case_id='rules', purpose='integration', engine=sys.executable,
            profile_template=str(self.root/'profile'), map_resource='Maps/Test.h3m',
            controller=[sys.executable, str(ROOT/'controller/main.py')], players={'red':'Nullkiller3'},
            max_seconds=1, experience_mode='off', strategy_guide={'mode':'off'},
            game_rules={'mode':'on', 'path':str(self.rules)})

    def prepare(self):
        from playtesting.runs import prepare
        config = self.root/'config.json'; config.write_text(json.dumps(self.settings))
        return prepare(config, self.run)

    def test_prepared_rules_are_frozen_consumed_and_checked_before_decision(self):
        from playtesting.runs import verify
        from playtesting.controller import exchange
        from unittest.mock import patch
        manifest = self.prepare()
        self.assertEqual(manifest['game_rules']['mode'], 'on')
        original = (self.rules/'rules/day_and_week.md').read_text()
        (self.rules/'rules/day_and_week.md').write_text('Changed original')
        verify(self.run)
        request = strategic_request()
        env = {**codex_fixture(self.root, MODEL), 'CAPTURE':str(self.root),
            'FINAL_REPLY':json.dumps(final_reply(request)), 'RULES_TEST_MODE':'consult',
            'VCMI_GAME_RULES':str(self.rules), 'VCMI_GAME_RULES_MODE':'off'}
        with patch.dict(os.environ, env):
            output, result = exchange(self.run, json.dumps(request).encode())
            self.assertEqual(result['status'], 'reply_valid', result)
            self.assertEqual(json.loads(output)['identity'], request['identity'])
            sections = json.loads(json.loads((self.root/'rules-result.json').read_text())['result']['content'][0]['text'])
            self.assertEqual(sections[0]['text'], original)
            (self.run/'game-rules/rules/day_and_week.md').write_text('Changed snapshot')
            output, result = exchange(self.run, json.dumps(request).encode())
        self.assertEqual(output, b'')
        self.assertEqual(result['status'], 'recording_error')
        self.assertIn('game rules', result['error'])
        self.assertEqual(len(list(self.root.glob('call-*.json'))), 1)

    def test_off_and_legacy_manifests_do_not_enable_inherited_rules(self):
        from playtesting.runs import verify
        from playtesting.controller import exchange
        from unittest.mock import patch
        self.settings['game_rules'] = {'mode':'off'}
        manifest = self.prepare()
        self.assertEqual(manifest['game_rules'], {'mode':'off'})
        self.assertFalse((self.run/'game-rules').exists())
        del manifest['game_rules']
        (self.run/'manifest.json').write_text(json.dumps(manifest))
        verify(self.run)
        request = strategic_request()
        env = {**codex_fixture(self.root, MODEL), 'CAPTURE':str(self.root),
            'FINAL_REPLY':json.dumps(final_reply(request)), 'VCMI_GAME_RULES_MODE':'on',
            'VCMI_GAME_RULES':str(self.rules)}
        with patch.dict(os.environ, env):
            output, result = exchange(self.run, json.dumps(request).encode())
        self.assertEqual(result['status'], 'reply_valid', result)
        instructions = json.loads((self.root/'call-1.json').read_text())['instructions']
        self.assertNotIn('# Game rules catalog', instructions)

    def test_added_rules_snapshot_file_is_detected(self):
        from playtesting.runs import verify
        self.prepare(); (self.run/'game-rules/rules/extra.md').write_text('Extra')
        with self.assertRaisesRegex(ValueError, 'game rules'): verify(self.run)

    def test_recorder_cancels_rules_tool_without_a_game_reply(self):
        from playtesting.controller import exchange
        from unittest.mock import patch
        self.settings['decision_timeout_seconds'] = .7
        self.prepare(); request = strategic_request()
        env = {**codex_fixture(self.root, MODEL), 'CAPTURE':str(self.root),
            'FINAL_REPLY':json.dumps(final_reply(request)), 'RULES_TEST_MODE':'consult_timeout'}
        with patch.dict(os.environ, env):
            output, result = exchange(self.run, json.dumps(request).encode())
        self.assertEqual(output, b''); self.assertEqual(result['status'], 'timeout', result)
        self.assertTrue((self.root/'tool-pid').is_file())
        if os.name != 'nt':
            import time
            for filename in ('model-pid', 'tool-pid'):
                pid = int((self.root/filename).read_text())
                for _ in range(50):
                    try: os.kill(pid, 0)
                    except ProcessLookupError: break
                    time.sleep(.02)
                else: self.fail('cancelled fixture process remains alive: '+filename)


if __name__ == '__main__': unittest.main()
