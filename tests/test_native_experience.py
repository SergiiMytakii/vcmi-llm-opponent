"""Opt-in native proof: an own game-over event reaches durable learning."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

from codex_fixture import codex_fixture
from fixtures.fog_maps import variants

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('VCMI_NATIVE_EXPERIENCE_CONFIG'),
                     'requires an explicit private native fixture on macOS')
class NativeExperienceTest(unittest.TestCase):
    def test_terminal_event_is_assessed_and_stored_without_executing_an_extra_game_action(self):
        config = json.loads(Path(os.environ['VCMI_NATIVE_EXPERIENCE_CONFIG']).read_text())
        output = Path(tempfile.mkdtemp(prefix='experience-',dir=ROOT/'.build/playtests'))
        print('\nNative experience evidence:',output,flush=True)
        profile = output/'fixture'
        shutil.copytree(config['profile_template'],profile)
        data = variants()['base']
        data['header.json']['triggeredEvents'] = {
            'proofEnd':{'condition':['daysPassed',{'value':1}],
                        'effect':{'type':'defeat','messageToSend':'Fixture has ended.'},
                        'message':'Fixture has ended.'}}
        map_path = profile/'Library/Application Support/vcmi/Maps/ExperienceProof.vmap'
        with zipfile.ZipFile(map_path,'x') as archive:
            for name,value in data.items(): archive.writestr(name,json.dumps(value))
        fixture_env = codex_fixture(output,'''
import json,pathlib,sys
if sys.argv[1:] == ['--version']:
    print('codex-cli 0.160.0');sys.exit(0)
args=sys.argv;r=json.load(sys.stdin)
reply={'protocol':1,'request_id':r['request_id'],'action_id':'end','strategy':None}
if r.get('experience',{}).get('mode')=='learn':
    episodes=r['experience']['episodes']
    assessments=[{'episode_id':e['id'],'lesson_id':None,'verdict':'support',
      'rule':'Check the scenario victory and defeat conditions before choosing to wait.',
      'conditions':['tempo'],'evidence_ids':[e['signals'][0]['id']],
      'explanation':'The engine reports a terminal result after waiting; this fixture tests transport, not strategic causality.'} for e in episodes[:2]]
    reply['learning']={'expectation':'Wait for a fresh observation.','assessments':assessments}
pathlib.Path(args[args.index('-o')+1]).write_text(json.dumps(reply))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}))
''')
        config.update(profile_template=str(profile),map_resource='Maps/ExperienceProof.vmap',
                      controller=[sys.executable,str(ROOT/'controller/main.py')],
                      controller_sources=[str(ROOT/'controller'/p) for p in ('codex.py','experience.py','strategy.py','instructions.txt','model.json')],
                      references={},purpose='integration',case_id='experience-proof',headless=True,max_seconds=30,
                      decision_timeout_seconds=37,players={'red':'ExternalAI','blue':'EmptyAI'})
        config.pop('save_resource',None)
        config_path=output/'config.json';config_path.write_text(json.dumps(config))
        run=output/'run'
        subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(config_path),'--out',str(run)],check=True,capture_output=True)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(ROOT/'scripts/playtest.py'),'run','--run',str(run)],
                env={**os.environ,**fixture_env},stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+40
                final=None
                while child.poll() is None and time.monotonic()<deadline:
                    for path in run.glob('decisions/*/explanation.json'):
                        try:
                            info=json.loads(path.read_text())
                        except json.JSONDecodeError:
                            continue
                        if info.get('request_id','').endswith(':final'):
                            final=info
                            break
                    if final:break
                    time.sleep(.1)
            finally:
                (run/'STOP').touch(exist_ok=True)
                child.wait(timeout=15)
        self.assertEqual(child.returncode,0,(output/'driver.log').read_text())
        self.assertIsNotNone(final,str(output))
        self.assertEqual(final['provider'],'codex')
        self.assertGreater(final['experience']['lessons_updated'],0)
        native=(run/'engine-logs/VCMI_Client_log.txt').read_text(errors='replace')
        self.assertIn('ExternalAI final experience review player=0 outcome=loss delivered=1',native)
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete'])
        self.assertTrue(launch['protected_files_unchanged'])
        self.assertTrue((run/'experience.sqlite3').is_file())
