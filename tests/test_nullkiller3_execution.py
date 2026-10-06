"""Native consequences reach the next common strategic request."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import shutil
from playtesting.runs import copy_snapshot_file

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/playtest.py'


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires a private NK3 bundle')
class NativeExecutionTest(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('VCMI_NK3_TURN_LOSS_CONFIG'),'requires the private command-save probe')
    def test_save_inside_a_native_movement_reconciles_unknown_effects_before_fresh_tasks(self):
        self.run_movement_save(False)

    @unittest.skipUnless(os.environ.get("VCMI_NK3_TURN_LOSS_CONFIG"),"requires the private command-save probe")
    def test_unfinished_saved_command_does_not_prove_uninterrupted_force_preservation(self):
        self.run_movement_save(True)

    def run_movement_save(self,preserving):
        config=json.loads(Path(os.environ['VCMI_NK3_TURN_LOSS_CONFIG']).read_text())
        ordinary=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-native-command-save-',dir=ROOT/'.build/playtests'))
        print('\nNK3 native-command save evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        settings=fixture/'Library/Application Support/vcmi/config/settings.json'
        values=json.loads(settings.read_text());values.setdefault('adventure',{})['enemyMoveTime']=500
        settings.write_text(json.dumps(values))
        config.update(profile_template=str(fixture),players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='native',
            references={},purpose='integration',case_id='nk3-native-command-save',headless=False,max_seconds=25,experience_mode='off')
        config.pop('save_resource',None)
        if preserving:
            import zipfile
            from fixtures.fog_maps import variants
            world=variants()['base']
            objects=world['objects.json']
            for name in [k for k,v in objects.items() if v['type']=='monster']:del objects[name]
            hero=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='red')
            hero.update(x=9,y=13)
            enemy=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='blue')
            enemy['options']['army']=[dict(type='core:archangel',amount=1000)]
            with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3ForceContinuity.vmap','w') as archive:
                for name,value in world.items():archive.writestr(name,json.dumps(value))
            config['map_resource']='Maps/NK3ForceContinuity.vmap'
            from test_nullkiller3_campaign import seed_campaign
            campaign=seed_campaign();campaign['reserves']=[]
            campaign['goals']=[dict(id='hold',kind='preserve_force',actor_ref='object:0',target_ref='object:1',
                deadline_day=6,priority=75,building_id=-1,min_army_value=1000,depends_on=[],
                required_capabilities=['land'],complete_when=dict(kind='force_preserved_until',value=6))]
            seed=output/'campaign.json';seed.write_text(json.dumps(campaign))
        def prepare(name):
            path=output/(name+'.json');path.write_text(json.dumps(config));run=output/name
            subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
            return run
        first=prepare('moving');logfile=first/'engine-logs/VCMI_Client_log.txt'
        env=dict(os.environ,VCMI_NK3_TURN_LOSS_PROBE_MODE='movement_save');env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        if preserving:env['VCMI_NK3_SEED_CAMPAIGN']=str(seed)
        with (first/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(first)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+30
                while child.poll() is None and time.monotonic()<deadline:
                    if logfile.exists() and 'NK3_TEST_NATIVE_SAVE' in logfile.read_text(errors='replace'):break
                    time.sleep(.03)
            finally:
                (first/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        text=logfile.read_text(errors='replace')
        self.assertTrue('NK3_TEST_NATIVE_SAVE day=1' in text,'no acknowledged movement checkpoint: '+str(first))
        for name in ('engine','engine_sources'):config[name]=ordinary[name]
        config.update(profile_template=str(first/'profile'),save_resource='Saves/NK3NativeCommandProbe.vsgm1',headless=True,max_seconds=6)
        env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        restored=prepare('restored')
        subprocess.run([sys.executable,str(CLI),'run','--run',str(restored)],env=env,check=True,capture_output=True,timeout=25)
        report=json.loads((restored/'report.json').read_text())
        recovered=[r for r in report['native_execution'] if r['action'].get('acknowledgment')=='recovered_unknown']
        self.assertEqual(len(recovered),1,'pending native task was lost or reconciled repeatedly')
        result=recovered[0];self.assertEqual(result['outcome'],'reconciled_unknown')
        before=result['action']['before']['heroes'][0]['position'];after=result['action']['after']['heroes'][0]['position']
        self.assertNotEqual(before,after,'saved movement had no acknowledged effect')
        from test_nullkiller3_native import native_records
        self.assertEqual(native_records(restored)[0]['heroes'][0]['position'],after,'fresh planning reused the pre-movement position')
        self.assertTrue(any(r['action'].get('acknowledgment')=='acknowledged' for r in report['native_execution'][1:]),'restored game could not continue useful native tasks')
        if preserving:
            from test_nullkiller3_campaign import campaign_records
            records=campaign_records(restored)
            self.assertTrue(records,'the saved preservation intention was discarded')
            self.assertTrue(all(r['statuses']['hold']['state']!='completed' for r in records),
                'the recovered endpoint falsely proved uninterrupted force preservation')
            unknown=next((r for r in records if r['statuses']['hold']['reason']=='force_continuity_unconfirmed'),None)
            self.assertIsNotNone(unknown,'the unfinished interval was treated as confirmed history')
            self.assertEqual(unknown['statuses']['hold']['unconfirmed_since_day'],1)
        for run in (first,restored):
            launch=json.loads((run/'launch.json').read_text())
            self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
            self.assertFalse(list((run/'decisions').glob('*/request.json')),'native save/load called a model')

    def test_confirmed_building_cost_and_result_reach_the_next_shared_model_request(self):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-execution-',dir=ROOT/'.build/playtests'))
        print('\nNK3 execution evidence:',output,flush=True)
        probe=ROOT/'tests/fixtures/nk3_strategy_probe.py'
        config.update(players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',references={},
                      controller=[sys.executable,str(probe)],controller_sources=[str(probe)],purpose='integration',
                      case_id='nk3-execution',headless=True,max_seconds=15,experience_mode='off')
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        def requests():
            return sorted((json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')),
                          key=lambda r:int(r['request_id'].rsplit(':',1)[1]))
        env=dict(os.environ,NK3_PROBE_MODE='valid');env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+20
                while child.poll() is None and time.monotonic()<deadline:
                    if len(requests())>=2:break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        items=requests();self.assertGreaterEqual(len(items),2,'no post-building strategic request')
        history=items[1]['memory'].get('recent_results',[])
        building=next((r for r in history if r.get('action',{}).get('kind')=='build'),None)
        self.assertIsNotNone(building,'confirmed native construction did not enter shared result memory')
        self.assertEqual(building['outcome'],'effects_observed')
        action=building['action'];self.assertEqual(action['goal_id'],'guild')
        option=next(b for b in items[0]['observation']['towns'][0]['building_options'] if b['id']==0)
        self.assertEqual(action['resource_delta'],[-v for v in option['cost']],
                         'reported construction cost differs from the acknowledged resource change')
        self.assertEqual(action['resource_flows']['coverage'],'complete')
        self.assertEqual(action['resource_flows']['debits'],option['cost'])
        self.assertEqual(action['resource_flows']['credits'],[0]*7)
        self.assertTrue(any(0 in t['buildings'] for t in action['after']['towns']))
        self.assertFalse(any(0 in t['buildings'] for t in action['before']['towns']))
        report=json.loads((run/'report.json').read_text())
        reported=next((r for r in report.get('native_execution',[]) if r.get('action',{}).get('goal_id')=='guild'),None)
        self.assertIsNotNone(reported,'the run report omitted confirmed native consequences')
        self.assertEqual(reported['action']['resource_delta'],action['resource_delta'])
        self.assertEqual(reported['action']['resource_flows'],action['resource_flows'])
        self.assertEqual(reported['outcome'],'effects_observed')
        self.assertGreaterEqual(report['native_metrics']['accepted_responses'],1)
        self.assertGreaterEqual(report['native_metrics']['requests_by_player_day'].get('0:1',0),1)
        self.assertIsNotNone(report['native_metrics']['wait_ms_median'])
        self.assertIsNotNone(report['native_metrics']['wait_ms_p95'])
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])


if __name__=='__main__':unittest.main()
