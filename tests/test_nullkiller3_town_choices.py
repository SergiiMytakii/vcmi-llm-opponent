"""Town departure, separate garrison and interception through real native tasks."""
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

@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'), 'requires private native bundle')
class TownChoicesTest(unittest.TestCase):
    def run_case(self, mode):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        out=Path(tempfile.mkdtemp(prefix='town-choice-'+mode+'-',dir=ROOT/'.build/playtests'))
        print('\nTown choice evidence:',out,flush=True)
        fixture=out/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        world=variants()['base'];objects=world['objects.json']
        for name in list(objects):
            if objects[name]['type'] not in ('hero','town') and name!='mine_7':del objects[name]
        objects['mine_7'].update(x=8,y=14)
        enemy=next(v for v in objects.values() if v['type']=='hero' and v['options']['owner']=='blue')
        if mode in ('prepare','recruit','detach'):
            del objects[next(k for k,v in objects.items() if v is enemy)]
        enemy.update(x=6 if mode=='near' else 11,y=12 if mode=='near' else 11);enemy['options']['army']=[dict(type='core:pikeman',amount=1)]
        with zipfile.ZipFile(fixture/'Library/Application Support/vcmi/Maps/TownChoices.vmap','w') as archive:
            for name,value in world.items():archive.writestr(name,json.dumps(value))
        controller=out/'controller.py';controller.write_text('''import json,sys
r=json.load(sys.stdin);w=r['observation'];h=w['heroes'][0]['ref'];t=w['towns'][0]['ref'];mode='''+repr(mode)+'''
if r.get('campaign') and not (mode=='reconsider' and r['campaign']['goals'][0]['kind']=='defend_area'):
 decision='retain';plan=None
else:
 if mode=='reconsider' and not r.get('campaign'):kind='defend_area';target=t;completion={'kind':'held_until','value':w['day']+1};floor=5000
 elif mode in ('prepare','recruit','detach'):kind='prepare_garrison';target=t;completion={'kind':'garrison_at_least','value':500 if mode=='recruit' else 1500};floor=5000
 elif mode=='intercept':kind='intercept_hero';target=next(o['ref'] for o in w['objects'] if o['kind']=='hero' and o['owner'] in w['enemy_players'] and o['visible']);completion={'kind':'enemy_engaged','value':0};floor=0
 else:kind='capture_target';target=next(o['ref'] for o in w['objects'] if o['kind']=='mine' and o['visible']);completion={'kind':'target_owned','value':w['player']};floor=0
 plan={'version':3,'revision':r['identity']['revision']+1,'approach':'offense','horizon_days':3,'goals':[{'id':'operation','kind':kind,'actor_ref':h,'target_ref':target,'deadline_day':w['day']+2,'priority':90,'building_id':-1,'min_army_value':floor,'depends_on':[],'required_capabilities':['land','transfer'] if kind=='prepare_garrison' else ['land'],'complete_when':completion}],'reserves':[],'policy':{'max_loss_ratio':.25,'allow_route_repair':True,'allow_helper_replacement':True,'critical_towns':[]}}
 if kind=='prepare_garrison':
  plan['goals'][0]['garrison_mode']='recruit_then_detach' if mode=='prepare' else mode
  mine=next(o['ref'] for o in w['objects'] if o['kind']=='mine' and o['visible'])
  plan['goals'].append({'id':'followup','kind':'capture_target','actor_ref':h,'target_ref':mine,'deadline_day':w['day']+2,'priority':80,'building_id':-1,'min_army_value':5000,'depends_on':['operation'],'required_capabilities':['land'],'complete_when':{'kind':'target_owned','value':w['player']}})
 decision='revise'
print(json.dumps({'protocol':2,'request_id':r['request_id'],'identity':r['identity'],'decision':decision,'reason':'Controlled native integration operation','evidence_refs':['observation:day'],'victory_method':'Validate the supported owned operation','assignments':[{'hero_ref':h,'role':'main'}],'alternatives':[{'approach':'offense','benefit':'Operate','cost':'Movement','uncertainty':'Enemy intent unknown'},{'approach':'defense','benefit':'Hold','cost':'Delay','uncertainty':'Enemy route unknown'}],'reconsider_when':[{'goal_id':'operation','kind':'deadline_missed'}],'plan':plan,'usage':{'input_tokens':0,'output_tokens':0,'known':True}}))
''')
        config.update(profile_template=str(fixture),map_resource='Maps/TownChoices.vmap',players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',references={},purpose='integration',case_id='town-choice-'+mode,headless=True,max_seconds=20,review_interval_days=2 if mode=='reconsider' else 1,experience_mode='off',controller=[sys.executable,str(controller)],controller_sources=[str(controller)])
        config.pop('save_resource',None)
        path=out/'config.json';path.write_text(json.dumps(config));run=out/'game'
        subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        with (out/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(ROOT/'scripts/playtest.py'),'run','--run',str(run)],stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+25
                while child.poll() is None and time.monotonic()<deadline:
                    state=run/'turn-review/state.json'
                    if state.exists() and json.loads(state.read_text()).get('status')=='paused':break
                    time.sleep(.05)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        launch=json.loads((run/'launch.json').read_text());self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        records=campaign_records(run);self.assertTrue(records,'no own native observations')
        requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
        if mode not in ('prepare','recruit','detach'):self.assertTrue(any(o['kind']=='hero' and o['owner']==1 and o['visible'] for r in requests for o in r['observation']['objects']),'fixture enemy not visible')
        self.assertTrue(any(r['revision']>=1 for r in records),'controlled campaign rejected')
        return run,records,requests

    def test_distant_visible_raider_does_not_prevent_mine_capture(self):
        run,records,_=self.run_case('depart')
        self.assertTrue(any(r['statuses'].get('operation',{}).get('state')=='completed' for r in records),'far raider held the main instead of capturing mine: '+str(run))
        self.assertNotEqual(records[-1]['heroes'][0]['position'],[5,11,0])

    def test_separate_garrison_recruits_and_detaches_without_spending_main_floor(self):
        run,records,_=self.run_case('prepare')
        self.assertTrue(any(r['statuses'].get('operation',{}).get('state')=='completed' for r in records),'separate garrison never prepared: '+str(run))
        last=records[-1];hero=last['heroes'][0];town=last['towns'][0]
        self.assertGreaterEqual(hero['army_value'],5000)
        self.assertNotEqual(town['army_holder_ref'],hero['ref'])
        self.assertGreaterEqual(town['defense_value'],1500)
        self.assertTrue(any(r['statuses'].get('followup',{}).get('state')=='completed' for r in records),'main did not continue after preparing garrison: '+str(run))
        self.assertLess(hero['army_value'],records[0]['heroes'][0]['army_value'],'missing stock did not cause a partial detachment')
        self.assertLess(last['resources'][6],records[0]['resources'][6],'garrison stock was not purchased')

    def test_recruit_only_keeps_main_army_intact(self):
        run,records,_=self.run_case('recruit')
        self.assertTrue(any(r['statuses'].get('operation',{}).get('state')=='completed' for r in records),str(run))
        self.assertTrue(all(r['heroes'][0]['army_value']>=records[0]['heroes'][0]['army_value'] for r in records),
                        'recruit-only preparation removed main creatures')
        self.assertGreaterEqual(records[-1]['towns'][0]['defense_value'],500)

    def test_detach_only_uses_main_creatures_without_recruiting(self):
        run,records,_=self.run_case('detach')
        self.assertTrue(any(r['statuses'].get('operation',{}).get('state')=='completed' for r in records),str(run))
        first,last=records[0],records[-1]
        self.assertGreaterEqual(last['heroes'][0]['army_value'],5000)
        self.assertGreaterEqual(last['towns'][0]['defense_value'],1500)
        executed,errors=native_records(run/'engine-logs/VCMI_Client_log.txt','NK3_EXECUTION');self.assertEqual(errors,0)
        split=[r['action'] for r in executed if r.get('action',{}).get('goal_id')=='operation' and 'after' in r['action']]
        self.assertTrue(split,'detachment task not executed')
        for action in split:
            self.assertEqual(action['before']['resources'],action['after']['resources'])
            self.assertEqual(action['after']['towns'][0]['army_value']-action['before']['towns'][0]['army_value'],
                             action['before']['heroes'][0]['army_value']-action['after']['heroes'][0]['army_value'])

    def test_finished_hold_reconsiders_while_main_is_still_in_town(self):
        run,records,requests=self.run_case('reconsider')
        followups=[r for r in requests if r.get('campaign')
                   and r['campaign']['goals'][0]['kind']=='defend_area']
        self.assertTrue(followups,'completed holding plan was not reconsidered')
        self.assertEqual(followups[0]['observation']['heroes'][0]['position'],[5,11,0],
                         'native departed before GPT could compare town choices')
        self.assertTrue(followups[0]['observation']['forecasts']['town_choices'])
        self.assertTrue(any(s['question']=='campaign_exhausted' for s in followups[0]['signals']))
        self.assertTrue(any(r['statuses'].get('operation',{}).get('state')=='completed'
                            and r['statuses']['operation'].get('completed_day')==2 for r in records))

    def test_adjacent_visible_enemy_keeps_native_town_defense(self):
        run,records,_=self.run_case('near')
        self.assertFalse(any(r['statuses'].get('operation',{}).get('state')=='completed' for r in records),
                         'direct nearby threat failed to protect the town: '+str(run))
        self.assertTrue(all(r['heroes'][0]['position']==[5,11,0] for r in records))

    def test_interception_completes_only_after_exact_enemy_battle(self):
        run,records,_=self.run_case('intercept')
        self.assertTrue(any(r['statuses'].get('operation',{}).get('state')=='completed' for r in records),'enemy engagement not confirmed: '+str(run))
        log=(run/'runtime.log').read_text()
        self.assertIn('"outcome" : "battle_won"',log)

if __name__=='__main__':unittest.main()
