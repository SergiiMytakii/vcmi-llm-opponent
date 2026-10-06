"""Known late delivery is explained while the deadline can still be revised."""
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
class NativeDeadlineTest(unittest.TestCase):
    def test_late_known_route_is_reported_before_the_deadline_expires(self):
        self.run_case(False)

    def test_timely_known_route_still_completes_its_delivery(self):
        self.run_case(True)

    def run_case(self,timely):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-deadline-',dir=ROOT/'.build/playtests'))
        print('\nNK3 deadline evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        world=variants()['base'];objects=world['objects.json']
        for name in [k for k,v in objects.items() if v['type'] in ('monster','mine','resource')]:del objects[name]
        town=next(v for v in objects.values() if v['type']=='town' and v['options']['owner']=='red')
        for name,x in [('town_middle',15),('town_source',24)]:
            objects[name]=copy.deepcopy(town);objects[name]['x']=x
        objects['town_source']['options']['army']=[dict(type='core:pikeman',amount=100)]
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3Deadline.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        probe=ROOT/'tests/fixtures/nk3_deadline_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/NK3Deadline.vmap',references={},
            players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',controller=[sys.executable,str(probe)],
            controller_sources=[str(probe)],purpose='integration',case_id='nk3-known-late-delivery',headless=True,
            max_seconds=12,experience_mode='off')
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,'scripts/playtest.py','prepare','--config',str(path),'--out',str(run)],
                       check=True,capture_output=True)
        env=dict(os.environ,NK3_DEADLINE_MODE='timely' if timely else 'late');env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,'scripts/playtest.py','run','--run',str(run)],
                                   env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+17
                while child.poll() is None and time.monotonic()<deadline:
                    records=campaign_records(run)
                    if timely and any(r['statuses'].get('supply',{}).get('state')=='completed' for r in records):break
                    if not timely and any(r['day']>=2 for r in records):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        records=campaign_records(run)
        self.assertTrue(records and 'supply' in records[0]['statuses'],'delivery intent was not accepted: '+str(run))
        requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
        if timely:
            self.assertTrue(any(r['statuses'].get('supply',{}).get('state')=='completed' for r in records),
                            'a timely native delivery was suppressed: '+str(run))
            self.assertFalse(any('deadline_unreachable' in s['facts'] for r in requests for s in r['signals']),
                             'a supported timely delivery produced a deadline failure')
            return
        late=[x for r in records if r['day']==1 and isinstance(r.get('forecasts'),dict)
              for x in r['forecasts']['deliveries']
              if x['goal_id']=='supply' and x['status']=='late_on_current_route']
        self.assertTrue(late and late[0]['arrival_day']>1,'fixture has no established late route: '+str(run))
        reviewed=[r for r in requests if r['identity']['day']==1
                  and any('deadline_unreachable' in s['facts'] for s in r['signals'])]
        self.assertEqual(len(reviewed),1,'known late delivery must expose its deadline reason before expiry: '+str(run))
        executions,errors=native_records(run/'engine-logs/VCMI_Client_log.txt','NK3_EXECUTION')
        self.assertEqual(errors,0)
        self.assertFalse(any(r['day']==1 and r['action'].get('goal_id')=='supply'
                             and r['outcome']=='effects_observed' for r in executions),
                         'an already-late delivery consumed the current turn')


if __name__=='__main__':unittest.main()
