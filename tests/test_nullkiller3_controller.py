"""Strategic goals traverse the existing subscription controller without actions."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from codex_fixture import codex_fixture

ROOT = Path(__file__).resolve().parents[1]


def strategic_request():
    return dict(protocol=2,request_id='instance:generation:0:1:0:1',
                identity=dict(instance='instance',generation='generation',player=0,day=1,revision=0),
                observation=dict(player=0,day=1,resources=[10,10,10,10,10,10,10000],
                                 heroes=[dict(id=0,ref='object:0',army_value=5000)],
                                 towns=[dict(id=1,ref='object:1',buildings=[],building_options=[dict(id=0,supported=True)])],
                                 objects=[dict(id=1,ref='object:1',kind='town',owner=0,visible=True)],
                                 frontiers=['tile:frontier'],capabilities=['land','build','transfer']),
                memory=dict(known_objects=[dict(ref='object:1')]),campaign=None,
                signals=[dict(question='opening',facts='no_campaign')],budget=dict(wait_ms=70000,tokens=12000))


class NativeStrategyControllerTest(unittest.TestCase):
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
mode=os.environ['NK3_STUB_MODE']
if mode=='stale':answer['identity']['generation']='old'
if mode=='capability':plan['goals'][0]['required_capabilities']=['fly']
if mode=='policy':plan['policy']['allow_route_repair']=1
if mode=='command':answer['command']='build'
if mode=='refusal':sys.exit(4)
if r.get('experience',{}).get('mode')=='learn':
 answer['learning']={'expectation':'Develop before expanding.','assessments':[]}
pathlib.Path(args[args.index('-o')+1]).write_text(json.dumps(answer))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':120,'output_tokens':40}}))
''')
            request=strategic_request()
            if learn:request['memory']['experience_id']='nk3-learning-opening'
            result=subprocess.run([sys.executable,str(ROOT/'controller/main.py')],input=json.dumps(request),
                                  text=True,capture_output=True,timeout=10,
                                  env={**os.environ,**env,'NK3_STUB_MODE':mode,'VCMI_EXPERIENCE_MODE':'learn' if learn else 'off',
                                       'VCMI_EXPERIENCE_DB':str(Path(folder)/'experience.sqlite3')})
            return result

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
