"""Read-only Strategy Guide MCP for one frozen, prepared bundle."""
import json
from pathlib import Path
import sys
from strategy_guide import StrategyGuide


def serve(root, audit, expected_hash):
    guide=StrategyGuide(root)
    if guide.bundle_hash!=expected_hash:raise ValueError('strategy guide changed before tool startup')
    tool={'name':'read_strategy_guide','description':'Read 1-3 relevant strategy sections from the provided catalog. Advice only; continue planning with current game facts.',
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
                'capabilities':{'tools':{}},'serverInfo':{'name':'nk3_strategy_guide','version':'1'}}
            elif method=='tools/list':result={'tools':[tool]}
            elif method=='ping':result={}
            elif method=='tools/call':
                params=message['params'];args=params.get('arguments',{})
                if params['name']!='read_strategy_guide' or not isinstance(args,dict) or set(args)!={'ids'}:
                    raise ValueError('invalid strategy guide tool request')
                content,files=guide.consult(args['ids'])
                with Path(audit).open('a',encoding='utf-8') as stream:
                    stream.write(json.dumps({'ids':args['ids'],'files':files,'result_bytes':len(content.encode('utf-8'))})+'\n')
                result={'content':[{'type':'text','text':content}]}
            else:raise ValueError('unsupported MCP method')
            response={'jsonrpc':'2.0','id':message['id'],'result':result}
        except (ValueError,KeyError,TypeError,OSError) as error:
            response={'jsonrpc':'2.0','id':message['id'],'error':{'code':-32602,'message':str(error)}}
        print(json.dumps(response,ensure_ascii=False),flush=True)


if __name__=='__main__':serve(sys.argv[1],sys.argv[2],sys.argv[3])
