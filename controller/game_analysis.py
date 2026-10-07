"""Evidence-linked review of completed player games; no strategic commands."""
import hashlib
import json
from pathlib import Path

from codex import invoke_model
from experience import Experience, encoded
from knowledge import publish
from strategy import _validate_shape
from prompt_context import encode_request

CHUNK_BYTES=128000


def object_schema(properties):
    return {'type':'object','additionalProperties':False,'required':list(properties),'properties':properties}


def text_schema(limit=1200):
    return {'type':'string','minLength':1,'maxLength':limit}


def refs_schema(ids):
    return {'type':'array','minItems':1,'maxItems':8,'items':{'type':'string','enum':ids}}


def evidence_for_game(store,game,decisions):
    events=[json.loads(r[0]) for r in store.db.execute('SELECT payload FROM turn_events WHERE game=? ORDER BY day,rowid',(game,))]
    records=[];sources=[];gaps=[];sequences={}
    for event in events:
        generation=event['generation'];sequence=event['sequence']
        if sequence!=sequences.get(generation,0)+1 or event.get('complete') is not True:gaps.append(f'{generation}:{sequence}')
        sequences[generation]=sequence
        eid=f"event:{generation}:{sequence}"
        data={key:value for key,value in event.items() if key not in ('game','generation','sequence','version','complete')}
        records.append({'id':eid,'day':event['day'],'kind':'own_event','data':data})
        sources.append({'id':eid,'kind':'turn_events','game':game,'generation':generation,'sequence':sequence})
    active_slots={(e['generation'],e['day']) for e in events}
    if decisions and Path(decisions).is_dir():
        for directory in sorted(Path(decisions).iterdir()):
            request_file=directory/'request.json'
            if not request_file.is_file():continue
            request=json.loads(request_file.read_text())
            if request.get('memory',{}).get('experience_id')!=game:continue
            day=request.get('identity',{}).get('day',request.get('observation',{}).get('day',0))
            if (request.get('identity',{}).get('generation'),day) not in active_slots:continue
            rid='model:'+request['request_id']
            answer_file=directory/'reply.json'
            if not answer_file.is_file():answer_file=directory/'stdout.bin'
            try:answer=json.loads(answer_file.read_text()) if answer_file.is_file() else None
            except ValueError:answer=None
            metadata_file=directory/'explanation.json'
            metadata=json.loads(metadata_file.read_text()) if metadata_file.is_file() else {}
            # Full pre-choice request and returned plan; CLI events remain raw audit
            # artifacts, not private thought or additional game observations.
            records.append({'id':rid,'day':day,'kind':'model_decision','request':request,'answer':answer,'metadata':metadata})
            sources.append({'id':rid,'kind':'model_call','directory':str(directory.resolve()),
                            'request_sha256':hashlib.sha256(request_file.read_bytes()).hexdigest()})
    signals=[]
    for row in store.db.execute('SELECT payload FROM episodes WHERE game=? AND assessed=0 ORDER BY day,rowid',(game,)):
        episode=json.loads(row[0])
        for signal in episode['signals']:
            if not any(s['id']==signal['id'] for s in signals):signals.append(signal)
    # Existing opportunity receipts provide checked before-choice alternatives.
    for signal in signals:
        records.append({'id':signal['id'],'day':signal.get('day',0),'kind':'episode_signal','data':signal})
    raw=encoded({'events':events,'records':records,'signals':signals})
    expected={r.get('action',{}).get('request_id') for e in events for r in e.get('results',[])
              if r.get('action',{}).get('kind')=='strategic_decision'}
    actual={r['request']['request_id'] for r in records if r['kind']=='model_decision'}
    coverage={'missing_model_calls':sorted(i for i in expected-actual if i),'events':len(events),'model_calls':sum(r['kind']=='model_decision' for r in records),
              'first_day':min(e['day'] for e in events),'last_day':max(e['day'] for e in events),
              'gaps':gaps,'has_initial_snapshot':any(e['phase']=='begin' for e in events),'from_start':min(e['day'] for e in events)==1 and any(e['phase']=='begin' and e['day']==1 for e in events)}
    records.sort(key=lambda r:r['day'])
    return events,records,signals,sources,coverage,hashlib.sha256(raw.encode()).hexdigest()


def chunks(records):
    # Lossless wire size matters: repeated snapshots share values in Codex input.
    if len(records)<=1 or len(encoded(encode_request({'records':records})).encode())<=CHUNK_BYTES:
        return [records] if records else []
    middle=len(records)//2
    return chunks(records[:middle])+chunks(records[middle:])


def review_completed_game(database,*,decisions=None,records=None,timeout=60,model='gpt-6.1-sol',effort='low',max_calls=12,max_tokens=200000,games=None):
    from analyze import analysis_schema,validate_analysis
    store=Experience(database,'learn')
    try:
        terminal=None
        for row in store.db.execute("SELECT payload FROM turn_events WHERE phase='terminal' ORDER BY rowid"):
            item=json.loads(row[0])
            if games is not None and item['game'] not in games:continue
            if item.get('complete') is True and item['observation'].get('terminal_result') in ('win','loss'):
                if not store.db.execute('SELECT 1 FROM game_reviews WHERE game=?',
                        (item['game'],)).fetchone():terminal=item;break
        if terminal is None:return {'status':'waiting_for_terminal'}
        game=terminal['game'];events,evidence,signals,sources,coverage,digest=evidence_for_game(store,game,decisions)
        rid=hashlib.sha256(game.encode()).hexdigest()[:24]
        directory=Path(records or Path(database).parent/'game-reviews')/rid
        directory.mkdir(parents=True,exist_ok=True)
        (directory/'evidence.json').write_text(encoded({'coverage':coverage,'records':evidence,'sources':sources}))
        parts=chunks(evidence)
        if len(parts)+1>max_calls:raise ValueError('whole-game review exceeds call budget; no partial review was learned')
        usage={'input_tokens':0,'output_tokens':0};summaries=[]
        instructions=(Path(__file__).with_name('game_analysis_instructions.txt')).read_text()
        call_count=0
        def call(payload,schema,name):
            nonlocal call_count
            folder=directory/name;folder.mkdir(exist_ok=True)
            call_count+=1;accounted=False
            try:
                reply,metadata=invoke_model(payload,schema,instructions,timeout=timeout,model=model,effort=effort,
                    decision_dir=folder,max_output_bytes=16384)
                tokens=metadata.get('usage')
                if not isinstance(tokens,dict) or any(type(tokens.get(k)) is not int or tokens[k]<0 for k in usage):
                    raise ValueError('unknown review usage; no lessons accepted')
                for key in usage:usage[key]+=tokens[key]
                accounted=True
                _validate_shape(reply,schema)
                if sum(usage.values())>max_tokens:raise ValueError('whole-game review exceeds token budget; no partial review was learned')
                return reply
            except Exception as error:
                if not accounted:
                    failed=getattr(error,'usage',None)
                    known=isinstance(failed,dict) and all(type(failed.get(k)) is int and failed[k]>=0 for k in usage)
                    if known:
                        for key in usage:usage[key]+=failed[key]
                    else:error.usage=None
                if accounted or (not accounted and known):error.usage=dict(usage)
                error.model_calls=call_count
                raise
        for index,part in enumerate(parts):
            ids=[r['id'] for r in part]
            schema=object_schema({'summary':text_schema(4000),'observations':{'type':'array','minItems':0,'maxItems':12,
                'items':object_schema({'text':text_schema(600),'evidence_ids':refs_schema(ids)})}})
            reply=call({'game_analysis_version':1,'stage':'chronology','game':game,'part':index,
                        'coverage':coverage,'earlier_summaries':summaries,'records':part},schema,f'part-{index}')
            summaries.append(reply)
        # Every cited raw record stays available alongside the summary. A final
        # finding must cite raw IDs; summaries cannot become replacement evidence.
        last_observation=next((e['observation'] for e in reversed(events) if e['phase']!='terminal'),terminal['observation'])
        request={'protocol':2,'request_id':'whole-game-review','memory':{'experience_id':game},
                 'observation':{**last_observation,'day':terminal['day'],'terminal_result':terminal['observation']['terminal_result']}}
        context=store.context(request,include_episodes=False,lesson_limit=None)
        raw_signals={s['id']:s for s in signals}
        for record in evidence:
            raw_signals.setdefault(record['id'],{'id':record['id'],'kind':record['kind'],'day':record['day'],
                'stage':'before' if record['kind']=='model_decision' else 'after','record':record})
        episode={'id':'whole-game','trajectory':[{'observation':last_observation}],
                 'after':request['observation'],'signals':list(raw_signals.values()),'prechoice_complete':False}
        cited=set(i for s in summaries for o in s['observations'] for i in o['evidence_ids'])
        accessible={r['id'] for r in evidence if r['id'] in cited or r['kind']=='episode_signal'}
        episode['signals']=[s for s in episode['signals'] if s['id'] in accessible]
        context['episodes']=[episode]
        fields=analysis_schema(context)['properties']
        ids=[s['id'] for s in episode['signals']]
        finding=object_schema({'assessment':fields['assessments']['items'],'evaluation':fields['evaluations']['items'],
            'decision_evidence_id':{'type':['string','null'],'enum':[None,*[r['id'] for r in evidence if r['kind']=='model_decision' and r['id'] in accessible]]}})
        schema=object_schema({'summary':text_schema(4000),'strategy':text_schema(4000),
            'turning_points':{'type':'array','minItems':1,'maxItems':12,
                'items':object_schema({'text':text_schema(600),'evidence_ids':refs_schema(ids)})},
            'findings':{'type':'array','minItems':0,'maxItems':5 if coverage['has_initial_snapshot'] else 0,'items':finding}})
        # The full source is reduced only through the evidence-bearing summaries;
        # checked opportunities and cited raw records accompany final synthesis.
        payload={'game_analysis_version':1,'stage':'synthesis','game':game,'outcome':terminal['observation']['terminal_result'],
            'coverage':coverage,'chronology':summaries,'lessons':context['lessons'],
            'evidence':[r for r in evidence if r['id'] in cited or r['kind']=='episode_signal']}
        report=call(payload,schema,'synthesis')
        prepared=[];lesson_keys=set()
        for index,f in enumerate(report['findings']):
            evaluation=f['evaluation'];alternative=raw_signals.get(evaluation['alternative_evidence_id'])
            decision=next((r for r in evidence if r['id']==f['decision_evidence_id']),None)
            assessment=f['assessment']
            existing=next((l['id'] for l in context['lessons'] if l['rule']==assessment['rule']),None)
            lesson_key=assessment['lesson_id'] or existing or 'rule:'+ ' '.join(assessment['rule'].casefold().split())
            if lesson_key in lesson_keys:raise ValueError('one game cannot reinforce the same lesson twice')
            lesson_keys.add(lesson_key)
            if evaluation['decision_quality']=='avoidable_mistake':
                if (coverage['gaps'] or coverage['missing_model_calls'] or not coverage['from_start'] or not decision or not isinstance(decision.get('answer'),dict) or not alternative
                        or alternative.get('day')!=decision['day']):
                    raise ValueError('mistake requires complete contemporaneous decision/alternative evidence')
                boundary=next((e for e in events if e['phase']=='decision' and e['generation']==decision['request'].get('identity',{}).get('generation')
                    and any(r.get('action',{}).get('request_id')==decision['request']['request_id']
                            for r in e.get('results',[]))),None)
                prior=next((e for e in reversed(events) if boundary and e['generation']==boundary['generation']
                    and e['sequence']<boundary['sequence'] and e['phase'] in ('begin','decision','end')),None)
                if not prior or alternative.get('journal_sequence')!=prior['sequence']:
                    raise ValueError('alternative was not observed at the pre-choice snapshot')
                if any(e['phase']=='execution' and e['generation']==boundary['generation']
                       and prior['sequence']<e['sequence']<boundary['sequence'] for e in events):
                    raise ValueError('pre-choice feasibility changed after the offered snapshot')
                offered={k:v for k,v in alternative.items() if k not in ('id','stage','day','journal_sequence','opportunity_kind')}
                offered['kind']=alternative.get('opportunity_kind')
                if offered not in prior['observation'].get('opportunities',[]):
                    raise ValueError('alternative is absent from the active pre-choice snapshot')
                episode['prechoice_complete']=True
            else:episode['prechoice_complete']=False
            answer={'assessments':[f['assessment']],'evaluations':[evaluation]}
            learning,details=validate_analysis(context,answer)
            eid=rid+':'+str(index)
            copied={**episode,'id':eid}
            learning['assessments'][0]['episode_id']=eid
            details={eid:details['whole-game']};evaluation={**evaluation,'episode_id':eid}
            prepared.append((copied,learning,details,evaluation))
        # One transaction: malformed findings, stale review or a failed model
        # never publish part of a game's lessons.
        with store.db:
            store.db.execute('BEGIN IMMEDIATE')
            if store.db.execute('SELECT 1 FROM game_reviews WHERE game=?',
                    (game,)).fetchone():return {'status':'already_reviewed'}
            if evidence_for_game(store,game,decisions)[-1]!=digest:
                raise ValueError('game evidence changed during review; no lessons accepted')
            # Apply the validated assessments using the existing persistence rules.
            for ep,learning,details,evaluation in prepared:
                store.db.execute('INSERT INTO episodes VALUES(?,?,?,?,?,0)',(ep['id'],game,'whole-game-review',terminal['day'],encoded(ep)))
            # Commit report/lesson updates through a savepoint-aware assess owner.
            for ep,learning,details,evaluation in prepared:
                store.assess(game,{**context,'episodes':[ep]},learning,evaluations=[evaluation],lesson_details=details)
            store.db.execute('INSERT INTO game_reviews VALUES(?,?,?,?,?,?)',
                (game,terminal['generation'],terminal['sequence'],digest,encoded({**report,'coverage':coverage,
                    'chronology':summaries,'evidence':evidence,'sources':sources}),encoded(usage)))
        publish(database)
        (directory/'report.json').write_text(encoded({'game':game,'coverage':coverage,'source_hash':digest,'usage':usage,**report}))
        return {'status':'game_reviewed','game':game,'findings':len(prepared),'report':str(directory/'report.json'),'usage':usage,'model_calls':len(parts)+1}
    finally:store.close()
