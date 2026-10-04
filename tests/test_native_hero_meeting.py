"""Real own-hero movement must close the engine dialog without exchanging armies."""
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
from fixtures.fog_maps import variants

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('VCMI_NATIVE_STRATEGY_CONFIG'),
                     'requires an explicit private native fixture on macOS')
class NativeHeroMeetingTest(unittest.TestCase):
    def test_own_hero_encounter_closes_dialog_and_the_next_turn_runs_without_transfers(self):
        config = json.loads(Path(os.environ['VCMI_NATIVE_STRATEGY_CONFIG']).read_text())
        output = Path(tempfile.mkdtemp(prefix='hero-meeting-', dir=ROOT/'.build/playtests'))
        print('\nNative hero meeting evidence:', output, flush=True)
        fixture = output/'fixture'
        shutil.copytree(config['profile_template'], fixture)
        world = variants()['base']
        town = next(o for o in world['objects.json'].values() if o['type']=='town' and o['options']['owner']=='red')
        town['options']['buildings']['allOf'].append('tavern')
        town['options']['buildings']['noneOf'].remove('tavern')
        hero = next(o for o in world['objects.json'].values() if o['type']=='hero' and o['options']['owner']=='red')
        hero.update(x=6,y=13)
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/HeroMeeting.vmap','x') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        config.update(profile_template=str(fixture),map_resource='Maps/HeroMeeting.vmap',
                      controller=[sys.executable,str(ROOT/'tests/fixtures/hero_meeting_probe.py')],
                      controller_sources=[],references={},purpose='integration',case_id='hero-meeting',
                      experience_mode='off',headless=True,max_seconds=15,decision_timeout_seconds=18,
                      players={'red':'ExternalAI','blue':'EmptyAI'})
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config))
        run=output/'run'
        subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        requests={}
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(ROOT/'scripts/playtest.py'),'run','--run',str(run)],stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+20
                while child.poll() is None and time.monotonic()<deadline:
                    for request_path in run.glob('decisions/*/request.json'):
                        try:r=json.loads(request_path.read_text())
                        except json.JSONDecodeError:continue
                        requests[r['request_id']]=r
                    if '0:2:0' in requests:break
                    time.sleep(.1)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        self.assertEqual(child.returncode,0,(output/'driver.log').read_text())
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        log=(run/'engine-logs/VCMI_Client_log.txt').read_text(errors='replace')
        self.assertIn('ExchangeDialog',log,'fixture did not exercise the hero meeting')
        self.assertTrue('0:2:0' in requests, 'an unresolved hero dialog blocked the next turn: '+', '.join(requests))
        before,after=requests['0:1:1'],requests['0:1:2']
        self.assertEqual({h['id']:h['army'] for h in before['observation']['heroes']},
                         {h['id']:h['army'] for h in after['observation']['heroes']})
        self.assertNotEqual(after['observation']['heroes'][0]['position'],before['observation']['heroes'][0]['position'])
        self.assertFalse('has to answer queries before attempting' in log, 'engine still has an unresolved query')


if __name__=='__main__':unittest.main()
