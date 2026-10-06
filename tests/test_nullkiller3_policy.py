"""Accepted risk policy also constrains independent native opportunities."""
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
from test_nullkiller3_campaign import campaign_records,seed_campaign

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/playtest.py'


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_CAMPAIGN_CONFIG'),
                     'requires an ordinary private NK3 bundle')
class NativePolicyTest(unittest.TestCase):
    def test_zero_loss_policy_blocks_unassigned_native_combat_while_useful_play_continues(self):
        self.run_policy(False)

    def test_acknowledged_combat_casualties_are_reported_separately_from_native_task_net_changes(self):
        self.run_policy(True)

    def test_unexpected_acknowledged_battle_loss_receives_one_critical_review_without_a_preservation_goal(self):
        self.run_policy(True,unexpected=True)

    def test_survivor_of_unexpected_combat_loss_starts_a_safe_return_before_the_critical_model_wait(self):
        self.run_policy(True,unexpected=True,stabilization=True)

    def test_unexpected_combat_loss_stops_the_old_composition_before_further_exploration(self):
        self.run_policy(True,unexpected=True,stabilization=True,interruption=True)

    def run_policy(self,combat_report,unexpected=False,stabilization=False,interruption=False):
        config=json.loads(Path(os.environ['VCMI_NK3_CAMPAIGN_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-risk-policy-',dir=ROOT/'.build/playtests'))
        print('\nNK3 risk-policy evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        world=variants()['base'];objects=world['objects.json']
        guard=next(v for v in objects.values() if v['type']=='monster')
        for name in [k for k,v in objects.items() if v['type']=='monster']:del objects[name]
        guard.update(x=8,y=13,subtype='archer')
        guard['template']['animation']='AVWARCH';guard['template']['editorAnimation']='AVWARCH'
        guard['options']['amount']=25
        objects['guard']=guard
        hero=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='red')
        hero['options']['army']=[dict(type='core:pikeman',amount=600),dict(type='core:archer',amount=20)]
        enemy=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='blue')
        enemy['options']['army']=[dict(type='core:archangel',amount=1000)]
        town=next(v for v in objects.values() if v['type']=='town' and v['options']['owner']=='red')
        town['options']['buildings']['allOf']=['fort','townHall']
        town['options']['buildings']['noneOf'] += [f'{prefix}{level}' for prefix in ('dwellingLvl','dwellingUpLvl') for level in range(1,8)]
        gold=next(v for v in objects.values() if v['type']=='resource' and v['subtype']=='gold' and v['x']<20)
        gold.update(x=7,y=13);gold['options']['amount']=20000
        for name in [k for k,v in objects.items() if v['type'] in ('resource','mine') and v['x']<20 and v is not gold]:del objects[name]
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/NK3RiskPolicy.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        config.update(profile_template=str(fixture),map_resource='Maps/NK3RiskPolicy.vmap',
            players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='native',purpose='integration',
            case_id='nk3-risk-policy',headless=True,max_seconds=15,references={},experience_mode='off')
        config.pop('save_resource',None)
        if unexpected:
            probe=ROOT/'tests/fixtures/nk3_strategy_probe.py'
            config.update(nk3_mode='model',controller=[sys.executable,str(probe)],controller_sources=[str(probe)])
        results={}
        cases=[('permissive',.01 if unexpected else .5)] if combat_report else [('permissive',.5),('strict',0)]
        for name,ratio in cases:
            seed=seed_campaign();seed['goals']=seed['goals'][:1];seed['reserves']=[]
            seed['policy']['max_loss_ratio']=ratio
            seed_path=output/(name+'-campaign.json');seed_path.write_text(json.dumps(seed))
            path=output/(name+'.json');path.write_text(json.dumps(config));run=output/name
            subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
            with (run/'driver.log').open('w') as log:
                child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],
                    env=dict(os.environ,VCMI_NK3_SEED_CAMPAIGN=str(seed_path),NK3_PROBE_MODE='retain_seed'),stdout=log,stderr=subprocess.STDOUT)
                try:
                    deadline=time.monotonic()+20
                    while child.poll() is None and time.monotonic()<deadline:
                        if any(r['day']>=3 for r in campaign_records(run)):break
                        time.sleep(.03)
                finally:
                    (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
            report=json.loads((run/'report.json').read_text())
            text=(run/'engine-logs/VCMI_Client_log.txt').read_text(errors='replace')
            records=campaign_records(run)
            self.assertTrue(records,'accepted policy was not installed: '+name)
            self.assertTrue(any(r['day']>=2 for r in records),'fixture did not complete a native turn: '+name)
            effects=[r for r in report['native_execution'] if r['outcome']=='effects_observed']
            losses=[]
            for effect in effects:
                action=effect['action'];before=sum(h['army_value'] for h in action['before']['heroes'])
                after=sum(h['army_value'] for h in action['after']['heroes'])
                if after<before:losses.append(action)
            results[name]=(records,effects,losses,'Starting battle of' in text)
            launch=json.loads((run/'launch.json').read_text())
            self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
            if not unexpected:self.assertFalse(list((run/'decisions').glob('*/request.json')),'native policy invoked a model')
        self.assertTrue(results['permissive'][3],'fixture exposed no ordinary native combat opportunity')
        self.assertTrue(results['permissive'][2],'fixture did not expose an army loss')
        if combat_report:
            battle=next((r for r in report['native_execution'] if r.get('action',{}).get('kind')=='battle'),None)
            self.assertIsNotNone(battle,'a confirmed battle was reduced to an unattributed task net change')
            self.assertEqual(battle['outcome'],'battle_won')
            self.assertEqual(report['native_metrics']['battle_outcomes'],{'battle_won':1})
            self.assertEqual(report['native_metrics']['own_battle_loss_value'],battle['action']['army_loss_value'])
            action=battle['action'];self.assertEqual(action['actor_ref'],'object:0')
            self.assertEqual(action['source'],'own_battle_result')
            self.assertGreater(action['army_loss_value'],0)
            task_loss=results['permissive'][2][0]
            if interruption:
                survivor=next(h for h in task_loss['after']['heroes'] if h['ref']==action['actor_ref'])
                self.assertEqual(survivor['position'],[7,13,0],
                    'the old composition continued beyond the acknowledged guarded visit after excessive casualties')
                self.assertEqual(task_loss['acknowledgment'],'replan_after_combat')
            net_loss=sum(h['army_value'] for h in task_loss['before']['heroes'])-sum(h['army_value'] for h in task_loss['after']['heroes'])
            self.assertEqual(action['army_loss_value'],net_loss,'acknowledged casualty value disagrees with the observed own-army loss')
            self.assertLessEqual(action['army_loss_value'],action['army_value_before'])
            self.assertEqual(action['army_loss_value'],sum({0:89,2:117}[c['creature_id']]*c['count'] for c in action['own_casualties']),
                'casualties do not use the pinned public creature values')
            if unexpected:
                self.assertGreater(action['army_loss_value'],action['army_value_before']*.01,
                    'fixture did not breach the accepted combat-loss budget')
                requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
                reviews=[r for r in requests if any(s['question'].startswith('battle_loss:') for s in r['signals'])]
                self.assertEqual(len(reviews),1,'an unexpected acknowledged loss was not reviewed exactly once: '+str(run))
                self.assertTrue(any(s['critical'] for s in reviews[0]['signals'] if s['question'].startswith('battle_loss:')))
                self.assertTrue(any(r['outcome']=='battle_won' and r['action'].get('army_loss_value')==action['army_loss_value']
                    for r in reviews[0]['memory']['recent_results']),'the request lost its actual combat evidence')
                self.assertTrue(any(r['day']>=2 for r in records),'native play stopped after the combat review')
                if stabilization:
                    request=reviews[0]
                    hero=next(h for h in request['observation']['heroes'] if h['ref']==action['actor_ref'])
                    town=request['observation']['towns'][0]
                    returns=[r for r in request['memory']['recent_results'] if r['action'].get('stabilization')=='unexpected_own_combat_loss'
                        and r['action'].get('acknowledgment')=='acknowledged' and r['outcome']=='effects_observed']
                    self.assertTrue(returns,'no acknowledged survivor return preceded the critical model request')
                    returned=returns[-1]['action']
                    before=next(h for h in returned['before']['heroes'] if h['ref']==hero['ref'])
                    after=next(h for h in returned['after']['heroes'] if h['ref']==hero['ref'])
                    distance=lambda h:sum(abs(h['position'][i]-town['position'][i]) for i in (0,1))
                    self.assertLess(distance(after),distance(before),'the survivor did not progress toward the safe town')
                    self.assertEqual(after['army_value'],before['army_value'],'the safe return lost further own troops')
                    self.assertEqual(hero['position'],after['position'],'unrelated movement followed stabilization before the model wait')
            return
        self.assertFalse(results['strict'][3],'an unassigned native opportunity bypassed the accepted zero-loss policy')
        self.assertTrue(results['strict'][1],'risk filtering removed useful native work')


if __name__=='__main__':unittest.main()
