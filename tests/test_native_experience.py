"""Opt-in native proof: an own game-over event reaches durable learning."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from contextlib import closing

from codex_fixture import codex_fixture
from fixtures.fog_maps import variants

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('VCMI_NATIVE_EXPERIENCE_CONFIG'),
                     'requires an explicit private native fixture on macOS')
class NativeExperienceTest(unittest.TestCase):
    def test_terminal_event_is_assessed_and_stored_without_executing_an_extra_game_action(self):
        self.run_terminal(os.environ['VCMI_NATIVE_EXPERIENCE_CONFIG'],'ExternalAI')

    def run_terminal(self,config_path,actor,cancel_final=False,native_opponent=False,check_context=False,battle_loss_final=False,battle_win_final=False):
        config = json.loads(Path(config_path).read_text())
        output = Path(tempfile.mkdtemp(prefix='experience-',dir=ROOT/'.build/playtests'))
        print('\nNative experience evidence:',output,flush=True)
        profile = output/'fixture'
        from playtesting.runs import copy_snapshot_file
        shutil.copytree(config['profile_template'],profile,copy_function=copy_snapshot_file)
        (output/'model-inputs').mkdir()
        data = variants()['base']
        data['header.json']['triggeredEvents'] = {
            'proofEnd':{'condition':['daysPassed',{'value':1}],
                        'effect':{'type':'defeat','messageToSend':'Fixture has ended.'},
                        'message':'Fixture has ended.'}}
        if battle_loss_final or battle_win_final:
            data=variants()['base']
            for name in [k for k,v in data['objects.json'].items() if v['type'] in ('monster','mine','resource')]:
                del data['objects.json'][name]
            hero=next(v for v in data['objects.json'].values() if v['type']=='hero' and v['options']['owner']=='red')
            hero['options']['army']=[dict(type='core:pikeman' if battle_loss_final else 'core:archangel',
                                        amount=1 if battle_loss_final else 1000)]
            enemy=next(v for v in data['objects.json'].values() if v['type']=='hero' and v['options']['owner']=='blue')
            enemy.update(x=9 if battle_loss_final else 11,y=13 if battle_loss_final else 11)
            enemy['options']['army']=[dict(type='core:archangel' if battle_loss_final else 'core:pikeman',
                                         amount=1000 if battle_loss_final else 1)]
            if battle_win_final:
                enemy_town=next(v for v in data['objects.json'].values() if v['type']=='town' and v['options']['owner']=='blue')
                enemy_town.update(x=12,y=11)
        map_path = profile/'Library/Application Support/vcmi/Maps/ExperienceProof.vmap'
        with zipfile.ZipFile(map_path,'x') as archive:
            for name,value in data.items(): archive.writestr(name,json.dumps(value))
        fixture_env = codex_fixture(output,'''
import json,os,pathlib,sys,time
if sys.argv[1:] == ['--version']:
    print('codex-cli 0.160.0');sys.exit(0)
args=sys.argv;r=json.load(sys.stdin)
if r.get('observation',{}).get('terminal_result'):
    pathlib.Path(os.environ['NK3_TEST_INPUT_DIRECTORY'],str(r['observation']['player'])+'.json').write_text(json.dumps(r))
if r.get('observation',{}).get('terminal_result') and int(os.environ.get('NK3_TEST_FINAL_DELAY','0')):
    pathlib.Path(os.environ['NK3_TEST_FINAL_STARTED']).touch()
    time.sleep(int(os.environ['NK3_TEST_FINAL_DELAY']))
reply={'protocol':1,'request_id':r['request_id'],'action_id':'end','strategy':None}
if r['protocol']==2:
    town=r['observation']['towns'][0]['ref'];day=r['observation']['day']
    goal=dict(id='guild',kind='develop_town',actor_ref=None,target_ref=town,deadline_day=day+3,priority=80,
        building_id=0,min_army_value=0,depends_on=[],required_capabilities=['build'],
        complete_when=dict(kind='building_present',value=0))
    if os.environ.get('NK3_TEST_FINAL_BATTLE_LOSS')=='1':
        hero=r['observation']['heroes'][0]
        goal.update(id='home',kind='defend_area',actor_ref=hero['ref'],building_id=-1,
            min_army_value=89,required_capabilities=['land'],complete_when=dict(kind='held_until',value=day+2))
    if os.environ.get('NK3_TEST_FINAL_BATTLE_WIN')=='1':
        hero=r['observation']['heroes'][0]
        enemy=next(o for o in r['observation']['visible_objects'] if o['kind']=='town' and o['owner']==1)
        goal.update(id='capture',kind='capture_target',actor_ref=hero['ref'],target_ref=enemy['ref'],
            building_id=-1,required_capabilities=['land'],complete_when=dict(kind='target_owned',value=0))
    plan=dict(version=3,revision=r['identity']['revision']+1,approach='economy',horizon_days=5,goals=[goal],reserves=[],
        policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=[town]))
    reply=dict(protocol=2,request_id=r['request_id'],identity=r['identity'],decision='revise',reason='Develop own town',
        evidence_refs=['town:'+town],victory_method='Prepare owned forces for conquest',assignments=[],
        alternatives=[dict(approach='economy',benefit='Develop',cost='Building',uncertainty='Future threats unknown'),
                      dict(approach='offense',benefit='Advance',cost='Army',uncertainty='Enemy strength unknown')],
        reconsider_when=[dict(goal_id='guild',kind='deadline_missed')],plan=plan)
    if os.environ.get('NK3_TEST_FINAL_BATTLE_LOSS')=='1':
        reply['assignments']=[dict(hero_ref=hero['ref'],role='defender',goal_ids=['home'])]
        reply['reconsider_when']=[dict(goal_id='home',kind='deadline_missed')]
    if os.environ.get('NK3_TEST_FINAL_BATTLE_WIN')=='1':
        reply['assignments']=[dict(hero_ref=hero['ref'],role='main',goal_ids=['capture'])]
        reply['reconsider_when']=[dict(goal_id='capture',kind='deadline_missed')]
    if r.get('campaign'):reply.update(decision='retain',plan=None)
if r.get('experience',{}).get('mode')=='learn':
    episodes=r['experience']['episodes']
    assessments=[{'episode_id':e['id'],'lesson_id':None,'verdict':'support',
      'rule':'Check the scenario victory and defeat conditions before choosing to wait.',
      'conditions':['tempo'],'evidence_ids':[e['signals'][0]['id']],
      'explanation':'The engine reports a terminal result after waiting; this fixture tests transport, not strategic causality.'} for e in episodes[:2]]
    reply['learning']={'expectation':'Wait for a fresh observation.','assessments':assessments}
pathlib.Path(args[args.index('-o')+1]).write_text(json.dumps(reply))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}))
''')
        config.update(profile_template=str(profile),map_resource='Maps/ExperienceProof.vmap',
                      controller=[sys.executable,str(ROOT/'controller/main.py')],
                      controller_sources=[str(ROOT/'controller'/p) for p in ('codex.py','experience.py','strategy.py','instructions.txt','model.json',
                          'native_strategy.py','native_instructions.txt','prompt_context.py','batch.py')],
                      references={},purpose='integration',case_id='experience-proof',headless=True,max_seconds=30,
                      decision_timeout_seconds=37,players={'red':actor,'blue':'Nullkiller3' if native_opponent else 'EmptyAI'},experience_mode='learn')
        if actor=='Nullkiller3':config['nk3_mode']='model'
        else:config.pop('nk3_mode',None)
        if battle_loss_final:config['players']['blue']='Nullkiller2'
        config.pop('save_resource',None)
        config_path=output/'config.json';config_path.write_text(json.dumps(config))
        run=output/'run'
        subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(config_path),'--out',str(run)],check=True,capture_output=True)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(ROOT/'scripts/playtest.py'),'run','--run',str(run)],
                env={**os.environ,**fixture_env,'NK3_TEST_FINAL_DELAY':'20' if cancel_final else '0',
                     'NK3_TEST_FINAL_BATTLE_LOSS':'1' if battle_loss_final else '0',
                     'NK3_TEST_FINAL_BATTLE_WIN':'1' if battle_win_final else '0',
                     'NK3_TEST_INPUT_DIRECTORY':str(output/'model-inputs'),
                     'NK3_TEST_FINAL_STARTED':str(output/'final-started')},stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+40
                final=None
                while child.poll() is None and time.monotonic()<deadline:
                    if cancel_final and (output/'final-started').exists():break
                    for path in run.glob('decisions/*/explanation.json'):
                        try:
                            info=json.loads(path.read_text())
                        except json.JSONDecodeError:
                            continue
                        if info.get('request_id','').endswith(':final'):
                            final=info
                            break
                    if final and not native_opponent:break
                    time.sleep(.1)
            finally:
                (run/'STOP').touch(exist_ok=True)
                child.wait(timeout=15)
        self.assertEqual(child.returncode,0,(output/'driver.log').read_text())
        if cancel_final:
            self.assertTrue((output/'final-started').exists(),'the separate postgame model never began')
            final_paths=[p.parent for p in run.glob('decisions/*/request.json') if json.loads(p.read_text()).get('request_id','').endswith(':final')]
            self.assertEqual(len(final_paths),1)
            result=json.loads((final_paths[0]/'result.json').read_text())
            self.assertEqual(result['status'],'requested_stop','STOP did not cancel the active postgame controller')
            self.assertEqual(result['purpose'],'postgame_reflection')
            launch=json.loads((run/'launch.json').read_text())
            self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
            return
        self.assertIsNotNone(final,str(output))
        self.assertEqual(final['provider'],'codex')
        self.assertGreater(final['experience']['lessons_updated'],0)
        native=(run/'engine-logs/VCMI_Client_log.txt').read_text(errors='replace')
        if actor=='ExternalAI':self.assertIn('ExternalAI final experience review player=0 outcome=loss delivered=1',native)
        else:
            self.assertIn('NK3_TERMINAL',native)
            final_requests=[json.loads(p.read_text()) for p in run.glob('decisions/*/request.json') if json.loads(p.read_text()).get('request_id','').endswith(':final')]
            self.assertEqual(len(final_requests),2 if native_opponent else 1)
            if native_opponent:
                self.assertEqual({r['observation']['player'] for r in final_requests},{0,1})
                self.assertEqual(len({r['memory']['experience_id'] for r in final_requests}),2)
                for r in final_requests:
                    own_player=r['observation']['player']
                    for item in r['memory']['recent_results']:
                        action=item['action']
                        if action['kind']=='battle':self.assertEqual(action['player'],own_player)
                        else:
                            self.assertEqual(action['before']['player'],own_player)
                            self.assertEqual(action['after']['player'],own_player)
            request=next(r for r in final_requests if r['observation']['player']==0)
            self.assertEqual(request['observation'],{'player':0,'day':1 if battle_loss_final else 2,
                                                    'terminal_result':'win' if battle_win_final else 'loss'})
            self.assertEqual(request['actions'],[{'id':'end','kind':'end_turn'}])
            if battle_loss_final or battle_win_final:
                self.assertTrue(('I lost the Starting battle of' if battle_loss_final else 'I won the Starting battle of') in native,
                                'fixture did not complete the intended actual battle')
                battles=[item for item in request['memory']['recent_results'] if item['action'].get('kind')=='battle']
                self.assertEqual(len(battles),1,'terminal reflection omitted the own defeat on the opponent turn')
                self.assertEqual(battles[0]['outcome'],'battle_lost' if battle_loss_final else 'battle_won')
                self.assertEqual(battles[0]['action']['player'],0)
                if battle_loss_final:self.assertGreater(battles[0]['action']['army_loss_value'],0)
            from playtesting.reports import native_records
            executions,errors=native_records(run/'engine-logs/VCMI_Client_log.txt','NK3_EXECUTION')
            self.assertEqual(errors,0)
            strategic=[json.loads(p.read_text()) for p in run.glob('decisions/*/request.json')
                       if json.loads(p.read_text()).get('protocol')==2
                       and json.loads(p.read_text())['observation']['player']==0]
            seen={item['sequence'] for r in strategic for item in r.get('memory',{}).get('recent_results',[])}
            tail={item['sequence'] for item in executions
                  if (item['action'].get('before',{}).get('player')==0
                      or item['action'].get('kind')=='battle' and item['action'].get('player')==0)
                  and item['sequence'] not in seen}
            self.assertTrue(tail,'fixture did not execute anything after its last strategic request')
            self.assertTrue(tail <= {item['sequence'] for item in request['memory'].get('recent_results',[])},
                            'terminal learning lost acknowledged own execution after the last model request')
            with closing(sqlite3.connect(run/'experience.sqlite3')) as db:
                episodes=[json.loads(row[0]) for row in db.execute('SELECT payload FROM episodes WHERE game=?',
                          (request['memory']['experience_id'],))]
            learned={signal['sequence'] for e in episodes for signal in e['signals'] if signal['kind']=='action_result'}
            self.assertTrue(tail <= learned,'own terminal execution did not reach durable experience')
            if check_context:
                final_input=json.loads((output/'model-inputs/0.json').read_text())
                context=final_input['experience']
                self.assertEqual(context['execution_context']['execution_mechanism'],'native_campaign_v3')
                self.assertTrue(context['execution_context']['rules_known'])
                self.assertEqual(context['execution_context']['engine_revision'],strategic[0]['observation']['rules']['engine_revision'])
                self.assertTrue(context['lessons'],'fixture did not produce a reusable lesson before its terminal review')
                for lesson in context['lessons']:
                    self.assertTrue(any(source['execution_mechanism']=='native_campaign_v3'
                        and source['rules_digest']==context['execution_context']['rules_digest']
                        for source in lesson['evidence_contexts']),'a native lesson lost its rule/executor provenance')
            directory=next(p.parent for p in run.glob('decisions/*/request.json') if json.loads(p.read_text())['request_id']==request['request_id'])
            result=json.loads((directory/'result.json').read_text())
            self.assertEqual(result['status'],'reply_valid')
            self.assertEqual(result['purpose'],'postgame_reflection')
            self.assertGreaterEqual(result['started_at'],json.loads((run/'launch.json').read_text())['finished_at'],
                'postgame reflection preceded engine command cleanup')
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete'])
        self.assertTrue(launch['protected_files_unchanged'])
        if battle_win_final:
            self.assertEqual(launch['reason'],'process_exit','won game required forced cleanup after shutdown began')
        self.assertTrue((run/'experience.sqlite3').is_file())
