"""Failed commitments release funds for real native continuation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from test_nullkiller3_campaign import campaign_records

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/playtest.py'


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_CAMPAIGN_CONFIG'),
                     'requires a private NK3 fixture')
class NativeFallbackTest(unittest.TestCase):
    def test_expired_building_commitment_releases_funds_for_native_spending(self):
        config=json.loads(Path(os.environ['VCMI_NK3_CAMPAIGN_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-expired-fallback-',dir=ROOT/'.build/playtests'))
        print('\nNK3 expired-fallback evidence:',output,flush=True)
        goal=dict(id='capital',kind='develop_town',actor_ref=None,target_ref='object:1',deadline_day=1,
                  priority=80,building_id=13,min_army_value=0,depends_on=[],required_capabilities=['build'],
                  complete_when=dict(kind='building_present',value=13))
        seed=dict(version=3,revision=1,approach='economy',horizon_days=3,goals=[goal],
                  reserves=[dict(goal_id='capital',resources=[0,0,0,0,0,0,10000],force_value=0)],
                  policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=['object:1']))
        seed_path=output/'campaign.json';seed_path.write_text(json.dumps(seed))
        config.update(players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='native',experience_mode='off',purpose='integration',
                      case_id='nk3-expired-fallback',headless=True,max_seconds=20,references={})
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],
                                   env=dict(os.environ,VCMI_NK3_SEED_CAMPAIGN=str(seed_path)),stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+25
                while child.poll() is None and time.monotonic()<deadline:
                    if any(r['day']>=3 for r in campaign_records(run)):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        records=campaign_records(run)
        expired=[r for r in records if r['statuses']['capital']['reason']=='deadline_missed']
        self.assertTrue(expired,'fixture did not miss a real building deadline: '+str(run))
        self.assertTrue(all(r['reserves']==[0]*7 for r in expired),'expired reserve froze native funds')
        day1=[r for r in records if r['day']==1]
        self.assertTrue(day1)
        available=day1[-1]['resources'][6]+1000
        self.assertTrue(any(r['day']==2 and r['resources'][6]<available for r in expired),
                        'native did not spend released funds in the next turn: '+str(run))
        self.assertFalse(list((run/'decisions').glob('*/request.json')),'native fallback called a model')
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])


if __name__=='__main__':unittest.main()
