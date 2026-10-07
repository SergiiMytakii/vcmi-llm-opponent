"""Battle attribution through actual campaign execution and hostile turns."""
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

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/playtest.py'


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires the private NK3 runtime and licensed fixture')
class BattleAttributionTest(unittest.TestCase):
    def test_selected_interception_keeps_its_forecast_after_strategy_revision(self):
        self.run_case(False)

    def test_incoming_attack_on_helper_has_no_campaign_goal_or_selected_route(self):
        self.run_case(True)

    def run_case(self,incoming):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-battle-attribution-',dir=ROOT/'.build/playtests'))
        print('\nBattle attribution evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        world=variants()['base'];objects=world['objects.json']
        for name in [k for k,v in objects.items() if v['type'] in ('monster','resource','mine')]:del objects[name]
        hero=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='red')
        enemy=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='blue')
        if incoming:
            hero.update(x=6,y=20);hero['options']['army']=[dict(type='core:archangel',amount=1000)]
            town=next(v for v in objects.values() if v['type']=='town' and v['options']['owner']=='red')
            spare=copy.deepcopy(town);spare.update(x=7,y=20);objects['own_spare_town']=spare
            town.update(x=17,y=11)
            town['options']['buildings']['allOf']=['fort','townHall']
            town['options']['buildings']['noneOf'] += ['dwellingLvl'+str(i) for i in range(1,8)]
            helper=copy.deepcopy(hero);helper.update(x=16,y=11)
            helper['options'].update(type='christian',army=[dict(type='core:pikeman',amount=1)])
            objects['own_helper']=helper
            enemy.update(x=17,y=11);enemy['options']['army']=[dict(type='core:archangel',amount=30)]
        else:
            hero['options']['army']=[dict(type='core:archangel',amount=100)]
            enemy.update(x=10,y=11);enemy['options']['army']=[dict(type='core:pikeman',amount=20)]
        resource='Maps/NK3BattleAttribution.vmap'
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi'/resource,'w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        probe=ROOT/'tests/fixtures/nk3_strategy_probe.py'
        config.update(profile_template=str(fixture),map_resource=resource,
            players={'red':'Nullkiller3','blue':'Nullkiller2' if incoming else 'EmptyAI'},
            nk3_mode='model',references={},controller=[sys.executable,str(probe)],controller_sources=[str(probe)],
            purpose='integration',case_id='nk3-battle-attribution',headless=True,max_seconds=18,experience_mode='off')
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        env=dict(os.environ,NK3_PROBE_MODE='hold_helpers' if incoming else 'battle_attribution')
        env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        with (output/'driver.log').open('w') as log:
            subprocess.run([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=35)
        report=json.loads((run/'report.json').read_text());launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        self.assertTrue(report['assignment_matches'])
        battles=report['battle_comparisons']
        if incoming:
            battle=next((b for b in battles if b['origin']=='incoming_attack'),None)
            self.assertIsNotNone(battle,'no actual hostile attack was observed')
            self.assertEqual(battle['own_side'],'defender');self.assertIsNone(battle['goal_id'])
            self.assertIsNone(battle['forecast'])
            action=next(r['action'] for r in report['native_execution'] if r.get('sequence')==battle['sequence'])
            requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
            first=min(requests,key=lambda r:int(r['request_id'].rsplit(':',1)[1]))
            helper=min(first['observation']['heroes'],key=lambda h:h['army_value'])
            self.assertEqual(battle['actor_ref'],helper['ref'],'hostile battle was not against the helper')
        else:
            battle=next((b for b in battles if b['goal_id']=='named-interception'),None)
            self.assertIsNotNone(battle,'named goal produced no real battle')
            self.assertEqual(battle['origin'],'campaign_operation');self.assertEqual(battle['own_side'],'attacker')
            self.assertEqual(battle['campaign_revision'],1)
            self.assertEqual(battle['forecast']['allowed_loss_ratio'],.7)
            self.assertEqual(battle['forecast']['army_loss_estimate'],
                battle['forecast']['loss_estimate']['path_component']+battle['forecast']['loss_estimate']['target_component'])
            self.assertNotIn('engine_actor_ids',battle['forecast'])
            requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
            self.assertTrue(any(r['identity']['revision']>1 for r in requests),'no later campaign revision observed')
            receipt=next(result for request in requests for result in request['memory']['recent_results']
                         if result['action'].get('goal_id')=='named-interception' and result['action'].get('kind')=='battle')
            self.assertEqual(receipt['action']['campaign_revision'],1)
            self.assertFalse({'selected_route','battle_origin','own_side','battle_position'} & set(receipt['action']))


if __name__=='__main__':unittest.main()
