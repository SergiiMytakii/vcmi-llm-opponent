"""Player-observed episodes and model-authored, revisable lessons.

SQLite owns durable evidence; the model can assess offered episodes only. No
game state, engine logs, hidden objects or previous chats are read here.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
if sys.platform == 'darwin':
    DATA_ROOT = Path.home() / 'Library/Application Support'
elif os.name == 'nt':
    DATA_ROOT = Path(os.environ.get('APPDATA', str(Path.home() / 'AppData/Roaming')))
else:
    DATA_ROOT = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
DEFAULT_DB = DATA_ROOT / 'VCMI-Nullkiller3/learning/experience.sqlite3'
CONDITIONS = ('combat', 'defense', 'economy', 'reinforcement', 'exploration', 'tempo')
KINDS = {'attack':'combat', 'battle':'combat', 'build':'economy', 'recruit':'reinforcement',
         'transfer':'reinforcement', 'upgrade':'reinforcement', 'explore':'exploration',
         'visit':'exploration', 'hire_hero':'exploration', 'end_turn':'tempo'}
CONTEXT_LIMIT = 131072


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def facts(request):
    """Small factual projection, with completeness explicit before inferring loss."""
    obs = request['observation']
    result = {k:obs[k] for k in ('day','player','resources','resource_order','terminal_result') if k in obs}
    result['execution_mechanism'] = ('native_campaign_v3' if request.get('protocol')==2
        or request.get('memory',{}).get('execution_mechanism')=='native_campaign_v3' else 'external_actions_v1')
    if isinstance(obs.get('rules'),dict):
        result['rules']={k:obs['rules'][k] for k in ('engine_version','engine_revision','mods') if k in obs['rules']}
    for name in ('heroes', 'towns'):
        if isinstance(obs.get(name), list):
            result[name + '_complete'] = len(obs[name]) <= 32
            result[name] = [{k:item[k] for k in ('id','ref','position','in_boat','strength','army','army_value',
                            'movement','movement_per_day','mana','role','defense_value','army_holder_ref','visiting_hero_ref','buildings','daily_income') if k in item}
                            for item in obs[name][:32]]
    if isinstance(obs.get('goal_statuses'),dict):result['goal_statuses']=obs['goal_statuses']
    # Visible threats can explain the information available before a choice.
    if isinstance(obs.get('visible_objects'),list):
        result['visible_objects'] = [{k:item[k] for k in ('id','kind','owner','position','strength','army') if k in item}
                                     for item in obs['visible_objects'][:16]]
    return result


def execution_context(observation):
    """Rule identity and executor provenance, without historical game positions."""
    rules=observation.get('rules',{})
    version=rules.get('engine_version') if isinstance(rules,dict) else None
    revision=rules.get('engine_revision') if isinstance(rules,dict) else None
    mods=rules.get('mods') if isinstance(rules,dict) else None
    valid_text=lambda value:isinstance(value,str) and 0<len(value)<=128
    known=(valid_text(version) and valid_text(revision) and isinstance(mods,list)
        # Pinned VCMI loads virtual core from builtin gameConfig; its declared
        # version is empty. The engine revision scopes that builtin component.
        and all(isinstance(m,dict) and valid_text(m.get('id'))
                and (valid_text(m.get('version')) or m.get('id')=='core' and m.get('version')=='') for m in mods))
    canonical=dict(engine_version=version,engine_revision=revision,
        mods=sorted([(m['id'],m['version']) for m in mods])) if known else None
    return dict(engine_version=version if valid_text(version) else None,
        engine_revision=revision if valid_text(revision) else None,rules_known=bool(known),
        rules_digest=hashlib.sha256(encoded(canonical).encode()).hexdigest() if known else None,
        execution_mechanism=observation.get('execution_mechanism'))


def signals(before, request):
    after = facts(request)
    changes = []
    for name in ('heroes','towns'):
        if before.get(name + '_complete') and after.get(name + '_complete'):
            old = {item['id']:item for item in before[name] if 'id' in item}
            new = {item['id']:item for item in after[name] if 'id' in item}
            for key in sorted(old.keys() - new.keys()):
                changes.append({'kind':name + '_no_longer_owned','object':key,'day':after.get('day')})
            for key in sorted(new.keys() - old.keys()):
                changes.append({'kind':name + '_now_owned','object':key,'day':after.get('day')})
            if name == 'heroes':
                for key in sorted(old.keys() & new.keys()):
                    a = old[key].get('strength', {}).get('army_ai_value')
                    b = new[key].get('strength', {}).get('army_ai_value')
                    if isinstance(a,(int,float)) and isinstance(b,(int,float)) and a != b:
                        changes.append({'kind':'own_army_value_changed','object':key,'before':a,'after':b,'day':after.get('day')})
    for item in request.get('memory', {}).get('recent_results', []):
        if isinstance(item,dict) and type(item.get('sequence')) is int:
            changes.append({'kind':'action_result','sequence':item['sequence'],
                            'action':item.get('action',{}),'outcome':item.get('outcome','unconfirmed')})
    review = request.get('memory', {}).get('plan_review', {})
    if isinstance(before.get('resources'),list) and isinstance(after.get('resources'),list) and before['resources'] != after['resources']:
        changes.append({'kind':'resource_balance_changed','before':before['resources'],
                        'after':after['resources'],'day':after.get('day')})
    if review.get('status') in ('infeasible','requires_revision','completed'):
        changes.append({'kind':'plan_review','review':review,'day':after.get('day')})
    for goal,status in after.get('goal_statuses',{}).items():
        if status!=before.get('goal_statuses',{}).get(goal):
            changes.append({'kind':'goal_status_changed','goal_id':goal,'status':status,'day':after.get('day')})
    if after.get('terminal_result') in ('win','loss'):
        changes.append({'kind':'game_result','result':after['terminal_result']})
    return changes


def learning_schema(context):
    assessment = {'type':'object','additionalProperties':False,
        'required':['episode_id','lesson_id','verdict','rule','conditions','evidence_ids','explanation'],
        'properties':{
            'episode_id':{'type':'string','enum':[e['id'] for e in context['episodes']]},
            'lesson_id':{'type':['string','null'],'enum':[None,*[l['id'] for l in context['lessons']]]},
            'verdict':{'type':'string','enum':['support','contradict','uncertain','revise']},
            'rule':{'type':'string','minLength':1,'maxLength':360},
            'conditions':{'type':'array','minItems':1,'maxItems':4,'items':{'type':'string','enum':list(CONDITIONS)}},
            'evidence_ids':{'type':'array','minItems':1,'maxItems':8,'items':{'type':'string'}},
            'explanation':{'type':'string','minLength':1,'maxLength':480}}}
    assessments = {'type':'array','minItems':len(context['episodes']),'maxItems':len(context['episodes']),'items':assessment} if context['episodes'] else {'type':'array','minItems':0,'maxItems':0,'items':{'type':'string'}}
    return {'type':'object','additionalProperties':False,'required':['expectation','assessments'],
            'properties':{'expectation':{'type':'string','minLength':1,'maxLength':240},'assessments':assessments}}


def text(value, maximum):
    if not isinstance(value,str) or not value.strip() or len(value.encode('utf-8')) > maximum:
        raise ValueError('invalid learning text')


def validate_learning(context, value):
    if not isinstance(value,dict) or set(value) != {'expectation','assessments'}:
        raise ValueError('invalid learning shape')
    text(value['expectation'],240)
    assessments = value['assessments']
    if not isinstance(assessments,list) or len(assessments) > 2:
        raise ValueError('too many assessments')
    episodes = {e['id']:e for e in context['episodes']}
    lessons = {l['id']:l for l in context['lessons']}
    seen = set()
    for item in assessments:
        if not isinstance(item,dict) or set(item) != {'episode_id','lesson_id','verdict','rule','conditions','evidence_ids','explanation'}:
            raise ValueError('invalid assessment fields')
        episode_id, lesson_id = item['episode_id'], item['lesson_id']
        if not isinstance(episode_id,str) or episode_id not in episodes or episode_id in seen:
            raise ValueError('assessment must cite a unique offered episode')
        seen.add(episode_id)
        if lesson_id is not None and (not isinstance(lesson_id,str) or lesson_id not in lessons):
            raise ValueError('lesson was not offered')
        if item['verdict'] not in ('support','contradict','uncertain','revise') or (item['verdict'] in ('contradict','revise') and lesson_id is None):
            raise ValueError('invalid lesson verdict')
        text(item['rule'],360)
        text(item['explanation'],480)
        conditions = item['conditions']
        if not isinstance(conditions,list) or not 1 <= len(conditions) <= 4 or any(c not in CONDITIONS for c in conditions):
            raise ValueError('invalid lesson conditions')
        # Lessons are portable guidance, never a cross-game object/position cache.
        if re.search(r'object:|tile:|\[\s*-?\d+\s*,\s*-?\d+\s*,\s*-?\d+\s*\]',item['rule']):
            raise ValueError('lesson contains a game-local reference')
        if item['verdict'] == 'revise' and item['rule'] == lessons[lesson_id]['rule']:
            raise ValueError('a revision must give a more precise replacement rule')
        if lesson_id is not None and item['verdict'] != 'revise' and (item['rule'] != lessons[lesson_id]['rule'] or sorted(conditions) != sorted(lessons[lesson_id]['conditions'])):
            raise ValueError('existing lesson cannot be silently rewritten; retire it and propose a new lesson')
        evidence = item['evidence_ids']
        ids = {s['id'] for s in episodes[episode_id]['signals']}
        if not isinstance(evidence,list) or not 1 <= len(evidence) <= 8 or any(not isinstance(e,str) or e not in ids for e in evidence):
            raise ValueError('assessment cites unobserved evidence')
    if seen != set(episodes):
        raise ValueError('every offered episode needs an assessment, including uncertainty')


class Experience:
    def __init__(self,path,mode='learn'):
        self.mode = mode
        path = Path(path)
        if mode not in ('learn','read_only'):
            raise ValueError('invalid experience mode')
        if mode == 'read_only':
            self.db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.2)
        else:
            path.parent.mkdir(parents=True,exist_ok=True)
            self.db = sqlite3.connect(path,timeout=.2)
        self.db.row_factory = sqlite3.Row
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0,1) or (mode == 'read_only' and version != 1):
            self.db.close()
            raise ValueError('unsupported experience database')
        if mode == 'learn':
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS decisions (
                    game TEXT, request TEXT, day INTEGER, payload TEXT, action TEXT,
                    expectation TEXT, PRIMARY KEY(game,request));
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY, game TEXT, request TEXT, day INTEGER,
                    payload TEXT, assessed INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS lessons (
                    id TEXT PRIMARY KEY, rule TEXT UNIQUE, conditions TEXT,
                    supports INTEGER DEFAULT 0, contradictions INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS assessments (
                    episode TEXT PRIMARY KEY, lesson TEXT, verdict TEXT, evidence TEXT, explanation TEXT);
                CREATE TABLE IF NOT EXISTS observed_signals (
                    game TEXT, id TEXT, PRIMARY KEY(game,id));
                CREATE TABLE IF NOT EXISTS retirements (
                    lesson TEXT PRIMARY KEY, episode TEXT, replacement TEXT);
                CREATE TABLE IF NOT EXISTS evaluations (episode TEXT PRIMARY KEY, payload TEXT);
                CREATE TABLE IF NOT EXISTS turn_events (
                    game TEXT, generation TEXT, sequence INTEGER, day INTEGER, phase TEXT, payload TEXT,
                    PRIMARY KEY(game,generation,sequence));
                CREATE TABLE IF NOT EXISTS game_reviews (
                    game TEXT, generation TEXT, terminal_sequence INTEGER,
                    source_hash TEXT, report TEXT, usage TEXT,
                    PRIMARY KEY(game));
                CREATE TABLE IF NOT EXISTS analysis_usage (
                    id INTEGER PRIMARY KEY, usage TEXT, result TEXT);
                CREATE INDEX IF NOT EXISTS decisions_game_day ON decisions(game,day);
                CREATE INDEX IF NOT EXISTS episodes_game_day ON episodes(game,day);
                PRAGMA user_version=1;
            ''')

            columns={row['name'] for row in self.db.execute('PRAGMA table_info(lessons)')}
            with self.db:
                if 'exceptions' not in columns:self.db.execute("ALTER TABLE lessons ADD COLUMN exceptions TEXT DEFAULT '[]'")
                if 'mechanism' not in columns:self.db.execute("ALTER TABLE lessons ADD COLUMN mechanism TEXT DEFAULT ''")

    @classmethod
    def for_request(cls,request):
        game = request.get('memory',{}).get('experience_id')
        mode = os.environ.get('VCMI_EXPERIENCE_MODE','learn')
        if mode == 'off' or not isinstance(game,str) or not re.fullmatch(r'[A-Za-z0-9-]{1,64}',game):
            return None
        return cls(os.environ.get('VCMI_EXPERIENCE_DB',str(DEFAULT_DB)),mode)

    def close(self):
        self.db.close()

    def observe(self,request):
        game = request['memory']['experience_id']
        day = request['observation'].get('day',0)
        if type(day) is not int or day < 0:
            raise ValueError('invalid experience day')
        if self.mode == 'learn':
            with self.db:
                # A save rollback cannot use episodes from its discarded future.
                parts = request['request_id'].split(':')
                attempt = float('inf') if parts[-1] == 'final' else int(parts[-1]) if parts[-1].isdigit() else None
                def future(row):
                    suffix = row['request'].split(':')[-1]
                    old_attempt = float('inf') if suffix == 'final' else int(suffix) if suffix.isdigit() else None
                    return row['day'] > day or (row['day'] == day and ('telemetry:' in row['request'])==('telemetry:' in request['request_id']) and attempt is not None
                           and old_attempt is not None and old_attempt > attempt)
                pending = self.db.execute('SELECT id,request,day,payload FROM episodes WHERE game=? AND day>=? AND assessed=0',(game,day)).fetchall()
                for row in pending:
                    if future(row):
                        # These signals have never been assessed. Release their
                        # deduplication entries so a replayed consequence can be
                        # reflected on; assessed historical evidence stays intact.
                        for signal in json.loads(row['payload'])['signals']:
                            self.db.execute('DELETE FROM observed_signals WHERE game=? AND id=?',(game,signal['id']))
                        self.db.execute('DELETE FROM episodes WHERE id=?',(row['id'],))
                for row in self.db.execute('SELECT request,day FROM decisions WHERE game=? AND day>=?',(game,day)).fetchall():
                    if future(row):
                        self.db.execute('DELETE FROM decisions WHERE game=? AND request=?',(game,row['request']))
                trace = self.db.execute('SELECT request,payload,action,expectation FROM decisions WHERE game=? AND request!=? ORDER BY rowid DESC LIMIT 8',
                                        (game,request['request_id'])).fetchall()
                if trace:
                    previous = json.loads(trace[0]['payload'])
                    fresh = []
                    for signal in signals(previous,request):
                        # Result sequences/ownership changes are consumed once, even
                        # though the engine repeats its recent history each call.
                        identity = encoded(signal)
                        sid = hashlib.sha256(identity.encode()).hexdigest()[:20]
                        if self.db.execute('SELECT 1 FROM observed_signals WHERE game=? AND id=?',(game,sid)).fetchone():
                            continue
                        signal['id'] = sid
                        fresh.append(signal)
                    if fresh:
                        eid = hashlib.sha256((game+':'+request['request_id']+':'+encoded(fresh)).encode()).hexdigest()[:24]
                        episode = {'id':eid,'trajectory':[{'request_id':row['request'],
                            'observation':json.loads(row['payload']),'action':json.loads(row['action']),
                            'expectation':row['expectation']} for row in reversed(trace)],
                            'after':facts(request),'signals':fresh}
                        while len(episode['trajectory']) > 1 and len(encoded(episode).encode()) > 65536:
                            episode['trajectory'].pop(0)
                        if len(encoded(episode).encode()) <= 65536:
                            self.db.execute('INSERT OR IGNORE INTO episodes(id,game,request,day,payload) VALUES(?,?,?,?,?)',
                                            (eid,game,request['request_id'],day,encoded(episode)))
                            for signal in fresh:
                                self.db.execute('INSERT OR IGNORE INTO observed_signals VALUES(?,?)',(game,signal['id']))

    def context(self,request,*,include_episodes=True,lesson_limit=6):
        game = request['memory']['experience_id']
        day = request['observation'].get('day',0)
        tags = {'defense','tempo'} | {KINDS[a['kind']] for a in request.get('actions',[]) if a['kind'] in KINDS}
        if request.get('protocol') == 2:
            tags.update(CONDITIONS)  # One strategic response can coordinate all modules.
        if request['observation'].get('terminal_result') in ('win','loss'):
            tags.update(CONDITIONS)
        else:
            for row in self.db.execute('SELECT payload FROM episodes WHERE game=? AND day<=? AND assessed=0 ORDER BY rowid LIMIT 2',(game,day)):
                episode=json.loads(row['payload'])
                for signal in episode['signals']:
                    kind=signal.get('action',{}).get('kind') if signal.get('kind')=='action_result' else None
                    if kind in KINDS:tags.add(KINDS[kind])
                    if signal.get('kind') in ('heroes_no_longer_owned','own_army_value_changed'):tags.add('combat')
                    if signal.get('kind') in ('towns_no_longer_owned','towns_now_owned'):tags.update(('combat','defense'))
                    if signal.get('kind')=='resource_balance_changed':tags.add('economy')
                for decision in episode['trajectory']:

                    kind = decision['action'].get('kind')
                    if kind in KINDS:
                        tags.add(KINDS[kind])
        current=facts(request)
        rules_source='current_observation' if 'rules' in current else 'unavailable'
        if request['observation'].get('terminal_result') in ('win','loss') and 'rules' not in current:
            previous=self.db.execute('SELECT payload FROM decisions WHERE game=? AND request!=? ORDER BY rowid DESC LIMIT 1',
                                     (game,request['request_id'])).fetchone()
            if previous and 'rules' in json.loads(previous['payload']):
                current['rules']=json.loads(previous['payload'])['rules']
                rules_source='last_own_decision_in_game'
        current_context=execution_context(current)
        lessons = []
        # Retired predecessors never consume slots needed by usable replacements.
        # Filter relevance before taking six, rather than truncating unrelated rows.
        for row in self.db.execute('''SELECT l.*, CASE WHEN r.lesson IS NOT NULL OR l.contradictions>=l.supports
                                     THEN 1 ELSE 0 END AS retired FROM lessons l
                                     LEFT JOIN retirements r ON r.lesson=l.id
                                     ORDER BY retired ASC,(l.supports-l.contradictions) DESC,l.rowid DESC'''):
            conditions = json.loads(row['conditions'])
            if not tags.intersection(conditions):
                continue
            supports, contradictions = row['supports'],row['contradictions']
            games = self.db.execute("SELECT COUNT(DISTINCT e.game) FROM assessments a JOIN episodes e ON e.id=a.episode WHERE a.lesson=? AND a.verdict IN ('support','revise')",
                                    (row['id'],)).fetchone()[0]
            sources={};source_keys=set();matching_games=set()
            for evidence in self.db.execute('''SELECT e.payload,e.game,a.verdict FROM assessments a
                    JOIN episodes e ON e.id=a.episode WHERE a.lesson=? ORDER BY e.rowid DESC''',(row['id'],)):
                trajectory=json.loads(evidence['payload']).get('trajectory',[])
                source=execution_context(trajectory[-1]['observation'] if trajectory else {})
                key=encoded(source);source_keys.add(key)
                supported=evidence['verdict'] in ('support','revise')
                if (supported and current_context['rules_known'] and source['rules_known']
                        and current_context['rules_digest']==source['rules_digest']
                        and current_context['execution_mechanism']==source['execution_mechanism']):
                    matching_games.add(evidence['game'])
                if key not in sources and len(sources)<4:sources[key]={**source,'supporting_games':set(),'contradicting_games':set()}
                if key in sources and evidence['verdict']!='uncertain':
                    sources[key]['supporting_games' if supported else 'contradicting_games'].add(evidence['game'])
            provenance=[{**source,'supporting_games':len(source['supporting_games']),
                         'contradicting_games':len(source['contradicting_games'])} for source in sources.values()]
            lessons.append({'id':row['id'],'rule':row['rule'],'conditions':conditions,
                'supports':supports,'contradictions':contradictions,'supporting_games':games,
                'matching_supporting_games':len(matching_games),'evidence_contexts':provenance,
                'evidence_contexts_complete':len(source_keys)<=4,
                'status':'retired' if row['retired'] else 'challenged' if contradictions else 'active',
                'confidence':'supported' if len(matching_games)>=3 and contradictions==0 else 'hypothesis',
                'exceptions':json.loads(row['exceptions'] or '[]') if 'exceptions' in row.keys() else [],
                'mechanism':row['mechanism'] if 'mechanism' in row.keys() else ''})
            if lesson_limit is not None and len(lessons) == lesson_limit:
                break
        context = {'mode':self.mode,'lessons':lessons,'episodes':[],
                   'execution_context':{**current_context,'rules_source':rules_source}}
        if include_episodes and self.mode == 'learn':
            for row in self.db.execute('SELECT payload FROM episodes WHERE game=? AND day<=? AND assessed=0 ORDER BY rowid LIMIT 2',(game,day)):
                episode = json.loads(row['payload'])
                candidate={**context,'episodes':[*context['episodes'],episode]}
                if len(encoded(candidate).encode()) > CONTEXT_LIMIT:
                    continue
                context=candidate
        return context

    def assess(self,game,context,learning,*,evaluations=None,lesson_details=None):
        """Atomically accept reflection; strategic decisions are saved independently."""
        validate_learning(context,learning)
        saved = 0
        assessed = 0
        from contextlib import nullcontext
        transaction = nullcontext() if self.db.in_transaction else self.db
        with transaction:
            if not self.db.in_transaction:self.db.execute('BEGIN IMMEDIATE')
            for episode in context['episodes']:
                row=self.db.execute('SELECT payload FROM episodes WHERE id=? AND game=?',(episode['id'],game)).fetchone()
                if not row or json.loads(row['payload'])!=episode:raise ValueError('stale analysis episode')
            for item in learning['assessments']:
                if self.db.execute('SELECT 1 FROM assessments WHERE episode=?',(item['episode_id'],)).fetchone():
                    continue
                if not self.db.execute('SELECT 1 FROM episodes WHERE id=? AND game=?',(item['episode_id'],game)).fetchone():
                    raise ValueError('episode does not belong to this player game')
                lesson_id = item['lesson_id']
                previous_lesson = lesson_id if item['verdict'] == 'revise' else None
                if (item['verdict'] == 'support' and lesson_id is None) or item['verdict'] == 'revise':
                    row = self.db.execute('SELECT id FROM lessons WHERE rule=?',(item['rule'],)).fetchone()
                    lesson_id = row['id'] if row else uuid.uuid4().hex
                    self.db.execute('INSERT OR IGNORE INTO lessons(id,rule,conditions) VALUES(?,?,?)',
                                    (lesson_id,item['rule'],encoded(sorted(set(item['conditions'])))))
                if previous_lesson:
                    self.db.execute('INSERT OR REPLACE INTO retirements VALUES(?,?,?)',
                                    (previous_lesson,item['episode_id'],lesson_id))
                    self.db.execute('UPDATE lessons SET contradictions=contradictions+1 WHERE id=?',(previous_lesson,))
                if lesson_id is not None and item['verdict'] != 'uncertain':
                    column = 'supports' if item['verdict'] in ('support','revise') else 'contradictions'
                    self.db.execute(f'UPDATE lessons SET {column}={column}+1 WHERE id=?',(lesson_id,))
                    if item['verdict'] == 'support':
                        self.db.execute('DELETE FROM retirements WHERE lesson=?',(lesson_id,))
                    saved += 1
                self.db.execute('INSERT INTO assessments VALUES(?,?,?,?,?)',(item['episode_id'],lesson_id,
                    item['verdict'],encoded(item['evidence_ids']),item['explanation']))
                self.db.execute('UPDATE episodes SET assessed=1 WHERE id=?',(item['episode_id'],))
                assessed += 1
                if evaluations is not None:
                    evaluation=next(e for e in evaluations if e['episode_id']==item['episode_id'])
                    self.db.execute('INSERT INTO evaluations VALUES(?,?)',(item['episode_id'],encoded(evaluation)))
                details=(lesson_details or {}).get(item['episode_id'])
                if details and lesson_id is not None and item['verdict'] in ('support','revise'):
                    self.db.execute('UPDATE lessons SET exceptions=?,mechanism=? WHERE id=?',
                        (encoded(details['exceptions']),details['mechanism'],lesson_id))
        return {'lessons_updated':saved,'episodes_assessed':assessed}

    def record_decision(self,request,reply):
        if self.mode != 'learn':return
        game=request['memory']['experience_id']
        with self.db:
            if request.get('protocol') == 2:
                plan = reply.get('plan') or request.get('campaign') or {}
                action = {'kind':'strategic_plan','plan':plan,'revision':plan.get('revision'),
                          'goal_kinds':[g['kind'] for g in plan.get('goals',[])],
                          'execution':'unconfirmed'}
            else:
                action = dict(next(a for a in request['actions'] if a['id'] == reply['action_id']))
            if reply.get('follow_up_action_ids'):
                offered = {a['id']:a for a in request['actions']}
                action['planned_follow_ups'] = [offered[i] for i in reply['follow_up_action_ids']]
            self.db.execute('INSERT OR REPLACE INTO decisions VALUES(?,?,?,?,?,?)',(game,request['request_id'],
                request['observation'].get('day',0),encoded(facts(request)),encoded(action),reply.get('reason','')))

    def record_fallback(self,request,reply):
        if self.mode != 'learn':
            return
        action = next(a for a in request['actions'] if a['id'] == reply['action_id'])
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO decisions VALUES(?,?,?,?,?,?)',
                (request['memory']['experience_id'],request['request_id'],request['observation'].get('day',0),
                 encoded(facts(request)),encoded({**action,'provider':'fallback'}),
                 'No valid model decision: infrastructure fallback ends the turn; not a deliberate strategic choice.'))
