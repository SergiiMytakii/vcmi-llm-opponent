"""Strategic goals traverse the existing subscription controller without actions."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from codex_fixture import codex_fixture
from fixtures.strategic_intent import with_intent

ROOT = Path(__file__).resolve().parents[1]


def strategic_request():
    return dict(protocol=2,request_id='instance:generation:0:1:0:1',
                identity=dict(instance='instance',generation='generation',player=0,day=1,revision=0),
                observation=dict(player=0,day=1,resources=[10,10,10,10,10,10,10000],
                                 heroes=[dict(id=0,ref='object:0',army_value=5000)],
                                 towns=[dict(id=1,ref='object:1',buildings=[],building_options=[dict(id=0,supported=True)])],
                                 objects=[dict(id=1,ref='object:1',kind='town',owner=0,visible=True)],
                                 frontiers=['tile:frontier'],capabilities=['land','build','transfer']),
                strategic_intent=None,memory=dict(known_objects=[dict(ref='object:1')]),campaign=None,
                signals=[dict(question='opening',facts='no_campaign')],budget=dict(wait_ms=70000,tokens=12000))


class NativeStrategyControllerTest(unittest.TestCase):
    def test_without_owned_towns_policy_requires_empty_critical_towns(self):
        from controller.native_strategy import reply_schema
        request=strategic_request()
        request['observation']['towns']=[]
        request['observation']['objects'][0]['owner']=1
        schema=reply_schema(request)
        policy=schema['properties']['plan']['anyOf'][1]['properties']['policy']['properties']
        self.assertEqual(policy['critical_towns']['maxItems'],0,
                         'No owned towns must not offer a dummy empty-string town reference')

    def test_post_capture_goals_use_owned_town_and_visible_enemy_with_distinct_predicates(self):
        from controller.native_strategy import validate_reply
        request=strategic_request()
        request['observation']['enemy_players']=[1]
        request['observation']['objects'].append(dict(ref='object:2',id=2,kind='hero',owner=1,visible=True))
        def answer(kind,target,completion,value):
            reply=dict(protocol=2,request_id=request['request_id'],identity=request['identity'],decision='revise',
                reason='Compare post-capture alternatives',evidence_refs=['observation:day'],victory_method='Maintain conquest',
                assignments=[dict(hero_ref='object:0',role='main')],
                alternatives=[dict(approach='offense',benefit='Advance',cost='Expose town',uncertainty='Enemy intent'),
                              dict(approach='defense',benefit='Hold',cost='Delay',uncertainty='Enemy timing')],
                reconsider_when=[dict(goal_id='prepare',kind='deadline_missed')],
                plan=dict(version=3,revision=1,approach='offense',horizon_days=3,
                    goals=[dict(id='prepare',kind=kind,actor_ref='object:0',target_ref=target,deadline_day=3,
                        priority=90,building_id=-1,min_army_value=4000,depends_on=[],required_capabilities=['land'],
                        complete_when=dict(kind=completion,value=value))],reserves=[],
                    policy=dict(max_loss_ratio=.25,allow_route_repair=True,allow_helper_replacement=True,critical_towns=[])))
            if kind=='prepare_garrison':reply['plan']['goals'][0]['garrison_mode']='recruit_then_detach'
            return with_intent(request,reply)
        validate_reply(request,answer('prepare_garrison','object:1','garrison_at_least',1000))
        validate_reply(request,answer('intercept_hero','object:2','enemy_engaged',0))
        four_options=answer('intercept_hero','object:2','enemy_engaged',0)
        four_options['alternatives'].extend([
            dict(approach='expansion',benefit='Capture then recruit',cost='Travel and losses',uncertainty='Enemy response'),
            dict(approach='offense',benefit='Reinforce then attack',cost='Delivery delay',uncertainty='Fresh attack route')])
        validate_reply(request,four_options)
        five_options=json.loads(json.dumps(four_options))
        five_options['alternatives'].append(
            dict(approach='scouting',benefit='Open a passage then reassess',cost='Movement',uncertainty='Exit safety'))
        with self.assertRaises(ValueError):validate_reply(request,five_options)
        for bad in [answer('prepare_garrison','object:0','garrison_at_least',1000),
                    answer('prepare_garrison','object:1','garrison_at_least',0),
                    answer('intercept_hero','object:2','target_owned',0)]:
            with self.assertRaises(ValueError):validate_reply(request,bad)
        request['observation']['objects'][-1]['visible']=False
        with self.assertRaises(ValueError):validate_reply(request,answer('intercept_hero','object:2','enemy_engaged',0))
        completed=answer('intercept_hero','object:2','enemy_engaged',0)
        goal=completed['plan']['goals'][0]
        request['campaign']=completed['plan']
        request['observation']['goal_statuses']={'prepare':{'state':'completed'}}
        request['observation']['confirmed_interceptions']=[{'goal':goal,'day':1,'won':True}]
        validate_reply(request,completed)
        changed=answer('intercept_hero','object:2','enemy_engaged',0)
        changed['plan']['goals'][0]['min_army_value']=3999
        with self.assertRaises(ValueError):validate_reply(request,changed)
        request['observation']['confirmed_interceptions']=[]
        with self.assertRaises(ValueError):validate_reply(request,completed)

    def exchange(self, mode,learn=False):
        with tempfile.TemporaryDirectory() as folder:
            env=codex_fixture(Path(folder), '''
import json,os,pathlib,sys
if sys.argv[1:]==['--version']:
 print('codex-cli 0.160.0');sys.exit(0)
args=sys.argv;r=json.load(sys.stdin)
schema=json.loads(pathlib.Path(args[args.index('--output-schema')+1]).read_text())
assert 'action_id' not in schema['properties'] and 'actions' not in r
assert args[args.index('-m')+1]=='gpt-6.1-sol'
plan=dict(version=3,revision=1,approach='economy',horizon_days=5,
 goals=[dict(id='guild',kind='develop_town',actor_ref=None,target_ref='object:1',deadline_day=3,
 priority=80,building_id=0,min_army_value=0,depends_on=[],required_capabilities=['build'],
 complete_when=dict(kind='building_present',value=0))],reserves=[],
 policy=dict(max_loss_ratio=.2,allow_route_repair=True,allow_helper_replacement=True,critical_towns=['object:1']))
answer=dict(protocol=2,request_id=r['request_id'],identity=r['identity'],decision='revise',reason='Opening development',
 evidence_refs=['town:object:1'],victory_method='Develop before advancing against known hostile teams',assignments=[],
 alternatives=[dict(approach='economy',benefit='Income',cost='Building resources',uncertainty='Threats unknown'),
               dict(approach='offense',benefit='Earlier pressure',cost='Army resources',uncertainty='Enemy location unknown')],
 reconsider_when=[dict(goal_id='guild',kind='deadline_missed')],plan=plan)
from strategic_intent import with_intent
answer=with_intent(r,answer)
mode=os.environ['NK3_STUB_MODE']
if mode in ('risk_protect','risk_accept'):
 answer['alternatives'][1]=dict(approach='defense',benefit='Preserve town income and recruits',cost='Divert the current operation',uncertainty='Enemy arrival unknown')
 answer['reason']='Protect the valuable town' if mode=='risk_protect' else 'Accept the secondary town risk to complete the funded operation'
 if mode=='risk_protect':
  answer['assignments']=[dict(hero_ref='object:0',role='defender')]
  plan['approach']='defense'
  plan['goals']=[dict(id='guild',kind='defend_area',actor_ref='object:0',target_ref='object:1',deadline_day=3,
   priority=90,building_id=-1,min_army_value=5000,depends_on=[],required_capabilities=['land'],
   complete_when=dict(kind='held_until',value=3))]
if mode=='stale':answer['identity']['generation']='old'
if mode=='capability':plan['goals'][0]['required_capabilities']=['fly']
if mode=='policy':plan['policy']['allow_route_repair']=1
if mode=='command':answer['command']='build'
if mode=='refusal':sys.exit(4)
if r.get('experience',{}).get('mode')=='learn':
 answer['learning']={'expectation':'Develop before expanding.','assessments':[]}
if 'kind' in schema['properties']:answer={'kind':'decision','decision':answer,'guide_request':None}
pathlib.Path(args[args.index('-o')+1]).write_text(json.dumps(answer))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':120,'output_tokens':40}}))
''')
            request=strategic_request()
            if mode.startswith('risk_'):
                request['observation']['forecasts']={'defenses':[{'town_ref':'object:1',
                    'status':'insufficient_current_force','threats':[{'source_ref':'object:9'}]}]}
            if learn:request['memory']['experience_id']='nk3-learning-opening'
            result=subprocess.run([sys.executable,str(ROOT/'controller/main.py')],input=json.dumps(request),
                                  text=True,capture_output=True,timeout=10,
                                  env={**os.environ,**env,'NK3_STUB_MODE':mode,'VCMI_EXPERIENCE_MODE':'learn' if learn else 'off',
                                       'VCMI_EXPERIENCE_DB':str(Path(folder)/'experience.sqlite3')})
            return result

    def test_exposed_town_requires_comparison_but_model_can_protect_or_accept_risk(self):
        omitted=self.exchange('risk_omitted')
        self.assertNotEqual(omitted.returncode,0)
        self.assertEqual(omitted.stdout,'')
        for mode,approach in [('risk_protect','defense'),('risk_accept','economy')]:
            with self.subTest(mode=mode):
                result=self.exchange(mode)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(json.loads(result.stdout)['plan']['approach'],approach)

    def test_model_creates_a_goal_without_a_native_action_shortlist(self):
        result=self.exchange('valid')
        self.assertEqual(result.returncode,0,result.stderr)
        reply=json.loads(result.stdout)
        self.assertEqual(reply['plan']['goals'][0]['building_id'],0)
        self.assertEqual(reply['usage'],dict(input_tokens=120,output_tokens=40,known=True))
        self.assertNotIn('action_id',reply)

    def test_first_strategic_decision_with_learning_and_no_prior_episodes_remains_valid(self):
        result=self.exchange('valid',learn=True)
        self.assertEqual(result.returncode,0,result.stderr)
        reply=json.loads(result.stdout);metadata=json.loads(result.stderr)
        self.assertEqual(reply['plan']['goals'][0]['building_id'],0)
        self.assertNotIn('learning',reply)
        self.assertEqual(metadata['experience']['episodes_assessed'],0)

    def test_invalid_strategy_returns_no_command_and_no_partial_plan(self):
        for mode in ['stale','capability','policy','command','refusal']:
            with self.subTest(mode=mode):
                result=self.exchange(mode)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(result.stdout,'')
                self.assertEqual(json.loads(result.stderr)['provider'],'fallback')


if __name__=='__main__':unittest.main()
