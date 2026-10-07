"""Completed-game learning through the actual analyst process and durable store."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from codex_fixture import codex_fixture

ROOT=Path(__file__).resolve().parents[1]

class GameAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'experience.sqlite3';self.journal=self.root/'turns.jsonl'
        self.records=self.root/'reviews';self.decisions=self.root/'decisions';self.decisions.mkdir()

    def event(self,day,phase,sequence,terminal=False):
        observation={'player':0,'day':day,'resources':[1000+day],
            'heroes':[{'id':1,'army_value':100,'movement':100}], 'towns':[],
            'rules':{'engine_version':'fixture','engine_revision':'fixture','mods':[]}}
        if terminal:observation['terminal_result']='loss'
        return {'version':1,'game':'own-game','generation':'first','player':0,'day':day,
            'phase':phase,'sequence':sequence,'complete':True,'observation':observation}

    def call(self,body,max_calls=12,finish=False):
        env={**os.environ,**codex_fixture(self.root,body)}
        command=[sys.executable,str(ROOT/'controller/analyze.py'),
            '--database',str(self.db),'--journal',str(self.journal),'--once','--records',str(self.records),
            '--decisions',str(self.decisions),'--max-calls',str(max_calls)]
        if finish:
            flag=self.root/'FINISH';flag.touch();command.remove('--once');command+=['--finish-file',str(flag)]
        result=subprocess.run(command,
            env=env,capture_output=True,text=True,timeout=10)
        return result

    def test_unfinished_game_collects_without_a_model_call(self):
        self.journal.write_text(json.dumps(self.event(1,'begin',1))+'\n'+json.dumps(self.event(2,'end',2))+'\n')
        result=self.call("raise AssertionError('unfinished game must not invoke a model')")
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        self.assertEqual(json.loads(result.stdout)['status'],'waiting_for_terminal')
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM turn_events').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT count(*) FROM lessons').fetchone()[0],0)

    def test_completed_game_reviews_full_history_and_publishes_once(self):
        events=[self.event(1,'begin',1),self.event(2,'end',2),self.event(3,'terminal',3,True)]
        self.journal.write_text(''.join(json.dumps(e)+'\n' for e in events))
        directory=self.decisions/'choice';directory.mkdir()
        request={'protocol':2,'request_id':'choice-1','identity':{'day':1,'generation':'first'},
                 'memory':{'experience_id':'own-game'},'observation':{'day':1,'player':0}}
        (directory/'request.json').write_text(json.dumps(request))
        (directory/'reply.json').write_text(json.dumps({'reason':'Prepare before departure.'}))
        result=self.call(ANALYST)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        report_path=Path(json.loads(result.stdout)['report'])
        report=json.loads(report_path.read_text())
        self.assertEqual(report['coverage']['events'],3)
        self.assertEqual(report['coverage']['model_calls'],1)
        self.assertEqual(len(report['findings']),1)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM game_reviews').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT supports FROM lessons').fetchone()[0],1)
        self.assertEqual(len(json.loads(self.db.with_suffix('.knowledge.json').read_text())['lessons']),1)
        self.journal.write_text(''.join(json.dumps(e)+'\n' for e in [*events,self.event(3,'terminal',4,True)]))
        duplicate=self.call("raise AssertionError('already reviewed game must not invoke model')")
        self.assertEqual(duplicate.returncode,0,duplicate.stderr)
        with sqlite3.connect(self.db) as db:self.assertEqual(db.execute('SELECT supports FROM lessons').fetchone()[0],1)

    def test_one_review_cannot_reinforce_the_same_lesson_twice(self):
        self.journal.write_text(''.join(json.dumps(e)+'\n' for e in
            [self.event(1,'begin',1),self.event(3,'terminal',2,True)]))
        body=ANALYST.replace("pathlib.Path(sys.argv[sys.argv.index('-o')+1])", "if r['stage']=='synthesis':answer['findings']*=2\npathlib.Path(sys.argv[sys.argv.index('-o')+1])")
        result=self.call(body)
        self.assertNotEqual(result.returncode,0)
        with sqlite3.connect(self.db) as db:self.assertEqual(db.execute('SELECT count(*) FROM lessons').fetchone()[0],0)

    def test_terminal_before_first_own_turn_produces_report_without_lessons(self):
        self.journal.write_text(json.dumps(self.event(1,'terminal',1,True))+'\n')
        body=ANALYST.replace('assert len(ids)>=2','assert len(ids)>=1').replace(
            "pathlib.Path(sys.argv[sys.argv.index('-o')+1])", "if r['stage']=='synthesis':answer['findings']=[]\npathlib.Path(sys.argv[sys.argv.index('-o')+1])")
        result=self.call(body)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        report=json.loads(Path(json.loads(result.stdout)['report']).read_text())
        self.assertFalse(report['coverage']['has_initial_snapshot'])
        self.assertEqual(report['findings'],[])

    def test_known_usage_on_failed_synthesis_includes_earlier_calls(self):
        self.journal.write_text(''.join(json.dumps(e)+'\n' for e in
            [self.event(1,'begin',1),self.event(3,'terminal',2,True)]))
        body=ANALYST.replace('write_text(json.dumps(answer))',"write_text('{' if r['stage']=='synthesis' else json.dumps(answer))")
        result=self.call(body)
        self.assertNotEqual(result.returncode,0)
        outcome=json.loads(result.stdout)
        self.assertEqual(outcome['calls'],2)
        self.assertEqual(outcome['charged_tokens'],26)

    def test_finish_drains_both_completed_player_games(self):
        first=[self.event(1,'begin',1),self.event(3,'terminal',2,True)]
        second=[self.event(1,'begin',1),self.event(3,'terminal',2,True)]
        for e in second:e['game']='second-game';e['player']=1;e['observation']['player']=1
        self.journal.write_text(''.join(json.dumps(e)+'\n' for e in first+second))
        result=self.call(ANALYST,finish=True)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM game_reviews').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT supports FROM lessons').fetchone()[0],2)

    def test_model_artifacts_from_discarded_future_are_excluded(self):
        old=self.event(3,'end',2)
        new=self.event(2,'begin',1);new['generation']='new'
        terminal=self.event(3,'terminal',2,True);terminal['generation']='new'
        self.journal.write_text(''.join(json.dumps(e)+'\n' for e in [self.event(1,'begin',1),old,new,terminal]))
        for name,generation,day in [('discarded','first',3),('retained','new',2)]:
            folder=self.decisions/name;folder.mkdir()
            (folder/'request.json').write_text(json.dumps({'request_id':name,'identity':{'generation':generation,'day':day},
                'memory':{'experience_id':'own-game'}}))
        result=self.call(ANALYST.replace("if r['stage']=='chronology':", "if r['stage']=='chronology':\n assert not any(i['id']=='model:discarded' for i in r['records'])"))
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        report=json.loads(Path(json.loads(result.stdout)['report']).read_text())
        self.assertEqual(report['coverage']['model_calls'],1)

    def test_budget_cannot_turn_partial_history_into_a_lesson(self):
        self.journal.write_text(''.join(json.dumps(e)+'\n' for e in
            [self.event(1,'begin',1),self.event(3,'terminal',2,True)]))
        result=self.call("raise AssertionError('insufficient budget must be detected before model')",max_calls=1)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('no partial review',result.stdout)
        with sqlite3.connect(self.db) as db:self.assertEqual(db.execute('SELECT count(*) FROM lessons').fetchone()[0],0)

    def test_unfinished_run_cannot_review_another_games_terminal(self):
        self.journal.write_text(''.join(json.dumps(e)+'\n' for e in
            [self.event(1,'begin',1),self.event(3,'terminal',2,True)]))
        first=self.call(ANALYST);self.assertEqual(first.returncode,0,first.stderr)
        with sqlite3.connect(self.db) as db:db.execute('DELETE FROM game_reviews')
        event=self.event(1,'begin',1);event['game']='unfinished-other'
        self.journal.write_text(json.dumps(event)+'\n')
        result=self.call("raise AssertionError('another game must not be reviewed by this run')")
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        self.assertEqual(json.loads(result.stdout)['status'],'waiting_for_terminal')

    def test_invalid_final_citation_cannot_publish_any_lessons(self):
        self.journal.write_text(''.join(json.dumps(e)+'\n' for e in
            [self.event(1,'begin',1),self.event(3,'terminal',2,True)]))
        result=self.call(ANALYST.replace("'after_evidence_ids':[eid]","'after_evidence_ids':['invented']"))
        self.assertNotEqual(result.returncode,0)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM lessons').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM game_reviews').fetchone()[0],0)

ANALYST = r"""
import json,pathlib,sys
if sys.argv[1:]==['--version']:
 print('codex-cli 0.160.0');sys.exit(0)
r=json.load(sys.stdin)
def decode(e):
 if 'reference_key' not in e:return e
 def expand(v):
  if isinstance(v,list):return [expand(i) for i in v]
  if not isinstance(v,dict):return v
  if set(v)=={e['reference_key']}:return expand(e['shared'][v[e['reference_key']]])
  obj=e.get('object_key')
  if obj and set(v)=={obj}:
   index,*values=v[obj]
   return {k:expand(i) for k,i in {**e.get('field_defaults',{}).get(str(index),{}),**dict(zip(e['fields'][index],values))}.items()}
  return {k:expand(i) for k,i in v.items()}
 return expand(e['request'])
r=decode(r)
if r['stage']=='chronology':
 ids=[i['id'] for i in r['records'] if i['kind'] in ('own_event','model_decision')]
 assert len(ids)>=2
 answer={'summary':'Observed preparation and subsequent defeat.',
  'observations':[{'text':'The whole game includes an initial turn and a terminal result.','evidence_ids':[ids[0],ids[-1]]}]}
else:
 assert r['outcome']=='loss'
 eid=next(i['id'] for i in r['evidence'] if i['kind']=='own_event' and i['data'].get('phase')=='terminal')
 assessment={'episode_id':'whole-game','lesson_id':None,'verdict':'support',
  'rule':'Reassess operation timing against current defense obligations.',
  'conditions':['tempo','defense'],'evidence_ids':[eid],'explanation':'The completed game motivates a conditional hypothesis.',
  'exceptions':['A necessary recovery pause may justify waiting.'],'mechanism':'Preserve tempo without ignoring defense.'}
 evaluation={'episode_id':'whole-game','outcome':'harm','decision_quality':'uncertain','responsibility':'strategy',
  'before_evidence_ids':[],'after_evidence_ids':[eid],'alternative_evidence_id':None,
  'explanation':'Defeat is observed, but avoidability is not proved.','uncertainty':'No verified better alternative.',
  'impact':'Player lost the game.'}
 answer={'summary':'Preparation followed by defeat.','strategy':'Assess the operation across all recorded turns.',
  'turning_points':[{'text':'The terminal result confirms defeat.','evidence_ids':[eid]}],
  'findings':[{'assessment':assessment,'evaluation':evaluation,'decision_evidence_id':None}]}
pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text(json.dumps(answer))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':8,'output_tokens':5}}))
"""

if __name__=='__main__':unittest.main()
