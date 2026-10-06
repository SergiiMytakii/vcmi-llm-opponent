"""Read-only MCP serving one frozen strategy or mechanics reference bundle."""
import json
from pathlib import Path
import sys
from strategy_guide import StrategyGuide


def serve(root, audit, expected_hash, kind='strategy_guide'):
    if kind == 'game_rules':
        from game_rules import GameRules
        guide=GameRules(root)
        description='Read 1-3 game mechanics cards. Explains how rules work, not which strategy to choose. Current scenario/mod facts and executor limits take precedence.'
    elif kind == 'strategy_guide':
        guide=StrategyGuide(root)
        description='Read 1-3 relevant strategy sections from the provided catalog. Advice only; continue planning with current game facts.'
    else:raise ValueError('unknown reference kind')
    if guide.bundle_hash!=expected_hash:raise ValueError(f'{guide.label} changed before tool startup')
    tool_name='read_'+kind
    tool={'name':tool_name,'description':description,
        'inputSchema':{'type':'object','properties':{'ids':{'type':'array','minItems':1,'maxItems':3,
            'items':{'type':'string','enum':[c['id'] for c in guide.catalog]}}},'required':['ids'],'additionalProperties':False},
        'annotations':{'readOnlyHint':True}}
    for line in sys.stdin:
        if len(line)>16384:raise ValueError('oversized MCP message')
        message=json.loads(line)
        if 'id' not in message:continue
        try:
            method=message.get('method')
            if method=='initialize':result={'protocolVersion':message['params']['protocolVersion'],
                'capabilities':{'tools':{}},'serverInfo':{'name':'nk3_'+kind,'version':'1'}}
            elif method=='tools/list':result={'tools':[tool]}
            elif method=='ping':result={}
            elif method=='tools/call':
                params=message['params'];args=params.get('arguments',{})
                if params['name']!=tool_name or not isinstance(args,dict) or set(args)!={'ids'}:
                    raise ValueError(f'invalid {guide.label} tool request')
                content,files=guide.consult(args['ids'])
                with Path(audit).open('a',encoding='utf-8') as stream:
                    stream.write(json.dumps({'ids':args['ids'],'files':files,'result_bytes':len(content.encode('utf-8'))})+'\n')
                result={'content':[{'type':'text','text':content}]}
            else:raise ValueError('unsupported MCP method')
            response={'jsonrpc':'2.0','id':message['id'],'result':result}
        except (ValueError,KeyError,TypeError,OSError) as error:
            response={'jsonrpc':'2.0','id':message['id'],'error':{'code':-32602,'message':str(error)}}
        print(json.dumps(response,ensure_ascii=False),flush=True)


if __name__=='__main__':serve(*sys.argv[1:])
