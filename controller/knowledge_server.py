"""Local STDIO MCP, with exactly two read-only tools and a frozen knowledge file."""
import json
from pathlib import Path
import sys

from knowledge import KnowledgeReader


def serve(path):
    raw=Path(path).read_bytes()
    if len(raw)>512*1024:raise ValueError('knowledge snapshot too large')
    reader=KnowledgeReader(json.loads(raw))
    tools=[{'name':'search_knowledge','description':'Find a few portable NK3 lessons for a strategic uncertainty. Read-only.',
        'inputSchema':{'type':'object','properties':{'query':{'type':'string','maxLength':200},
            'category':{'type':['string','null'],'enum':[None,'combat','defense','economy','reinforcement','exploration','tempo']}},
            'required':['query'],'additionalProperties':False},'annotations':{'readOnlyHint':True}},
        {'name':'read_lesson','description':'Read one lesson returned by knowledge search, including conditions and confidence. Read-only.',
        'inputSchema':{'type':'object','properties':{'id':{'type':'string'}},'required':['id'],'additionalProperties':False},
        'annotations':{'readOnlyHint':True}}]
    for line in sys.stdin:
        if len(line)>16384:raise ValueError('oversized MCP message')
        message=json.loads(line)
        if 'id' not in message:continue
        ident=message['id'];method=message.get('method')
        try:
            if method=='initialize':result={'protocolVersion':message['params']['protocolVersion'],
                'capabilities':{'tools':{}},'serverInfo':{'name':'nk3_knowledge','version':'1'}}
            elif method=='tools/list':result={'tools':tools}
            elif method=='tools/call':
                params=message['params'];value=reader.call(params['name'],params.get('arguments',{}))
                result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}]}
            elif method=='ping':result={}
            else:raise ValueError('unsupported MCP method')
            response={'jsonrpc':'2.0','id':ident,'result':result}
        except (ValueError,KeyError,TypeError) as error:
            response={'jsonrpc':'2.0','id':ident,'error':{'code':-32602,'message':str(error)}}
        print(json.dumps(response,ensure_ascii=False),flush=True)


if __name__=='__main__':serve(sys.argv[1])
