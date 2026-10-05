"""Repeated actual handoff attempts need a meaningful strategic review."""
import copy
import hashlib
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
class NativeStagnationTest(unittest.TestCase):
    def test_unproductive_handoff_is_reviewed_after_two_own_days(self):
        self.run_case(False)

    def test_renumbering_the_same_stalled_handoff_does_not_repeat_the_review(self):
        self.run_case(True)

    def test_changing_the_source_pledge_repairs_and_completes_the_stalled_delivery(self):
        self.run_case(False,repair=True)

    def test_saved_stagnation_clock_and_addressed_question_survive_a_real_game_load(self):
        self.run_case(False,restoring=True)

    def run_case(self,renumber,repair=False,restoring=False):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-handoff-stagnation-',dir=ROOT/'.build/playtests'))
        print('\nNK3 handoff stagnation evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        world=variants()['base'];objects=world['objects.json']
        for name in [k for k,v in objects.items() if v['type'] in ('monster','mine','resource')]:del objects[name]
        town=next(v for v in objects.values() if v['type']=='town' and v['options']['owner']=='red')
        town['options']['army']=[dict(type='core:pikeman',amount=100)]
        town['options']['buildings']['allOf']=['fort','townHall']
        town['options']['buildings']['noneOf'] += [f'{prefix}{level}' for prefix in ('dwellingLvl','dwellingUpLvl') for level in range(1,8)]
        hero=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='red')
        hero.update(x=9,y=11)
        helper=copy.deepcopy(hero);helper.update(x=5,y=12)
        helper['options'].update(type='christian',army=[dict(type='core:pikeman',amount=100)])
        objects['hero_helper']=helper
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3HandoffStagnation.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        probe=ROOT/'tests/fixtures/nk3_stagnation_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/NK3HandoffStagnation.vmap',references={},
            players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',controller=[sys.executable,str(probe)],
            controller_sources=[str(probe)],purpose='integration',case_id='nk3-handoff-stagnation',headless=not restoring,
            max_seconds=18,experience_mode='off')
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,'scripts/playtest.py','prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        env=dict(os.environ,NK3_STAGNATION_MODE='release' if repair else 'renumber' if renumber else 'retain');env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        if restoring:env['NK3_STAGNATION_SAVE_GATE']=str(output/'save-completed')
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,'scripts/playtest.py','run','--run',str(run)],env=env,stdin=subprocess.PIPE if restoring else None,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+23;sent=False
                while child.poll() is None and time.monotonic()<deadline:
                    if restoring:
                        requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
                        if not sent and any(any(s['question']=='stagnation:operations' for s in r['signals']) for r in requests):
                            child.stdin.write(b'save Saves/NK3OperationClock\n');child.stdin.flush();sent=True
                        logfile=run/'engine-logs/VCMI_Client_log.txt'
                        if sent and 'Game has been successfully saved!' in logfile.read_text(errors='replace'):
                            save=run/'profile/Library/Application Support/vcmi/Saves/NK3OperationClock.vsgm1'
                            self.assertTrue(save.is_file() and save.stat().st_size>0,'completed checkpoint has no bytes')
                            digest=hashlib.sha256(save.read_bytes()).hexdigest();time.sleep(.03)
                            self.assertEqual(hashlib.sha256(save.read_bytes()).hexdigest(),digest,'checkpoint bytes were still changing')
                            recovery=output/'NK3OperationClock-recovery.vsgm1';copy_snapshot_file(save,recovery)
                            self.assertEqual(hashlib.sha256(recovery.read_bytes()).hexdigest(),digest)
                            receipt=dict(source_run_id=json.loads((run/'manifest.json').read_text())['run_id'],
                                         save_resource='Saves/NK3OperationClock.vsgm1',sha256=digest,recovery=str(recovery),boundary='own-day-3 strategic wait')
                            (output/'checkpoint.json').write_text(json.dumps(receipt,indent=2)+'\n')
                            break
                    elif any(r['day']>=4 for r in campaign_records(run)):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
                if child.stdin:child.stdin.close()
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        records=campaign_records(run)
        self.assertTrue(records and 'deliver' in records[0]['statuses'],'delivery intent was not accepted: '+str(run))
        executions,errors=native_records(run/'engine-logs/VCMI_Client_log.txt','NK3_EXECUTION');self.assertEqual(errors,0)
        repeats=[r for r in executions if r['action'].get('goal_id')=='deliver' and r['outcome']=='no_change_observed']
        self.assertTrue(all(sum(r['day']==day for r in repeats)>=2 for day in (1,2)),
                        'fixture has no admitted repeated ineffective handoff: '+str(run))
        requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
        reviews=[r for r in requests if any(s['question'].startswith('stagnation:') for s in r['signals'])]
        self.assertEqual(len(reviews),1,'ineffective handoff must receive one semantic review: '+str(run))
        self.assertEqual(reviews[0]['identity']['day'],3,'two own days must precede the review')
        self.assertFalse(any(r['day']>=3 for r in repeats),'a retained stalled intent kept repeating ineffective visits: '+str(run))
        if renumber:
            self.assertTrue(any('deliver2' in r['statuses'] for r in records),'renumbered equivalent strategy was not accepted')
        if repair:
            completed=next((r for r in records if r['statuses'].get('deliver',{}).get('state')=='completed'),None)
            self.assertIsNotNone(completed,'changed source pledge did not re-enable the physical delivery: '+str(run))
            receipt=next(d for d in completed['confirmed_deliveries'] if d['goal']['id']=='deliver')
            self.assertEqual(receipt['day'],3);self.assertGreaterEqual(receipt['recipient_after'],6000)
            self.assertGreaterEqual(receipt['source_after'],8700);self.assertLess(receipt['source_after'],8900)
        if restoring:
            self.assertTrue(sent,'checkpoint was not requested while the own strategic exchange waited')
            self.assertIn('Game has been successfully saved!',(run/'engine-logs/VCMI_Client_log.txt').read_text(errors='replace'))
            config.update(profile_template=str(run/'profile'),save_resource='Saves/NK3OperationClock.vsgm1',headless=True,max_seconds=12)
            path=output/'restored.json';path.write_text(json.dumps(config));resumed=output/'restored'
            subprocess.run([sys.executable,'scripts/playtest.py','prepare','--config',str(path),'--out',str(resumed)],check=True,capture_output=True)
            self.assertEqual(json.loads((resumed/'manifest.json').read_text())['save_sha256'],receipt['sha256'])
            env.pop('NK3_STAGNATION_SAVE_GATE',None)
            with (output/'restored-driver.log').open('w') as log:
                child=subprocess.Popen([sys.executable,'scripts/playtest.py','run','--run',str(resumed)],env=env,stdout=log,stderr=subprocess.STDOUT)
                try:
                    deadline=time.monotonic()+17
                    while child.poll() is None and time.monotonic()<deadline:
                        if any(r['day']>=5 for r in campaign_records(resumed)):break
                        time.sleep(.03)
                finally:
                    (resumed/'STOP').touch(exist_ok=True);child.wait(timeout=15)
            restored=campaign_records(resumed)
            self.assertTrue(restored and restored[0]['day']==3,'checkpoint did not preserve the exact stalled own day: '+str(resumed))
            self.assertTrue(any(r['day']>=5 for r in restored),'load did not complete another own day with a fresh wait budget')
            receipt.update(restored_run_id=json.loads((resumed/'manifest.json').read_text())['run_id'],restored_day=restored[0]['day'])
            (output/'checkpoint.json').write_text(json.dumps(receipt,indent=2)+'\n')
            executed,errors=native_records(resumed/'engine-logs/VCMI_Client_log.txt','NK3_EXECUTION');self.assertEqual(errors,0)
            self.assertFalse(any(r['action'].get('goal_id')=='deliver' for r in executed),'a stalled saved handoff replayed after load')
            self.assertFalse(list((resumed/'decisions').glob('*/request.json')),'the saved addressed question was requested again')
            launch=json.loads((resumed/'launch.json').read_text())
            self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])

if __name__=='__main__':unittest.main()
