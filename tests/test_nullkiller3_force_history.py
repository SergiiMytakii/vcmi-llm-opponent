"""A real acknowledged force dip remains visible after immediate recruitment."""
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

from fixtures.fog_maps import variants
from playtesting.runs import copy_snapshot_file
from test_nullkiller3_campaign import campaign_records

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/playtest.py'


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_GARRISON_CONFIG'),
                     'requires a private garrison-state probe')
class NativeForceHistoryTest(unittest.TestCase):
    def test_acknowledged_dip_is_not_erased_by_recruitment_before_the_next_planning_pass(self):
        self.run_history(False)

    def test_survivor_returns_to_a_safe_owned_town_without_further_loss_when_the_model_reply_is_stale(self):
        self.run_history(True)

    def test_expired_failed_preservation_releases_its_live_force_reserve_and_retains_the_loss(self):
        self.run_history(True,expiry=True)

    def run_history(self,loss,expiry=False):
        config=json.loads(Path(os.environ['VCMI_NK3_GARRISON_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-force-history-',dir=ROOT/'.build/playtests'))
        print('\nNK3 force-history evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        world=variants()['base'];objects=world['objects.json']
        for name in [k for k,v in objects.items() if v['type']=='monster']:del objects[name]
        hero=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='red');hero.update(x=9,y=11)
        helper=copy.deepcopy(hero);helper.update(x=6,y=11)
        helper['options'].update(type='christian',army=[dict(type='core:'+kind,amount=1) for kind in
            ('imp','skeleton','goblin','troglodyte','gnoll','halfling','peasant')])
        objects['hero_garrison']=helper
        if expiry:
            enemy=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='blue')
            enemy['options']['army']=[dict(type='core:archangel',amount=1000)]
        town=next(v for v in objects.values() if v['type']=='town' and v['options']['owner']=='red')
        town['options']['buildings']['allOf']=['fort','townHall','dwellingLvl1']
        town['options']['buildings']['noneOf'] += [f'{prefix}{level}' for prefix in ('dwellingLvl','dwellingUpLvl')
            for level in range(1,8) if not (prefix=='dwellingLvl' and level==1)]
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3ForceHistory.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        probe=ROOT/'tests/fixtures/nk3_strategy_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/NK3ForceHistory.vmap',
            players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',purpose='integration',case_id='nk3-force-history',
            headless=True,max_seconds=25 if expiry else 15,references={},controller=[sys.executable,str(probe)],controller_sources=[str(probe)],experience_mode='off')
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        env=dict(os.environ,NK3_PROBE_MODE='force_history',VCMI_NK3_GARRISON_PROBE_MODE='force_loss' if loss else 'force_dip')
        env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+(30 if expiry else 20)
                while child.poll() is None and time.monotonic()<deadline:
                    records=campaign_records(run)
                    if not loss and any(r['day']>=2 for r in records):break
                    if loss and any(r['day']>=(7 if expiry else 3) for r in records):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        records=campaign_records(run);self.assertTrue(records,'preservation plan was not installed')
        initial=records[0]['heroes'][1]['army_value']
        text=(run/'engine-logs/VCMI_Client_log.txt').read_text(errors='replace')
        dip=re.search(r'NK3_TEST_DIP day=2 army=(\d+)',text)
        recovered=re.search(r'NK3_TEST_RECOVERED day=2 army=(\d+)',text)
        self.assertIsNotNone(dip,'no real acknowledged withdrawal')
        self.assertLess(int(dip[1]),initial)
        if not loss:
            self.assertIsNotNone(recovered,'no real acknowledged recruitment')
            self.assertGreater(int(recovered[1]),initial)
        fresh=next(r for r in records if r['day']==2)
        if not loss:self.assertGreater(fresh['heroes'][1]['army_value'],initial,'the dip was not repaired before planning')
        status=fresh['statuses']['hold']
        self.assertEqual(status['reason'],'force_floor_breached','recruitment erased an acknowledged preservation violation')
        self.assertEqual(status['observed_day'],2)
        self.assertEqual(status['observed_army_value'],int(dip[1]))
        requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
        self.assertTrue(any(s['question']=='commitment:hold' for r in requests for s in r['signals']),
                        'the violated commitment did not receive a critical strategic review')
        if loss:
            question=next(r for r in requests if r['identity']['day']==2)
            town=next(t for t in question['observation']['towns'] if t['ref']==question['campaign']['goals'][0]['target_ref'])
            hero=question['observation']['heroes'][1]
            self.assertLess(hero['army_value'],initial)
            self.assertLessEqual(max(abs(hero['position'][i]-town['position'][i]) for i in (0,1)),1,
                'the strategic wait began before the safe survivor return')
            returns=[]
            for result in question['memory']['recent_results']:
                action=result.get('action',{})
                if action.get('goal_id')!='hold' or action.get('acknowledgment')!='acknowledged':continue
                before=next((h for h in action.get('before',{}).get('heroes',[]) if h['ref']==hero['ref']),None)
                after=next((h for h in action.get('after',{}).get('heroes',[]) if h['ref']==hero['ref']),None)
                if before and after and before['position']!=after['position']:returns.append(result)
            self.assertTrue(returns,'the safe return was not acknowledged before the model request')
            route=next(r for r in question['observation']['forecasts']['routes'] if r['target_ref']==town['ref'])
            self.assertTrue(any(a['hero_ref']==hero['ref'] and a['day']==2 and a['army_loss_estimate']==0
                                for a in route['own_arrivals']),'fixture has no timely safe survivor route')
            self.assertTrue(any(r['day']==2 and max(abs(r['heroes'][1]['position'][i]-town['position'][i]) for i in (0,1))<=1
                                for r in records),'surviving hero stayed frozen outside the town after a failed strategic reply')
            self.assertTrue(all(r['heroes'][1]['army_value']>=int(dip[1]) for r in records if 2<=r['day']<=6),
                            'native stabilization spent more of the surviving force')
            self.assertTrue(all(r['statuses']['hold']['state']!='completed' for r in records),
                            'returning to safety falsely completed uninterrupted preservation')
            stale=[]
            for path in (run/'decisions').glob('*/request.json'):
                request=json.loads(path.read_text())
                if request['identity']['day']!=2:continue
                reply=json.loads((path.parent/'stdout.bin').read_bytes())
                result=json.loads((path.parent/'result.json').read_text())
                stale.append(reply['identity']!=request['identity'] and result['status']=='invalid_reply')
            self.assertTrue(any(stale),'the controller boundary did not reject the deliberately stale reply')
            report=json.loads((run/'report.json').read_text())
            self.assertTrue(any(r.get('day')==2 and r.get('accepted') is False
                                for r in report['native_strategy']),'native fallback was not observed')
        if expiry:
            expired=next((r for r in records if r['day']>=7 and r.get('forecasts')),None)
            self.assertIsNotNone(expired,'the live game did not reach the preservation deadline')
            state=expired['statuses']['hold']
            self.assertEqual(state['reason'],'deadline_missed','expired failure still holds the survivor')
            self.assertEqual(state['failure_reason'],'force_floor_breached')
            self.assertEqual(state['observed_army_value'],int(dip[1]))
            source=expired['heroes'][1]['ref']
            pool=next(p for p in expired['forecasts']['army_pools'] if source in p['aliases'])
            self.assertEqual(pool['reserved_value'],0,'expired force reserve still constrains native fallback')
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])


if __name__=='__main__':unittest.main()
