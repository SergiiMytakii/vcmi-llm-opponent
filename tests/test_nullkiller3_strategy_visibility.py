"""Player-visible model inputs, request necessity and fallback after movement."""
import copy
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from fixtures.fog_maps import variants
from test_nullkiller3_native import native_records, first_movement

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/playtest.py'
DATA=Path('Library/Application Support/vcmi')


def permitted_request(value):
    value=copy.deepcopy(value)
    value['memory'].pop('experience_id',None)
    # Stored strategy decisions retain their originating request ID. Only its
    # game/generation UUIDs vary between equivalent independent runs; retain
    # player, day, revision and request sequence for the behavioral comparison.
    uuid=r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    for result in value['memory'].get('recent_results',[]):
        action=result.get('action',{})
        if isinstance(action.get('request_id'),str):
            action['request_id']=re.sub(r'^'+uuid+':'+uuid+':',
                                        'game:generation:',action['request_id'],count=1)
    return {key:value[key] for key in ('observation','memory','campaign','signals','strategic_intent')}


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires separate NK3 build and private fog fixtures')
class StrategicVisibilityTest(unittest.TestCase):
    def test_model_inputs_after_scouting_and_timeout_fallback_ignore_hidden_variants(self):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-model-visibility-',dir=ROOT/'.build/playtests'))
        print('\nNK3 model visibility evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture)
        probe=ROOT/'tests/fixtures/nk3_strategy_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/NK3StrategyVisibility.vmap',
                      players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',references={},
                      controller=[sys.executable,str(probe)],controller_sources=[str(probe)],
                      purpose='integration',case_id='nk3-model-visibility',headless=True,max_seconds=25,
                      decision_timeout_seconds=1,experience_mode='off')
        config.pop('save_resource',None)
        results={}
        for mode in ('scout','timeout'):
            observations={}
            worlds=variants()
            for name,world in worlds.items():
                guard=next(v for v in world['objects.json'].values() if v['type']=='monster' and v['x']==9)
                guard['options']['amount']={'same_category':199,'different_category':251}.get(name,150)
                with zipfile.ZipFile(fixture/DATA/'Maps/NK3StrategyVisibility.vmap','w') as archive:
                    for filename,value in world.items():archive.writestr(filename,json.dumps(value))
                path=output/(mode+'-'+name+'.json');path.write_text(json.dumps(config));run=output/(mode+'-'+name)
                subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
                env=dict(os.environ,NK3_PROBE_MODE=mode,VCMI_AI_OPEN_MAP='0');env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
                with (run/'driver.log').open('w') as log:
                    child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
                    try:
                        deadline=time.monotonic()+30
                        while child.poll() is None and time.monotonic()<deadline:
                            records=native_records(run)
                            requests=list((run/'decisions').glob('*/request.json'))
                            if first_movement(records) is not None and (mode=='timeout' or len(requests)>=2):break
                            time.sleep(.03)
                    finally:
                        (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
                records=native_records(run);boundary=first_movement(records)
                self.assertIsNotNone(boundary,'no actual movement: '+str(run))
                requests=sorted((json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')),
                                key=lambda r:int(r['request_id'].rsplit(':',1)[1]))
                self.assertTrue(requests,'no strategic request: '+str(run))
                if mode=='scout':
                    self.assertGreaterEqual(len(requests),2,'no post-movement strategic view: '+str(run))
                    self.assertNotEqual(requests[0]['observation']['heroes'][0]['position'],
                                        requests[1]['observation']['heroes'][0]['position'])
                    checked=requests[:2]
                else:
                    self.assertEqual(sum(any(s['question']=='opening' for s in r['signals']) for r in requests),1)
                    checked=requests[:1]
                    outcomes=[json.loads(p.read_text()).get('status') for p in (run/'decisions').glob('*/result.json')]
                    self.assertIn('timeout',outcomes)
                observations[name]={'requests':[permitted_request(r) for r in checked],
                                    'native':records[:boundary+1]}
                launch=json.loads((run/'launch.json').read_text())
                self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
                self.assertTrue(json.loads((run/'report.json').read_text())['assignment_matches'])
            for name in ('hidden','hidden_insert','hidden_remove'):
                self.assertEqual(observations[name],observations['base'],mode+': '+name+' '+str(output))
            self.assertNotEqual(observations['different_category'],observations['base'])
            self.assertNotEqual(observations['same_category'],observations['base'])
            results[mode]=observations
        (output/'comparison.json').write_text(json.dumps(results,indent=2))


if __name__=='__main__':unittest.main()
