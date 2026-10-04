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
import uuid

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / '.build/experience.sqlite3'
CONDITIONS = ('combat', 'defense', 'economy', 'reinforcement', 'exploration', 'tempo')
KINDS = {'attack':'combat', 'build':'economy', 'recruit':'reinforcement',
         'transfer':'reinforcement', 'upgrade':'reinforcement', 'explore':'exploration',
         'visit':'exploration', 'hire_hero':'exploration', 'end_turn':'tempo'}
CONTEXT_LIMIT = 32768


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def facts(request):
    """Small factual projection, with completeness explicit before inferring loss."""
    obs = request['observation']
    result = {k:obs[k] for k in ('day','player','resources','resource_order','terminal_result') if k in obs}
    for name in ('heroes', 'towns'):
        if isinstance(obs.get(name), list):
            result[name + '_complete'] = len(obs[name]) <= 32
            result[name] = [{k:item[k] for k in ('id','position','strength','army','buildings','daily_income') if k in item}
                            for item in obs[name][:32]]
    # Visible threats can explain the information available before a choice.
    if isinstance(obs.get('visible_objects'),list):
        result['visible_objects'] = [{k:item[k] for k in ('id','kind','owner','position','strength','army') if k in item}
                                     for item in obs['visible_objects'][:16]]
    return result


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
    assessments = {'type':'array','minItems':len(context['episodes']),'maxItems':2,'items':assessment} if context['episodes'] else {'type':'array','maxItems':0,'items':{'type':'string'}}
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
                CREATE INDEX IF NOT EXISTS decisions_game_day ON decisions(game,day);
                CREATE INDEX IF NOT EXISTS episodes_game_day ON episodes(game,day);
                PRAGMA user_version=1;
            ''')

    @classmethod
    def for_request(cls,request):
        game = request.get('memory',{}).get('experience_id')
        mode = os.environ.get('VCMI_EXPERIENCE_MODE','learn')
        if mode == 'off' or not isinstance(game,str) or not re.fullmatch(r'[A-Za-z0-9-]{1,64}',game):
            return None
        return cls(os.environ.get('VCMI_EXPERIENCE_DB',str(DEFAULT_DB)),mode)

    def close(self):
        self.db.close()

    def prepare(self,request):
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
                    return row['day'] > day or (row['day'] == day and attempt is not None
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
                        while len(episode['trajectory']) > 1 and len(encoded(episode).encode()) > 24000:
                            episode['trajectory'].pop(0)
                        if len(encoded(episode).encode()) <= 24000:
                            self.db.execute('INSERT OR IGNORE INTO episodes(id,game,request,day,payload) VALUES(?,?,?,?,?)',
                                            (eid,game,request['request_id'],day,encoded(episode)))
                            for signal in fresh:
                                self.db.execute('INSERT OR IGNORE INTO observed_signals VALUES(?,?)',(game,signal['id']))
        tags = {'defense','tempo'} | {KINDS[a['kind']] for a in request['actions'] if a['kind'] in KINDS}
        if request['observation'].get('terminal_result') in ('win','loss'):
            tags.update(CONDITIONS)
        else:
            for row in self.db.execute('SELECT payload FROM episodes WHERE game=? AND day<=? AND assessed=0 ORDER BY rowid LIMIT 2',(game,day)):
                for decision in json.loads(row['payload'])['trajectory']:
                    kind = decision['action'].get('kind')
                    if kind in KINDS:
                        tags.add(KINDS[kind])
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
            lessons.append({'id':row['id'],'rule':row['rule'],'conditions':conditions,
                'supports':supports,'contradictions':contradictions,'supporting_games':games,
                'status':'retired' if row['retired'] else 'challenged' if contradictions else 'active',
                'confidence':'supported' if games >= 3 and contradictions == 0 else 'hypothesis'})
            if len(lessons) == 6:
                break
        context = {'mode':self.mode,'lessons':lessons,'episodes':[]}
        if self.mode == 'learn':
            for row in self.db.execute('SELECT payload FROM episodes WHERE game=? AND day<=? AND assessed=0 ORDER BY rowid LIMIT 2',(game,day)):
                episode = json.loads(row['payload'])
                if len(encoded({**context,'episodes':[*context['episodes'],episode]}).encode()) <= CONTEXT_LIMIT:
                    context['episodes'].append(episode)
        return context

    def accept(self,request,reply):
        """One transaction: evidence assessments, lesson updates and chosen intent."""
        learning = reply['learning']
        validate_learning(request['experience'],learning)
        game = request['memory']['experience_id']
        saved = 0
        with self.db:
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
            action = next(a for a in request['actions'] if a['id'] == reply['action_id'])
            self.db.execute('INSERT OR REPLACE INTO decisions VALUES(?,?,?,?,?,?)',(game,request['request_id'],
                request['observation'].get('day',0),encoded(facts(request)),encoded(action),learning['expectation']))
        return {'lessons_updated':saved,'episodes_assessed':len(learning['assessments']),
                'lessons_supplied':len(request['experience']['lessons'])}

    def record_fallback(self,request,reply):
        if self.mode != 'learn':
            return
        action = next(a for a in request['actions'] if a['id'] == reply['action_id'])
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO decisions VALUES(?,?,?,?,?,?)',
                (request['memory']['experience_id'],request['request_id'],request['observation'].get('day',0),
                 encoded(facts(request)),encoded({**action,'provider':'fallback'}),
                 'No valid model decision: infrastructure fallback ends the turn; not a deliberate strategic choice.'))
