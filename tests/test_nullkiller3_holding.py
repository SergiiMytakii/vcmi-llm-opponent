"""Passive holding keeps its defender and avoids ineffective repeated visits."""
import copy
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
from playtesting.runs import copy_snapshot_file
from playtesting.reports import native_records
from test_nullkiller3_campaign import campaign_records

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires an ordinary isolated NK3 bundle')
class NativeHoldingTest(unittest.TestCase):
    def test_stationed_defender_waits_without_repeated_visits_while_an_independent_scout_works(self):
        self.run_case(False)

    def test_stationed_defender_takes_usable_surplus_before_waiting(self):
        self.run_case(True)

    def run_case(self,surplus):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-holding-',dir=ROOT/'.build/playtests'))
        print('\nNK3 passive-holding evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        world=variants()['base'];objects=world['objects.json']
        for name in [k for k,v in objects.items() if v['type'] in ('monster','mine','resource')]:del objects[name]
        own=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='red')
        helper=copy.deepcopy(own);helper.update(x=6,y=12)
        helper['options'].update(type='christian',army=[dict(type='core:pikeman',amount=1)])
        objects['hero_900']=helper
        if surplus:
            town=next(v for v in objects.values() if v['type']=='town' and v['options']['owner']=='red')
            town['options']['army']=[dict(type='core:pikeman',amount=100)]
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3Holding.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        probe=ROOT/'tests/fixtures/nk3_holding_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/NK3Holding.vmap',references={},
            players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',controller=[sys.executable,str(probe)],
            controller_sources=[str(probe)],purpose='integration',case_id='nk3-passive-holding',headless=True,
            max_seconds=12,experience_mode='off')
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,'scripts/playtest.py','prepare','--config',str(path),'--out',str(run)],
                       check=True,capture_output=True)
        env=dict(os.environ);env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,'scripts/playtest.py','run','--run',str(run)],
                                   env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+17
                while child.poll() is None and time.monotonic()<deadline:
                    records=campaign_records(run)
                    if any(r['day']>=3 for r in records):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        records=campaign_records(run)
        self.assertTrue(records and 'hold' in records[0]['statuses'],'the simultaneous plan was not accepted: '+str(run))
        self.assertTrue(any(r['day']>=3 for r in records),'observation boundary was not reached: '+str(run))
        requests=sorted((json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')),
                        key=lambda r:int(r['request_id'].rsplit(':',1)[1]))
        defender,scout=requests[0]['observation']['heroes'][:2]
        self.assertEqual(defender['position'],requests[0]['observation']['towns'][0]['position'])
        for record in records:
            if record['day']<=3:
                self.assertEqual(record['heroes'][0]['position'],defender['position'],'holding diverted the defender')
        completed=next((r for r in records if r['statuses'].get('scout',{}).get('state')=='completed'),None)
        self.assertTrue(completed and completed['day']<=2,
                        'already-stationed defender starved the independent scout: '+str(run))
        self.assertTrue(any(r['heroes'][1]['position']!=scout['position'] for r in records if r['day']<=2),
                        'the scout did not execute its real movement')
        executions,errors=native_records(run/'engine-logs/VCMI_Client_log.txt','NK3_EXECUTION')
        self.assertEqual(errors,0,'incomplete execution evidence')
        if surplus:
            self.assertTrue(any(r['outcome']=='effects_observed'
                and r['action']['after']['heroes'][0]['army_value']>r['action']['before']['heroes'][0]['army_value']
                and r['action']['after']['towns'][0]['army_value']<r['action']['before']['towns'][0]['army_value']
                for r in executions),'holding skipped a real available army transfer')
        self.assertFalse(any(r['outcome']=='no_change_observed' and r['action'].get('goal_id')=='hold'
                             for r in executions),'passive holding emitted a redundant visit')


if __name__=='__main__':unittest.main()
