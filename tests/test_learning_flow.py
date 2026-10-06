"""Separate strategic choice and durable reflection through subprocess seams."""
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing
import subprocess
import sys
import tempfile
import unittest

from codex_fixture import codex_fixture

ROOT = Path(__file__).resolve().parents[1]
STRATEGIST = '''
import json,pathlib,sys
if sys.argv[1:] == ['--version']:
    print('codex-cli 0.160.0');sys.exit(0)
r=json.load(sys.stdin)
s=json.loads(pathlib.Path(sys.argv[sys.argv.index('--output-schema')+1]).read_text())
assert 'experience' not in r, 'raw experience reached the strategist'
assert 'learning' not in s['properties'], 'strategist is still required to reflect'
answer={'protocol':1,'request_id':r['request_id'],'action_id':'end','strategy':None}
pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text(json.dumps(answer))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}))
'''
ANALYST = '''
import json,pathlib,sys
if sys.argv[1:] == ['--version']:
    print('codex-cli 0.160.0');sys.exit(0)
r=json.load(sys.stdin)
assert 'analysis_version' in r and 'actions' not in r
evaluations=[];assessments=[]
for e in r['episodes']:
 ids=[s['id'] for s in e['signals']]
 evaluations.append({'episode_id':e['id'],'outcome':'harm','decision_quality':'uncertain',
  'responsibility':'unknown','before_evidence_ids':[],'after_evidence_ids':ids[:1],
  'alternative_evidence_id':None,'explanation':'Own hero is no longer owned; the cause is unconfirmed.',
  'uncertainty':'No confirmed battle receipt.','impact':'One own hero no longer owned.'})
 assessments.append({'episode_id':e['id'],'lesson_id':None,'verdict':'support',
  'rule':'Check acknowledged battle results before attributing missing heroes to combat.',
  'conditions':['combat'],'evidence_ids':ids[:1],'explanation':'Ownership change alone does not establish cause.',
  'exceptions':['A confirmed battle receipt supplies stronger evidence.'],
  'mechanism':'Avoid attributing losses to an unobserved cause.'})
answer={'evaluations':evaluations,'assessments':assessments}
pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text(json.dumps(answer))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':8,'output_tokens':5}}))
'''


class LearningFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.database=self.folder/'experience.sqlite3'
        self.env={**os.environ,**codex_fixture(self.folder,STRATEGIST),
                  'VCMI_EXPERIENCE_DB':str(self.database),'VCMI_EXPERIENCE_MODE':'learn'}

    def request(self,day=1,heroes=None):
        return {'protocol':1,'request_id':f'0:{day}:0',
                'observation':{'day':day,'player':0,'heroes':heroes if heroes is not None else [{'id':7,'strength':{'army_ai_value':1000}}],
                               'towns':[{'id':8}],'resources':[5000]},
                'memory':{'schema':2,'experience_id':'player-game','plan':None,'recent_results':[]},
                'actions':[{'id':'end','kind':'end_turn'}]}

    def call(self,request):
        self.env.update(codex_fixture(self.folder,STRATEGIST))
        r=subprocess.run([sys.executable,str(ROOT/'controller/main.py')],input=json.dumps(request),
                         text=True,capture_output=True,timeout=10,env=self.env)
        self.assertEqual(r.returncode,0,r.stderr)
        return json.loads(r.stdout),json.loads(r.stderr)

    def test_strategy_does_not_reflect_but_its_decision_and_consequence_are_durable(self):
        _,first=self.call(self.request())
        self.assertEqual(first['provider'],'codex',first)
        _,second=self.call(self.request(day=2,heroes=[]))
        self.assertEqual(second['provider'],'codex',second)
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM episodes WHERE assessed=0').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM assessments').fetchone()[0],0)

    def test_separate_analysis_publishes_a_lesson_without_repeating_its_evidence(self):
        self.call(self.request())
        self.call(self.request(day=2,heroes=[]))
        env={**self.env,**codex_fixture(self.folder,ANALYST)}
        command=[sys.executable,str(ROOT/'controller/analyze.py'),'--database',str(self.database),'--once']
        first=subprocess.run(command,text=True,capture_output=True,env=env,timeout=10)
        self.assertEqual(first.returncode,0,first.stderr)
        self.assertEqual(json.loads(first.stdout)['status'],'assessed',first.stdout)
        knowledge=self.database.with_suffix('.knowledge.json')
        lesson=json.loads(knowledge.read_text())['lessons'][0]
        self.assertEqual(lesson['supports'],1)
        self.assertEqual(lesson['confidence'],'hypothesis')
        second=subprocess.run(command,text=True,capture_output=True,env=env,timeout=10)
        self.assertEqual(second.returncode,0,second.stderr)
        self.assertEqual(json.loads(knowledge.read_text())['lessons'][0]['supports'],1)
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM evaluations').fetchone()[0],1)


if __name__=='__main__':unittest.main()
