"""Durable lesson rules through separate analysis and published knowledge."""
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing
import subprocess
import sys
import unittest

import test_learning_flow as flow
ROOT=flow.ROOT
from codex_fixture import codex_fixture
sys.path.insert(0,str(ROOT/'controller'))
from experience import Experience
from knowledge import publish,snapshot_for_request,KnowledgeReader
from unittest.mock import patch

REVIEWER=flow.ANALYST.replace('import json,pathlib,sys','import json,pathlib,sys,os').replace(
 "'lesson_id':None,'verdict':'support'",
 "'lesson_id':r['lessons'][0]['id'] if r['lessons'] else None,'verdict':os.environ.get('ANALYSIS_MODE','support')")
REVIEWER=REVIEWER.replace("answer={'evaluations':evaluations,'assessments':assessments}","""
mode=os.environ.get('ANALYSIS_MODE','support')
if mode=='revise':
 for a in assessments:a['rule']='Use confirmed own battle receipts to distinguish casualties from changes in army ownership.'
if mode=='invented':
 for a in assessments:a['evidence_ids']=['invented']
if mode=='skip':assessments=[]
answer={'evaluations':evaluations,'assessments':assessments}
""")


class ExperienceTest(unittest.TestCase):
    setUp=flow.LearningFlowTest.setUp
    request=flow.LearningFlowTest.request
    call=flow.LearningFlowTest.call

    def episode(self,game='player-game',rules=None):
        first=self.request();first['memory']['experience_id']=game
        after=self.request(day=2,heroes=[]);after['memory']['experience_id']=game
        if rules:
            first['observation']['rules']=rules;after['observation']['rules']=rules
        self.call(first);self.call(after)

    def analyze(self,mode='support',check=True):
        env={**self.env,**codex_fixture(self.folder,REVIEWER),'ANALYSIS_MODE':mode}
        r=subprocess.run([sys.executable,str(ROOT/'controller/analyze.py'),'--database',str(self.database),'--once'],
                         capture_output=True,text=True,env=env,timeout=10)
        if check:self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        return r

    def lessons(self):return json.loads(self.database.with_suffix('.knowledge.json').read_text())['lessons']

    def test_supported_confidence_needs_three_compatible_games(self):
        rules={'engine_version':'1.8','engine_revision':'revision-A',
               'mods':[{'id':'core','version':''},{'id':'vcmi','version':'1.5'}]}
        for number in range(3):self.episode('game-'+str(number),rules);self.analyze()
        request=self.request();request['observation']['rules']=rules
        with patch.dict(os.environ,self.env):matching=snapshot_for_request(request)['lessons'][0]
        self.assertEqual(matching['matching_supporting_games'],3)
        self.assertEqual(matching['confidence'],'supported')
        request['observation']['rules']={**rules,'engine_revision':'different'}
        with patch.dict(os.environ,self.env):different=snapshot_for_request(request)['lessons'][0]
        self.assertEqual(different['confidence'],'hypothesis')
        self.assertEqual(different['matching_supporting_games'],0)

    def test_contradicted_lesson_is_removed_from_published_advice(self):
        self.episode('one');self.analyze();self.episode('two');self.analyze('contradict')
        self.assertEqual(self.lessons(),[])
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT supports,contradictions FROM lessons').fetchone(),(1,1))

    def test_revision_preserves_predecessor_and_publishes_replacement(self):
        self.episode('one');self.analyze();old=self.lessons()[0]['id']
        self.episode('two');self.analyze('revise')
        self.assertEqual(len(self.lessons()),1)
        self.assertNotEqual(self.lessons()[0]['id'],old)
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM retirements').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lessons').fetchone()[0],2)

    def test_uncertainty_does_not_publish_a_new_rule(self):
        self.episode();self.analyze('uncertain');self.assertEqual(self.lessons(),[])
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM assessments').fetchone()[0],1)

    def test_invented_evidence_or_skipped_episode_keeps_pending_and_strategy_usable(self):
        for mode in ('invented','skip'):
            with self.subTest(mode=mode):
                self.episode(mode);result=self.analyze(mode,check=False)
                self.assertNotEqual(result.returncode,0,result.stdout)
                with closing(sqlite3.connect(self.database)) as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM assessments').fetchone()[0],0)
                _,metadata=self.call(self.request())
                self.assertEqual(metadata['provider'],'codex')

    def test_publication_recovers_after_commit_without_new_analysis_or_counters(self):
        self.episode();self.analyze();expected=self.lessons()
        self.database.with_suffix('.knowledge.json').unlink()
        result=self.analyze()
        self.assertEqual(json.loads(result.stdout)['status'],'idle')
        self.assertEqual(self.lessons(),expected)

    def test_corrupted_publication_is_rebuilt_from_committed_sqlite(self):
        self.episode();self.analyze();target=self.database.with_suffix('.knowledge.json');expected=target.read_bytes()
        for invalid in ('[]','null','1',json.dumps({'revision':json.loads(expected)['revision'],'lessons':'corrupt'})):
            target.write_text(invalid)
            publish(self.database)
            self.assertEqual(target.read_bytes(),expected)
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM analysis_usage').fetchone()[0],1)

    def test_recovery_removes_retired_advice_without_another_model_call(self):
        self.episode('one');self.analyze()
        target=self.database.with_suffix('.knowledge.json');stale=target.read_bytes()
        self.episode('two');self.analyze('contradict');target.write_bytes(stale)
        with closing(sqlite3.connect(self.database)) as db:
            counters=db.execute('SELECT supports,contradictions FROM lessons').fetchall()
            usage=db.execute('SELECT COUNT(*) FROM analysis_usage').fetchone()[0]
        result=self.analyze()
        self.assertEqual(json.loads(result.stdout)['status'],'idle')
        self.assertEqual(self.lessons(),[])
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT supports,contradictions FROM lessons').fetchall(),counters)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM analysis_usage').fetchone()[0],usage)

    def test_save_rollback_discards_unassessed_future_and_reoffers_consequence(self):
        self.episode();self.call(self.request())
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM episodes WHERE assessed=0').fetchone()[0],0)
        self.call(self.request(day=2,heroes=[]));self.analyze()
        self.assertEqual(self.lessons()[0]['supports'],1)

    def test_incomplete_own_roster_does_not_prove_hero_loss(self):
        self.call(self.request(heroes=[{'id':99}]))
        self.call(self.request(day=2,heroes=[{'id':n} for n in range(33)]))
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM episodes').fetchone()[0],0)

    def test_read_only_and_off_controller_leave_library_unchanged(self):
        self.episode();self.analyze();before=self.database.read_bytes()
        for mode in ('read_only','off'):
            env={**self.env,'VCMI_EXPERIENCE_MODE':mode}
            r=subprocess.run([sys.executable,str(ROOT/'controller/main.py')],input=json.dumps(self.request()),
                             capture_output=True,text=True,env=env,timeout=10)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(self.database.read_bytes(),before)

    def test_stale_analysis_cannot_restore_a_discarded_episode(self):
        self.episode();store=Experience(self.database,'learn')
        try:
            context=store.context({'protocol':1,'memory':{'experience_id':'player-game'},'observation':{'day':2}})
            store.observe(self.request())
            episode=context['episodes'][0]
            assessment={'episode_id':episode['id'],'lesson_id':None,'verdict':'support',
                'rule':'Retain confirmed evidence.','conditions':['combat'],
                'evidence_ids':[episode['signals'][0]['id']],'explanation':'Confirmed observation.'}
            with self.assertRaisesRegex(ValueError,'stale'):
                store.assess('player-game',context,{'expectation':'Separate analysis.','assessments':[assessment]})
        finally:store.close()

    def test_large_provenance_keeps_the_complete_rule_and_exceptions_readable(self):
        lesson={'id':'one','rule':'Check current defense obligations.','conditions':['defense'],
            'status':'active','confidence':'hypothesis','exceptions':['Required delivery.'],
            'mechanism':'Protect current commitments.',
            'evidence_contexts':[{'engine_revision':'x'*600,'supporting_games':1} for _ in range(4)]}
        reader=KnowledgeReader({'revision':'fixed','lessons':[lesson]})
        found=reader.call('search_knowledge',{'query':'defense'})['lessons']
        self.assertEqual(found[0]['id'],'one')
        read=reader.call('read_lesson',{'id':'one'})['lessons'][0]
        self.assertEqual(read['rule'],lesson['rule'])
        self.assertEqual(read['exceptions'],lesson['exceptions'])
        self.assertEqual(read['mechanism'],lesson['mechanism'])
        self.assertFalse(read['evidence_contexts_complete'])

    def test_knowledge_reader_has_shared_budget_and_no_path_read_operation(self):
        self.episode();self.analyze();reader=KnowledgeReader({'revision':'one','lessons':self.lessons()})
        result=reader.call('search_knowledge',{'query':'battle','category':'combat'})
        self.assertEqual(len(result['lessons']),1)
        self.assertEqual(reader.call('read_lesson',{'id':'/etc/passwd'})['lessons'],[])
        for _ in range(2):reader.call('read_lesson',{'id':self.lessons()[0]['id']})
        self.assertIn('unavailable',reader.call('search_knowledge',{'query':'battle'}))
        with self.assertRaisesRegex(ValueError,'unknown'):
            KnowledgeReader({'lessons':[]}).call('read_file',{'path':'/etc/passwd'})


if __name__=='__main__':unittest.main()
