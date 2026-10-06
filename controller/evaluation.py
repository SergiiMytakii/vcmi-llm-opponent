"""Own-turn collection and review candidates; detectors never grade strategy."""
import hashlib
import json
from pathlib import Path
import re

try:
    from .experience import Experience, encoded, facts
except ImportError:
    from experience import Experience, encoded, facts


def signal_id(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()[:20]


def unchanged_actor(before,after,actor):
    a=next((h for h in before.get('heroes',[]) if h.get('ref')==actor),None)
    b=next((h for h in after.get('heroes',[]) if h.get('ref')==actor),None)
    return bool(a and b and isinstance(a.get('position'),list) and len(a['position'])==3
        and isinstance(a.get('army_value'),(int,float)) and a.get('position')==b.get('position')
        and a.get('army_value')==b.get('army_value'))


class TelemetryCollector:
    def __init__(self,database,journal,players,*,idle_turns=2,mine_turns=2,scouting_turns=3):
        self.database=Path(database);self.journal=Path(journal);self.players=set(players)
        self.offset=0;self.gap=False
        self.idle_turns=idle_turns;self.mine_turns=mine_turns;self.scouting_turns=scouting_turns

    def poll(self):
        if not self.journal.is_file():return 0
        if self.journal.stat().st_size<self.offset:self.offset=0;self.gap=True
        count=0
        with self.journal.open('rb') as stream:
            stream.seek(self.offset)
            while True:
                line=stream.readline(512*1024+1)
                if not line:break
                if not line.endswith(b'\n'):break  # Retry an incomplete append.
                self.offset=stream.tell()
                try:
                    if len(line)>512*1024:raise ValueError('oversized own event')
                    event=json.loads(line)
                    if self.ingest(event):count+=1
                except (ValueError,TypeError,KeyError):self.gap=True
        return count

    def ingest(self,event):
        if not isinstance(event,dict):raise ValueError('invalid own telemetry')
        if event.get('version')!=1 or event.get('phase') not in ('begin','end','decision','execution','terminal'):raise ValueError('invalid own telemetry')
        player=event.get('player');day=event.get('day');sequence=event.get('sequence')
        if type(player) is not int or type(day) is not int or day<1 or type(sequence) is not int or sequence<1:raise ValueError('invalid event identity')
        if self.players and player not in self.players:return False
        for field in ('game','generation'):
            if not isinstance(event.get(field),str) or not re.fullmatch(r'[A-Za-z0-9-]{1,64}',event[field]):raise ValueError('invalid own game identity')
        world=event.get('observation')
        if not isinstance(world,dict) or world.get('player')!=player or world.get('day')!=day:raise ValueError('event observation belongs to another player/day')
        if event['phase']=='begin':self.gap=False
        event={**event,'complete':event.get('complete') is True and not self.gap}
        if event['phase']=='execution':
            result=event.get('own_result',{})
            if not isinstance(result,dict) or not isinstance(result.get('action'),dict):raise ValueError('invalid execution receipt')
            action=result['action']
            if result.get('player')!=player or result.get('day')!=day:raise ValueError('foreign execution receipt')
            if action.get('kind')=='battle':
                if action.get('player')!=player:raise ValueError('foreign battle receipt')
            elif any(not isinstance(action.get(k),dict) or action[k].get('player')!=player for k in ('before','after')):raise ValueError('foreign own-state receipt')
        store=Experience(self.database,'learn')
        try:
            if store.db.execute('SELECT 1 FROM turn_events WHERE game=? AND generation=? AND sequence=?',
                (event['game'],event['generation'],sequence)).fetchone():return False
            with store.db:
                if event['phase']=='begin':
                    old=store.db.execute('SELECT MAX(day) FROM turn_events WHERE game=? AND generation!=?',
                        (event['game'],event['generation'])).fetchone()[0]
                    if old is not None and old>=day:
                        for row in store.db.execute('SELECT id,payload FROM episodes WHERE game=? AND day>=? AND assessed=0',(event['game'],day)).fetchall():
                            for sig in json.loads(row['payload'])['signals']:
                                store.db.execute('DELETE FROM observed_signals WHERE game=? AND id=?',(event['game'],sig['id']))
                            store.db.execute('DELETE FROM episodes WHERE id=?',(row['id'],))
                        store.db.execute('DELETE FROM decisions WHERE game=? AND day>=?',(event['game'],day))
                        store.db.execute('DELETE FROM turn_events WHERE game=? AND day>=? AND generation!=?',
                            (event['game'],day,event['generation']))
                store.db.execute('INSERT INTO turn_events VALUES(?,?,?,?,?,?)',
                    (event['game'],event['generation'],sequence,day,event['phase'],encoded(event)))
            if event['phase'] in ('end','terminal'):
                start=store.db.execute("SELECT sequence FROM turn_events WHERE game=? AND generation=? AND day=? AND phase='begin' ORDER BY sequence DESC LIMIT 1",
                    (event['game'],event['generation'],day)).fetchone()
                executions=[json.loads(r[0])['own_result'] for r in store.db.execute(
                    "SELECT payload FROM turn_events WHERE game=? AND generation=? AND day=? AND phase='execution' AND sequence>? AND sequence<? ORDER BY sequence",
                    (event['game'],event['generation'],day,start[0] if start else 0,sequence))]
                receipts={r['sequence']:r for r in [*event.get('results',[]),*executions] if type(r.get('sequence')) is int}
                event={**event,'results':list(receipts.values())}
                with store.db:store.db.execute('UPDATE turn_events SET payload=? WHERE game=? AND generation=? AND sequence=?',
                    (encoded(event),event['game'],event['generation'],sequence))
            # Begin supplies the first baseline, including a terminal on turn one.
            # End/terminal expose consequences even with no GPT strategy call.
            if event['phase'] in ('begin','end','terminal'):
                request={'protocol':2,'request_id':f"{event['game']}:{event['generation']}:{player}:{day}:telemetry:{sequence}",
                    'memory':{'experience_id':event['game'],'recent_results':event.get('results',[])},'observation':world}
                store.observe(request)
                self._event_evidence(store,event,request['request_id'])
                action={'kind':'native_turn','phase':event['phase'],'plan':event.get('campaign'),
                    'execution':'observed','source':'own-turn telemetry'}
                with store.db:store.db.execute('INSERT OR IGNORE INTO decisions VALUES(?,?,?,?,?,?)',
                    (event['game'],request['request_id'],day,encoded(facts(request)),encoded(action),
                     'Continue the engine-accepted plan; no new model decision.'))
            self._candidates(store,event)
        finally:store.close()
        return True

    def _event_evidence(self,store,event,request_id):
        # Consequence episodes need the snapshot before the affected execution,
        # not a fresh forecast recomputed after the result became known.
        rows=store.db.execute('SELECT id,payload FROM episodes WHERE game=? AND request=? AND assessed=0',
            (event['game'],request_id)).fetchall()
        history=[json.loads(row[0]) for row in store.db.execute(
            'SELECT payload FROM turn_events WHERE game=? AND generation=? AND sequence<=? ORDER BY sequence',
            (event['game'],event['generation'],event['sequence']))]
        for row in rows:
            episode=json.loads(row['payload'])
            affected={s['sequence'] for s in episode['signals'] if s.get('kind')=='action_result'}
            executions=[e for e in history if (e['phase']=='execution' and e['own_result']['sequence'] in affected)
                or (e['phase']=='decision' and any(r.get('sequence') in affected for r in e.get('results',[])))]
            boundary=min([e['sequence'] for e in executions] or [event['sequence']])
            before=next((e for e in reversed(history) if e['sequence']<boundary
                and e['phase'] in ('begin','decision','end')),None)
            if before is None:continue
            interval=[e for e in history if before['sequence']<=e['sequence']<=event['sequence']]
            complete=all(e['complete'] for e in interval) and all(
                b['sequence']==a['sequence']+1 for a,b in zip(interval,interval[1:]))
            prior=[]
            for opportunity in before['observation'].get('opportunities',[]):
                signal={**opportunity,'kind':'opportunity','opportunity_kind':opportunity.get('kind'),
                    'stage':'before','day':before['day'],'journal_sequence':before['sequence']}
                signal['id']=signal_id(signal);prior.append(signal)
            candidate={**episode,'category':'event','prechoice_complete':complete,
                'prechoice':{'day':before['day'],'phase':before['phase'],'sequence':before['sequence'],
                    'observation':before['observation'],'accepted_campaign':before.get('campaign')},
                'signals':[*prior,*episode['signals']]}
            if len(encoded(candidate).encode())<=65536:
                with store.db:store.db.execute('UPDATE episodes SET payload=? WHERE id=? AND assessed=0',
                    (encoded(candidate),row['id']))

    def _candidates(self,store,event):
        if event['phase']!='end':return
        events=[json.loads(r[0]) for r in store.db.execute(
            'SELECT payload FROM turn_events WHERE game=? AND generation=? AND day<=? ORDER BY sequence',
            (event['game'],event['generation'],event['day']))]
        # A complete pair needs all intervening journal sequence numbers.
        pairs=[];begin=None;last_sequence=None
        for item in events:
            if last_sequence is not None and item['sequence']!=last_sequence+1:begin=None
            last_sequence=item['sequence']
            if item['phase']=='begin':begin=item if item['complete'] else None
            elif item['phase']=='end':
                if begin and item['complete'] and begin['day']==item['day']:pairs.append((begin,item))
                begin=None
            elif not item['complete']:begin=None
        if not pairs or pairs[-1][1]['day']!=event['day']:return
        current=pairs[-1][0]['observation'];idle=current.get('main_army_idle',{});main=idle.get('hero_ref')
        subjects=[('idle_main',main,None,self.idle_turns)] if main else []
        for opportunity in current.get('opportunities',[]):
            if opportunity.get('kind')=='capture_mine' and opportunity.get('available') is True:
                subjects.append(('ignored_mine',opportunity.get('actor_ref'),opportunity.get('target_ref'),self.mine_turns))
            if opportunity.get('kind')=='scout' and current.get('scouting_blocked') is True:
                subjects.append(('missing_scouting',opportunity.get('actor_ref'),opportunity.get('target_ref'),self.scouting_turns))
        for category,actor,target,threshold in subjects:
            window=[];next_day=event['day']
            for start,end in reversed(pairs):
                before=start['observation'];after=end['observation']
                if end['day']!=next_day or not unchanged_actor(before,after,actor):break
                hero=next((h for h in after.get('heroes',[]) if h.get('ref')==actor),{})
                if category=='idle_main' and hero.get('movement',0)<max(500,hero.get('movement_per_day',0)/2):break
                relevant=[o for o in before.get('opportunities',[]) if o.get('actor_ref')==actor
                    and (target is None or o.get('target_ref')==target) and o.get('available') is True]
                if category!='idle_main' and not relevant:break
                if category=='missing_scouting' and before.get('scouting_blocked') is not True:break
                completed=after.get('goal_statuses',{})
                assigned=[g for g in (start.get('campaign') or {}).get('goals',[]) if g.get('actor_ref')==actor]
                if any(completed.get(g['id'],{}).get('state')=='completed' for g in assigned):break
                if category=='missing_scouting' and (before.get('observed_frontiers')!=after.get('observed_frontiers')
                        or before.get('observed_scout_areas')!=after.get('observed_scout_areas')):break
                window.append((start,end));next_day-=1
            if len(window)<threshold:continue
            window.reverse()
            ident=signal_id({'game':event['game'],'generation':event['generation'],'category':category,
                'actor':actor,'target':target,'first_day':window[0][0]['day']})
            signals=[]
            for start,end in window:
                for o in start['observation'].get('opportunities',[]):
                    if o.get('actor_ref')==actor and (target is None or o.get('target_ref')==target):
                        sig={**o,'kind':'opportunity','opportunity_kind':o.get('kind'),'stage':'before','day':start['day']}
                        sig['id']=signal_id(sig);signals.append(sig)
                sig={'kind':'no_target_progress','stage':'after','day':end['day'],'actor_ref':actor,
                    'reason':end['observation'].get('main_army_idle',{}).get('reason','unknown')}
                sig['id']=signal_id(sig);signals.append(sig)
            episode={'id':ident,'category':category,'window':{'first_day':window[0][0]['day'],
                'last_day':event['day'],'complete':True},'trajectory':[{'request_id':f"turn:{start['sequence']}",
                    'observation':{**start['observation'],'opportunities':[o for o in start['observation'].get('opportunities',[]) if o.get('actor_ref')==actor and (target is None or o.get('target_ref')==target)][:4]},'action':{'kind':'accepted_campaign','plan_at_start':start.get('campaign'),'plan_at_end':end.get('campaign')},
                    'results':end.get('results',[]),
                    'expectation':start.get('reason','')} for start,end in window[:3]],
                'after':{**window[-1][1]['observation'],'opportunities':[],
                    'accepted_campaign':window[-1][1].get('campaign'),'results':window[-1][1].get('results',[])},'signals':signals[:64]}
            if len(encoded(episode).encode())>65536:continue
            with store.db:store.db.execute('INSERT OR IGNORE INTO episodes VALUES(?,?,?,?,?,0)',
                (ident,event['game'],f"window:{ident}",event['day'],encoded(episode)))
