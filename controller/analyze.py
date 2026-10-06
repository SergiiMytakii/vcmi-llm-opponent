"""Bounded, separate reflection calls; never participates in a strategy exchange."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import re
import sys
import time

from codex import invoke_model, MODEL, REASONING_EFFORT
from experience import Experience, learning_schema, validate_learning, encoded
from knowledge import publish
from strategy import _validate_shape

ROOT=Path(__file__).resolve().parent
OUTCOMES=['benefit','harm','missed_opportunity','no_material_change','unknown']
QUALITY=['supported','avoidable_mistake','uncertain']
RESPONSIBILITY=['strategy','native_execution','infrastructure','external','mixed','unknown']


def analysis_schema(context):
    assessment=learning_schema(context)['properties']['assessments']
    if context['episodes']:
        properties=assessment['items']['properties']
        properties['exceptions']={'type':'array','minItems':0,'maxItems':4,'items':{'type':'string','maxLength':160}}
        properties['mechanism']={'type':'string','maxLength':240}
        assessment['items']['required']+=['exceptions','mechanism']
    before_ids=[s['id'] for e in context['episodes'] for s in e['signals'] if s.get('stage')=='before']
    after_ids=[s['id'] for e in context['episodes'] for s in e['signals'] if s.get('stage')!='before']
    fields={'episode_id':{'type':'string','enum':[e['id'] for e in context['episodes']]},
        'outcome':{'type':'string','enum':OUTCOMES},'decision_quality':{'type':'string','enum':QUALITY},
        'responsibility':{'type':'string','enum':RESPONSIBILITY},
        'before_evidence_ids':{'type':'array','minItems':0,'maxItems':8 if before_ids else 0,
            'items':{'type':'string','enum':before_ids} if before_ids else {'type':'string'}},
        'after_evidence_ids':{'type':'array','minItems':1,'maxItems':8,'items':{'type':'string','enum':after_ids}},
        'alternative_evidence_id':{'type':['string','null'],'enum':[None,*before_ids]},
        **{k:{'type':'string','minLength':1,'maxLength':480} for k in ('explanation','uncertainty','impact')}}
    count=len(context['episodes'])
    return {'type':'object','additionalProperties':False,'required':['evaluations','assessments'],
        'properties':{'assessments':assessment,'evaluations':{'type':'array','minItems':count,'maxItems':count,
            'items':{'type':'object','additionalProperties':False,'required':list(fields),'properties':fields}}}}


def validate_analysis(context,reply):
    _validate_shape(reply,analysis_schema(context))
    episodes={e['id']:e for e in context['episodes']};seen=set();details={};assessments=[]
    for item in reply['evaluations']:
        eid=item['episode_id']
        if eid in seen:raise ValueError('duplicate episode evaluation')
        seen.add(eid);signals={s['id']:s for s in episodes[eid]['signals']}
        before=item['before_evidence_ids'];after=item['after_evidence_ids']
        if any(i not in signals or signals[i].get('stage')!='before' for i in before):raise ValueError('unobserved pre-choice evidence')
        if any(i not in signals or signals[i].get('stage')=='before' for i in after):raise ValueError('unobserved outcome evidence')
        alt=item['alternative_evidence_id']
        if alt is not None and alt not in before:raise ValueError('alternative was not contemporaneous evidence')
        if item['decision_quality']=='avoidable_mistake':
            opportunity=signals.get(alt,{})
            if opportunity.get('kind')!='opportunity' or opportunity.get('available') is not True or opportunity.get('constraints_checked') is not True:
                raise ValueError('mistake requires an observed feasible alternative')
            if episodes[eid].get('category') in ('idle_main','ignored_mine','missing_scouting'):
                if not episodes[eid].get('window',{}).get('complete',False):raise ValueError('incomplete window cannot prove avoidable omission')
            elif episodes[eid].get('prechoice_complete') is not True:
                raise ValueError('event mistake requires complete pre-choice evidence')
    if seen!=set(episodes):raise ValueError('every episode needs evaluation')
    for item in reply['assessments']:
        details[item['episode_id']]={k:item[k] for k in ('exceptions','mechanism')}
        for value in item['exceptions']:
            if len(value.encode('utf-8'))>160:raise ValueError('lesson exception exceeds byte limit')
        if len(item['mechanism'].encode('utf-8'))>240:raise ValueError('lesson mechanism exceeds byte limit')
        for value in [item['rule'],item['mechanism'],*item['exceptions']]:
            if re.search(r'object:|tile:|\[\s*-?\d+\s*,\s*-?\d+\s*,\s*-?\d+\s*\]',value):
                raise ValueError('lesson contains game-local knowledge')
        assessments.append({k:v for k,v in item.items() if k not in ('exceptions','mechanism')})
        evaluation=next(e for e in reply['evaluations'] if e['episode_id']==item['episode_id'])
        if evaluation['responsibility'] in ('infrastructure','native_execution') and item['verdict'] in ('support','revise'):
            raise ValueError('technical failures cannot create strategic lessons')
    learning={'expectation':'Separate reflection; no game command.','assessments':assessments}
    validate_learning(context,learning)
    return learning,details


@contextmanager
def analyst_lock(database):
    path=Path(str(database)+'.analyst.lock');path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as stream:
        if os.name=='nt':
            import msvcrt
            if path.stat().st_size==0:stream.write(b'0');stream.flush()
            stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield


def analyze_once(database,*,timeout=60,model=MODEL,effort=REASONING_EFFORT,record_dir=None):
    store=Experience(database,'learn')
    try:
        publish(database)  # Recover publication even if no pending episode remains.
        row=store.db.execute('SELECT game,day FROM episodes WHERE assessed=0 ORDER BY rowid LIMIT 1').fetchone()
        if not row:return {'status':'idle'}
        latest=store.db.execute('SELECT request,payload FROM decisions WHERE game=? ORDER BY rowid DESC LIMIT 1',(row['game'],)).fetchone()
        observation=json.loads(latest['payload']) if latest else {'day':row['day']}
        observation['day']=max(observation.get('day',0),row['day'])
        request={'protocol':2 if observation.get('execution_mechanism')=='native_campaign_v3' else 1,
            'request_id':latest['request'] if latest else 'separate-analysis','memory':{'experience_id':row['game']},'observation':observation}
        context=store.context(request)
        if not context['episodes']:return {'status':'idle'}
        # No DB transaction is held while waiting for the model.
        payload={'analysis_version':1,'game':row['game'],**context}
        answer,metadata=invoke_model(payload,analysis_schema(context),
            (ROOT/'analysis_instructions.txt').read_text(),timeout=timeout,model=model,effort=effort,
            decision_dir=record_dir,max_output_bytes=16384)
        learning,details=validate_analysis(context,answer)
        result=store.assess(row['game'],context,learning,evaluations=answer['evaluations'],lesson_details=details)
        with store.db:store.db.execute('INSERT INTO analysis_usage(usage,result) VALUES(?,?)',
            (encoded(metadata.get('usage')),encoded(result)))
        publish(database)
        return {'status':'assessed',**result,'usage':metadata.get('usage')}
    finally:store.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--journal',type=Path)
    parser.add_argument('--players',default='')
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--collect-only',action='store_true')
    parser.add_argument('--publish-only',action='store_true')
    parser.add_argument('--stop-file',type=Path)
    parser.add_argument('--finish-file',type=Path)
    parser.add_argument('--idle-turns',type=int,default=2)
    parser.add_argument('--mine-turns',type=int,default=2)
    parser.add_argument('--scouting-turns',type=int,default=3)
    parser.add_argument('--max-calls',type=int,default=12)
    parser.add_argument('--max-tokens',type=int,default=200000)
    parser.add_argument('--timeout',type=float,default=60)
    parser.add_argument('--interval',type=float,default=5)
    parser.add_argument('--model',default=MODEL)
    parser.add_argument('--effort',default=REASONING_EFFORT)
    parser.add_argument('--records',type=Path)
    args=parser.parse_args()
    if args.max_calls<1 or args.max_tokens<1 or not 0<args.timeout<=120 or not 0<args.interval<=60:parser.error('invalid analysis limits')
    if any(not 1<=n<=30 for n in (args.idle_turns,args.mine_turns,args.scouting_turns)):parser.error('invalid review thresholds')
    if args.publish_only:
        if not args.database.exists():
            store=Experience(args.database,'learn');store.close()
        publish(args.database);return 0
    players={int(p) for p in args.players.split(',') if p}
    from evaluation import TelemetryCollector
    collector=TelemetryCollector(args.database,args.journal,players,idle_turns=args.idle_turns,
        mine_turns=args.mine_turns,scouting_turns=args.scouting_turns) if args.journal else None
    calls=tokens=0
    previous=None
    try:
        with analyst_lock(args.database):
            if args.collect_only:
                count=collector.poll() if collector else 0
                publish(args.database)
                print(json.dumps({'status':'collected','events':count}),flush=True)
                return 0
            while True:
                if args.stop_file and args.stop_file.exists():break
                if collector:collector.poll()
                record=None
                if args.records:
                    record=args.records/str(calls);record.mkdir(parents=True,exist_ok=True)
                try:
                    if calls>=args.max_calls or tokens>=args.max_tokens:
                        publish(args.database);result={'status':'budget_exhausted'}
                    else:
                        result=analyze_once(args.database,timeout=args.timeout,model=args.model,effort=args.effort,record_dir=record)
                        if result['status']=='assessed':
                            calls+=1;usage=result.get('usage') or {};tokens+=usage.get('input_tokens',args.max_tokens)+usage.get('output_tokens',0)
                except (OSError,ValueError,TypeError,KeyError,sqlite3.Error,TimeoutError,subprocess.SubprocessError) as error:
                    calls+=1;result={'status':'error','reason':str(error)}
                    # Unknown spent usage is charged conservatively.
                    tokens=args.max_tokens
                result={**result,'calls':calls,'charged_tokens':tokens}
                if result!=previous:print(json.dumps(result,ensure_ascii=False),flush=True)
                previous=result
                if args.once:return 1 if result['status']=='error' else 0
                if args.finish_file and args.finish_file.exists():break
                time.sleep(args.interval)
    except (OSError,ValueError) as error:
        print(json.dumps({'status':'unavailable','reason':str(error)}),file=sys.stderr);return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
