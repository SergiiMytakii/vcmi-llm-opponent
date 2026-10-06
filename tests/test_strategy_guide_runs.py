"""Prepared runs consume immutable guide snapshots through the recorder."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from playtesting.runs import prepare, verify
from playtesting.controller import exchange
from codex_fixture import codex_fixture
from test_strategy_guide import MODEL, final_reply
from test_nullkiller3_controller import strategic_request

ROOT=Path(__file__).resolve().parents[1]

class StrategyGuideRunsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.run=self.root/'run'
        data=self.root/'profile/Library/Application Support/vcmi'
        (data/'Maps').mkdir(parents=True);(data/'config').mkdir()
        (data/'Maps/Test.h3m').write_bytes(b'test');(data/'config/settings.json').write_text('{}')
        self.guide=self.root/'guide';shutil.copytree(ROOT/'controller/strategy_guide',self.guide)
        self.settings=dict(version=1,case_id='guide',purpose='integration',engine=sys.executable,
            profile_template=str(self.root/'profile'),map_resource='Maps/Test.h3m',
            controller=[sys.executable,str(ROOT/'controller/main.py')],players={'red':'Nullkiller3'},
            max_seconds=1,experience_mode='off',strategy_guide={'mode':'on','path':str(self.guide)})
        self.config=self.root/'config.json'

    def prepare(self):
        self.config.write_text(json.dumps(self.settings));return prepare(self.config,self.run)

    def test_original_edit_does_not_change_snapshot_and_snapshot_tampering_blocks_decision(self):
        manifest=self.prepare()
        pinned=manifest['strategy_guide']
        self.assertEqual(pinned['mode'],'on')
        self.assertIn(str(ROOT/'controller/strategy_guide.py'),manifest['controller_sources'])
        original=(self.guide/'rules/opening.md').read_bytes()
        (self.guide/'rules/opening.md').write_text('Changed original, not the run')
        self.assertEqual((self.run/'strategy-guide/rules/opening.md').read_bytes(),original)
        verify(self.run)
        request=strategic_request()
        env={**codex_fixture(self.root,MODEL),'CAPTURE':str(self.root),
            'FINAL_REPLY':json.dumps(final_reply(request)),'GUIDE_TEST_MODE':'consult',
            'VCMI_STRATEGY_GUIDE':str(self.guide),'VCMI_STRATEGY_GUIDE_MODE':'off'}
        from unittest.mock import patch
        with patch.dict(os.environ,env):
            output,result=exchange(self.run,json.dumps(request).encode())
            self.assertEqual(result['status'],'reply_valid',result)
            self.assertEqual(json.loads(output)['identity'],request['identity'])
            call=json.loads((self.root/'call-2.json').read_text())
            self.assertNotIn('Changed original',call['instructions'])
            (self.run/'strategy-guide/rules/opening.md').write_text('Changed snapshot')
            output,result=exchange(self.run,json.dumps(request).encode())
            self.assertEqual(output,b'');self.assertEqual(result['status'],'recording_error')
            self.assertIn('strategy guide',result['error'])
            self.assertEqual(len(list(self.root.glob('call-*.json'))),2)

    def test_recorder_cancels_the_second_call_without_a_game_reply(self):
        self.settings['decision_timeout_seconds']=.7
        self.prepare();request=strategic_request()
        env={**codex_fixture(self.root,MODEL),'CAPTURE':str(self.root),
            'FINAL_REPLY':json.dumps(final_reply(request)),'GUIDE_TEST_MODE':'second_timeout'}
        from unittest.mock import patch
        with patch.dict(os.environ,env):
            output,result=exchange(self.run,json.dumps(request).encode())
        self.assertEqual(output,b'')
        self.assertEqual(result['status'],'timeout',result)
        self.assertTrue((self.root/'second-pid').is_file(),'second call must have started')
        if os.name!='nt':
            import time
            pid=int((self.root/'second-pid').read_text())
            # The recorder terminates the owned controller group; the OS reaps its children.
            for _ in range(50):
                try:os.kill(pid,0)
                except ProcessLookupError:break
                time.sleep(.02)
            else:self.fail('cancelled fixture model remains alive')
        decision=next((self.run/'decisions').iterdir())
        self.assertTrue((decision/'model-call-1/codex-events.jsonl').is_file())

    def test_added_snapshot_file_is_detected(self):
        self.prepare();(self.run/'strategy-guide/rules/extra.md').write_text('Extra')
        with self.assertRaisesRegex(ValueError,'strategy guide'):verify(self.run)

    def test_explicit_off_is_recorded_without_snapshot(self):
        self.settings['strategy_guide']={'mode':'off'}
        self.assertEqual(self.prepare()['strategy_guide'],{'mode':'off'})
        self.assertFalse((self.run/'strategy-guide').exists())
        verify(self.run)

if __name__=='__main__':unittest.main()
