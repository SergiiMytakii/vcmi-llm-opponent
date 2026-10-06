import json
from pathlib import Path
import sqlite3
from contextlib import closing
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'controller'))
from analyze import validate_analysis
from evaluation import TelemetryCollector


class EvaluationTest(unittest.TestCase):
    def collect(self,days=2,*,progress=False,gap=False,defense=False,scouting=False,available=True,end_movement=1500):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        folder=Path(temporary.name);journal=folder/'turns.jsonl';database=folder/'experience.sqlite3'
        events=[]
        for day in range(1,days+1):
            for phase in ('begin','end'):
                world={'day':day,'player':1,'heroes':[{'id':7,'ref':'object:7','position':[day if progress and phase=='end' else 0,0,0],
                    'movement':end_movement if phase=='end' else 1500,'movement_per_day':1500,'army_value':5000}],
                    'towns':[],'resources':[0]*7,'main_army_idle':{'hero_ref':'object:7','reason':'defense' if defense else 'no_task'},
                    'scouting_blocked':scouting,'opportunities':[{'actor_ref':'object:7','target_ref':'tile:known' if scouting else 'object:9',
                        'category':'exploration' if scouting else 'economy','kind':'scout' if scouting else 'capture_mine',
                        'available':available,'constraints_checked':available,'arrival_day':day}]}
                if gap and day==1 and phase=='end':continue
                events.append({'version':1,'game':'own-game','generation':'generation','player':1,'day':day,
                    'phase':phase,'sequence':len(events)+1,'complete':True,'campaign':None,'observation':world})
        journal.write_text(''.join(json.dumps(e)+'\n' for e in events))
        TelemetryCollector(database,journal,{1}).poll()
        with closing(sqlite3.connect(database)) as db:
            return [json.loads(r[0]) for r in db.execute('SELECT payload FROM episodes')]

    def evaluation(self,episode,quality='avoidable_mistake',responsibility='strategy'):
        before=[s['id'] for s in episode['signals'] if s.get('stage')=='before']
        after=[s['id'] for s in episode['signals'] if s.get('stage')!='before']
        rule='Reconsider repeated idle turns when a useful route is feasible.'
        return {'evaluations':[{'episode_id':episode['id'],'outcome':'missed_opportunity','decision_quality':quality,
            'responsibility':responsibility,'before_evidence_ids':before[:1],'after_evidence_ids':after[:1],
            'alternative_evidence_id':before[0] if before and quality=='avoidable_mistake' else None,
            'explanation':'Two complete turns with an offered route and no progress.',
            'uncertainty':'Forecast does not guarantee capture.','impact':'Two own turns.'}],
            'assessments':[{'episode_id':episode['id'],'lesson_id':None,'verdict':'support','rule':rule,
                'conditions':['tempo'],'evidence_ids':after[:1],'explanation':'Observed delay.',
                'exceptions':['Necessary defense or supported preparation.'],'mechanism':'Preserve useful tempo.'}]}

    def test_first_turn_terminal_is_durable_without_a_completed_end_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);database=folder/'experience.sqlite3';journal=folder/'turns.jsonl'
            begin={'version':1,'game':'own-game','generation':'first','player':0,'day':1,'phase':'begin',
                'sequence':1,'complete':True,'observation':{'player':0,'day':1,'heroes':[],'towns':[]}}
            terminal={**begin,'sequence':2,'phase':'terminal','observation':{'player':0,'day':1,'terminal_result':'win'}}
            journal.write_text(json.dumps(begin)+'\n'+json.dumps(terminal)+'\n')
            TelemetryCollector(database,journal,{0}).poll()
            with closing(sqlite3.connect(database)) as db:
                episodes=[json.loads(row[0]) for row in db.execute('SELECT payload FROM episodes')]
            self.assertTrue(any(s['kind']=='game_result' for e in episodes for s in e['signals']))

    def test_progress_and_incomplete_history_do_not_create_multiday_omission(self):
        for arguments in ({'progress':True},{'gap':True}):
            with self.subTest(arguments=arguments):
                self.assertFalse(any(e.get('category')=='idle_main' for e in self.collect(**arguments)))

    def test_ignored_mine_requires_an_available_route(self):
        self.assertTrue(any(e.get('category')=='ignored_mine' for e in self.collect()))
        self.assertFalse(any(e.get('category')=='ignored_mine' for e in self.collect(available=False)))

    def test_scouting_review_requires_three_complete_turns_and_information_blocker(self):
        self.assertFalse(any(e.get('category')=='missing_scouting' for e in self.collect(days=2,scouting=True)))
        self.assertTrue(any(e.get('category')=='missing_scouting' for e in self.collect(days=3,scouting=True)))

    def test_mine_and_scouting_candidates_do_not_require_unused_main_army_movement(self):
        episodes=self.collect(end_movement=100)
        self.assertTrue(any(e.get('category')=='ignored_mine' for e in episodes))
        self.assertFalse(any(e.get('category')=='idle_main' for e in episodes))
        self.assertTrue(any(e.get('category')=='missing_scouting' for e in self.collect(days=3,scouting=True,end_movement=100)))

    def test_battle_event_can_use_complete_prechoice_evidence_without_a_multiday_window(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);database=folder/'experience.sqlite3';journal=folder/'turns.jsonl'
            begin={'version':1,'game':'own-game','generation':'first','player':1,'day':1,'phase':'begin',
                'sequence':1,'complete':True,'observation':{'player':1,'day':1,'heroes':[],'towns':[],
                    'opportunities':[{'actor_ref':'object:7','target_ref':'object:9','kind':'capture_mine',
                        'available':True,'constraints_checked':True}]}}
            result={'sequence':7,'player':1,'day':1,'outcome':'battle_lost','action':{'kind':'battle','player':1}}
            execution={**begin,'sequence':2,'phase':'execution','own_result':result,'observation':{'player':1,'day':1}}
            terminal={**begin,'sequence':3,'phase':'terminal','results':[result],
                'observation':{'player':1,'day':1,'terminal_result':'loss'}}
            journal.write_text(''.join(json.dumps(e)+'\n' for e in (begin,execution,terminal)))
            TelemetryCollector(database,journal,{1}).poll()
            with closing(sqlite3.connect(database)) as db:episode=json.loads(db.execute('SELECT payload FROM episodes').fetchone()[0])
            self.assertTrue(episode['prechoice_complete'])
            self.assertNotIn('window',episode)
            validate_analysis({'episodes':[episode],'lessons':[]},self.evaluation(episode))
            episode['prechoice_complete']=False
            with self.assertRaisesRegex(ValueError,'pre-choice'):
                validate_analysis({'episodes':[episode],'lessons':[]},self.evaluation(episode))

    def test_deadline_failure_opens_an_event_episode_immediately(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);database=folder/'experience.sqlite3';journal=folder/'turns.jsonl'
            begin={'version':1,'game':'own-game','generation':'first','player':1,'day':2,'phase':'begin',
                'sequence':1,'complete':True,'observation':{'player':1,'day':2,'heroes':[],'towns':[],
                    'goal_statuses':{'capture':{'state':'waiting','reason':'dependency_pending'}}}}
            end={**begin,'phase':'end','sequence':2,'observation':{**begin['observation'],
                'goal_statuses':{'capture':{'state':'blocked','reason':'deadline_missed'}}}}
            journal.write_text(json.dumps(begin)+'\n'+json.dumps(end)+'\n')
            TelemetryCollector(database,journal,{1}).poll()
            with closing(sqlite3.connect(database)) as db:episodes=[json.loads(r[0]) for r in db.execute('SELECT payload FROM episodes')]
            self.assertTrue(any(s['kind']=='goal_status_changed' and s['status']['reason']=='deadline_missed'
                for e in episodes for s in e['signals']))

    def test_mistake_needs_contemporaneous_feasible_evidence(self):
        episode=next(e for e in self.collect() if e.get('category')=='idle_main')
        context={'episodes':[episode],'lessons':[]}
        validate_analysis(context,self.evaluation(episode))
        episode['signals'][0]['available']=False
        with self.assertRaisesRegex(ValueError,'feasible'):
            validate_analysis(context,self.evaluation(episode))
        justified=self.evaluation(episode,quality='supported')
        justified['evaluations'][0]['explanation']='Own critical defense explains the wait.'
        validate_analysis(context,justified)

    def test_technical_execution_failure_cannot_publish_strategic_advice(self):
        episode=next(e for e in self.collect() if e.get('category')=='idle_main')
        with self.assertRaisesRegex(ValueError,'technical'):
            validate_analysis({'episodes':[episode],'lessons':[]},self.evaluation(episode,quality='uncertain',responsibility='native_execution'))

    def test_idle_window_requires_two_complete_own_turns_and_preserves_before_alternatives(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);journal=folder/'turns.jsonl';database=folder/'experience.sqlite3'
            events=[]
            for day in (1,2):
                for phase in ('begin','end'):
                    events.append({'version':1,'game':'own-game','generation':'generation-a','player':1,
                        'day':day,'phase':phase,'sequence':len(events)+1,'complete':True,'campaign':None,
                        'observation':{'day':day,'player':1,'heroes':[{'id':7,'ref':'object:7',
                            'position':[1,1,0],'movement':1500,'movement_per_day':1500,'army_value':1000}],
                            'towns':[],'resources':[0]*7,
                            'main_army_idle':{'hero_ref':'object:7','movement':1500,'reason':'no_task'},
                            'opportunities':[{'actor_ref':'object:7','target_ref':'object:9','category':'economy',
                                'kind':'capture_mine','available':True,'constraints_checked':True,
                                'arrival_day':day,'expected_effect':'known resource production'}]}})
            journal.write_text('\n'.join(json.dumps(e) for e in events[:3])+'\n')
            collector=TelemetryCollector(database,journal,{1});collector.poll()
            with closing(sqlite3.connect(database)) as db:
                rows=[json.loads(r[0]) for r in db.execute('SELECT payload FROM episodes')]
                self.assertFalse(any(r.get('category')=='idle_main' for r in rows))
            with journal.open('a') as stream:stream.write(json.dumps(events[3])+'\n')
            collector.poll();collector.poll()
            with closing(sqlite3.connect(database)) as db:
                rows=[json.loads(r[0]) for r in db.execute('SELECT payload FROM episodes')]
            idle=[r for r in rows if r.get('category')=='idle_main']
            self.assertEqual(len(idle),1)
            self.assertTrue(idle[0]['window']['complete'])
            alternatives=[s for s in idle[0]['signals'] if s.get('kind')=='opportunity']
            self.assertTrue(alternatives)
            self.assertTrue(all(s['stage']=='before' for s in alternatives))


if __name__=='__main__':unittest.main()
