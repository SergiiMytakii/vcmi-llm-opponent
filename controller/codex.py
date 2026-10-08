"""Subscription-only, one-shot Codex decision transport for CLI 0.160.0."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from strategy import strategy_schema, validate_strategy, campaign_schema, validate_campaign
from batch import validate_batch
from prompt_context import (compact_json, encode_request, context_parts, bounded_history, without_unknown_army_values,
                            SHARED_CONTEXT_INSTRUCTIONS, HISTORY_INSTRUCTIONS, SOFT_INPUT_BYTES)


ROOT = Path(__file__).resolve().parent
MODEL = 'gpt-5.6-terra'
REASONING_EFFORT = 'none'
VERSION = 'codex-cli 0.160.0'
TIMEOUT = 120  # NK3: recorder 130s, native exchange 140s.
LEGACY_TIMEOUT = 60  # Deprecated protocol 1 retains its native 70s boundary.
LIMIT = 1024 * 1024
DISABLED = '''shell_tool unified_exec shell_snapshot apps plugins remote_plugin memories
multi_agent multi_agent_v2 goals browser_use browser_use_external computer_use image_generation
view_image skill_search skill_mcp_dependency_install hooks tool_suggest sleep_tool
workspace_dependencies code_mode code_mode_host code_mode_only unbounded_connection_retries
realtime_conversation deferred_executor send_message_to_user_async request_permissions_tool
token_budget current_time_reminder deferred_tool_world_state standalone_web_search'''.split()


def validate_request(request):
    if isinstance(request,dict) and request.get('protocol') == 2:
        from native_strategy import validate_request as validate_native
        return validate_native(request)
    if not isinstance(request, dict) or type(request.get('protocol')) is not int or request['protocol'] != 1:
        raise ValueError('unsupported protocol')
    if not isinstance(request.get('request_id'), str) or not request['request_id']:
        raise ValueError('missing request_id')
    if not isinstance(request.get('observation'), dict):
        raise ValueError('missing observation')
    actions = request.get('actions')
    if not isinstance(actions, list) or not actions:
        raise ValueError('missing actions')
    ids = []
    for action in actions:
        if not isinstance(action, dict) or not isinstance(action.get('id'), str) or not action['id']:
            raise ValueError('invalid action id')
        if not isinstance(action.get('kind'), str):
            raise ValueError('missing action kind')
        ids.append(action['id'])
    if len(ids) != len(set(ids)) or not any(a['kind'] == 'end_turn' for a in actions):
        raise ValueError('ambiguous actions or missing end_turn')


def validate_reply(request, reply):
    if request['protocol'] == 2:
        from native_strategy import validate_reply as validate_native
        return validate_native(request,reply)
    fields = {'protocol', 'request_id', 'action_id'}
    if isinstance(reply, dict) and 'follow_up_action_ids' in reply:
        fields.add('follow_up_action_ids')
    if isinstance(reply, dict) and 'strategy' in reply and 'memory' in request:
        fields.add('strategy')
    if isinstance(reply, dict) and 'campaign' in reply and 'campaign' in request.get('memory', {}):
        fields.add('campaign')
    if not isinstance(reply, dict) or set(reply) != fields:
        raise ValueError('invalid reply shape')
    if type(reply['protocol']) is not int or reply['protocol'] != 1:
        raise ValueError('invalid reply protocol')
    if reply['request_id'] != request['request_id']:
        raise ValueError('stale request_id')
    if not isinstance(reply['action_id'], str) or reply['action_id'] not in {a['id'] for a in request['actions']}:
        raise ValueError('action was not offered')
    validate_batch(request, reply)
    if 'strategy' in reply:
        validate_strategy(request, reply['strategy'])
    if 'campaign' in reply:
        validate_campaign(request, reply['campaign'], reply.get('strategy'))
    if request.get('memory', {}).get('campaign') and reply.get('strategy') is not None and not reply.get('campaign'):
        validate_campaign(request, {'decision':'retain', 'reason':'Operational alignment',
                                   'evidence_refs':['observation:day'], 'plan':None}, reply['strategy'])
    wire_reply = reply
    if len((compact_json(wire_reply) + '\n').encode('utf-8')) > 8192:
        raise ValueError('reply exceeds native transport limit')
    return reply


def resolve_executable(value=None):
    """Select a native Windows CLI, never execute its npm shell wrapper."""
    executable = value or os.environ.get('VCMI_CODEX_EXECUTABLE')
    if not executable:
        executable = (shutil.which('codex.exe') if os.name == 'nt' else None) or shutil.which('codex')
    if not executable:
        raise ValueError('Codex CLI is not installed')
    path = Path(shutil.which(str(executable)) or executable).expanduser().resolve()
    if path.suffix.lower() in ('.cmd', '.bat', '.ps1'):
        # npm puts the wrapper beside node_modules. Its optional platform
        # package may be nested under codex or hoisted beside it. These paths
        # follow the installed CLI's bin/codex.js, for our Windows x64 target.
        package = path.parent / 'node_modules/@openai/codex'
        vendor_roots = [package / 'node_modules/@openai/codex-win32-x64/vendor',
                        path.parent / 'node_modules/@openai/codex-win32-x64/vendor',
                        package / 'vendor']
        if path.stem.lower() == 'codex':
            for vendor in vendor_roots:
                native = vendor / 'x86_64-pc-windows-msvc/bin/codex.exe'
                if native.is_file():
                    return str(native.resolve())
        raise ValueError('native Codex binary missing; set VCMI_CODEX_EXECUTABLE to codex.exe')
    if os.name == 'nt' and path.suffix.lower() != '.exe':
        raise ValueError('native Windows Codex binary required; select codex.exe')
    if not path.is_file():
        raise ValueError('Codex executable does not exist')
    return str(path)


def choose(request):
    started = time.monotonic()
    validate_request(request)
    instructions=(ROOT/('native_instructions.txt' if request['protocol']==2 else 'instructions.txt')).read_text(encoding='utf-8')
    references={}
    path=os.environ.get('VCMI_PLAYTEST_PROMPT')
    if path:
        raw=Path(path).read_bytes()
        if len(raw)>32768:raise ValueError('strategy reference is too large')
        instructions+='\n\nPROMPT\n'+raw.decode('utf-8')
        references['prompt']=hashlib.sha256(raw).hexdigest()
    if request['protocol'] == 2:
        from native_strategy import reply_schema
        schema = reply_schema(request)
    else:
        schema = {'type': 'object', 'additionalProperties': False,
                  'required': ['protocol', 'request_id', 'action_id'], 'properties': {
                      'protocol': {'type': 'integer', 'enum': [1]},
                      'request_id': {'type': 'string', 'enum': [request['request_id']]},
                      'action_id': {'type': 'string', 'enum': [a['id'] for a in request['actions']]}}}
        if 'memory' in request:
            schema['required'].append('strategy')
            schema['properties']['strategy'] = strategy_schema(request)
        if 'campaign' in request.get('memory', {}):
            schema['required'].append('campaign')
            schema['properties']['campaign'] = campaign_schema(request)
        limit = request['observation'].get('batch_action_limit', 1)
        if type(limit) is not int or not 1 <= limit <= 32:
            raise ValueError('invalid batch action limit')
        if limit > 1:
            schema['required'].append('follow_up_action_ids')
            schema['properties']['follow_up_action_ids'] = {
                'type': 'array', 'maxItems': limit - 1,
                'items': {'type': 'string', 'enum': [a['id'] for a in request['actions']]}}

    from knowledge import snapshot_for_request, KNOWLEDGE_INSTRUCTIONS
    knowledge=snapshot_for_request(request)
    if knowledge is not None:instructions+='\n'+KNOWLEDGE_INSTRUCTIONS
    timeout=min(TIMEOUT,request['budget']['wait_ms']/1000-2) if request['protocol']==2 else LEGACY_TIMEOUT
    deadline = started + timeout
    decision_dir = os.environ.get('VCMI_PLAYTEST_DECISION_DIR')
    if request['protocol'] == 1:
        answer,metadata=invoke_model(request,schema,instructions,timeout=timeout,
            knowledge=knowledge,decision_dir=decision_dir)
        try:answer=validate_reply(request,answer)
        except ValueError as error:
            error.usage=metadata.get('usage');raise
        metadata['references']=references
        return answer,metadata

    from strategy_guide import StrategyGuide, DEFAULT_ROOT
    mode = os.environ.get('VCMI_STRATEGY_GUIDE_MODE','on')
    if mode not in ('on','off'):raise ValueError('invalid strategy guide mode')
    guide = StrategyGuide(os.environ.get('VCMI_STRATEGY_GUIDE',str(DEFAULT_ROOT))) if mode=='on' else None
    guide_info = {'mode':mode,'requested_ids':[],'returned_files':[]}
    if guide:
        guide_info.update(bundle_sha256=guide.bundle_hash,catalog=guide.catalog,file_hashes=guide.hashes)
        instructions += guide.instructions()
    from game_rules import GameRules, DEFAULT_ROOT as RULES_ROOT
    rules_mode = os.environ.get('VCMI_GAME_RULES_MODE','on')
    if rules_mode not in ('on','off'):raise ValueError('invalid game rules mode')
    game_rules = GameRules(os.environ.get('VCMI_GAME_RULES',str(RULES_ROOT))) if rules_mode=='on' else None
    rules_info = {'mode':rules_mode,'requested_ids':[],'returned_files':[]}
    if game_rules:
        rules_info.update(bundle_sha256=game_rules.bundle_hash,catalog=game_rules.catalog,file_hashes=game_rules.hashes)
        instructions += game_rules.instructions()
    folder = Path(decision_dir) / 'model-call-1' if decision_dir else None
    if folder:folder.mkdir()
    metadata={}
    try:
        answer,metadata=invoke_model(request,schema,instructions,timeout=timeout,deadline=deadline,
            knowledge=knowledge,guide=guide,guide_info=guide_info,game_rules=game_rules,rules_info=rules_info,
            decision_dir=folder,max_output_bytes=32768)
        answer=validate_reply(request,answer)
    except BaseException as error:
        if not hasattr(error,'usage'):error.usage=metadata.get('usage')
        error.diagnostics={'strategy_guide':guide_info,'game_rules':rules_info,'references':references}
        raise
    metadata.update(references=references,strategy_guide=guide_info,game_rules=rules_info,
        model_calls=[{'number':1,'status':'completed','usage':metadata.get('usage')}])
    return answer,metadata


def _compact_response_schema(schema):
    """Share large string enums in an expanded native schema, without changing its language."""
    def normalize(value):
        if isinstance(value, list):return [normalize(item) for item in value]
        if not isinstance(value, dict):return value
        result = {key:normalize(item) for key,item in value.items()}
        values = result.get('enum')
        if result.get('type') == 'string' and values and all(isinstance(v, str) for v in values):
            if 'minLength' in result and all(len(v) >= result['minLength'] for v in values):
                del result['minLength']
            if 'maxLength' in result and all(len(v) <= result['maxLength'] for v in values):
                del result['maxLength']
        return result

    normalized = normalize(schema)
    counts = Counter()
    nodes = {}
    def enum_key(value):
        if value.get('type') == 'string' and 'enum' in value:
            key = compact_json(value)
            if len(key.encode('utf-8')) >= 256:return key
        return None
    def collect(value):
        if isinstance(value, dict):
            key = enum_key(value)
            if key is not None:counts[key] += 1;nodes[key] = value
            for item in value.values():collect(item)
        elif isinstance(value, list):
            for item in value:collect(item)
    collect(normalized)
    names = {key:'allowed_'+str(i) for i,key in enumerate(key for key in counts if counts[key] > 1)}
    def share(value):
        if isinstance(value, dict):
            key = enum_key(value)
            if key in names:return {'$ref':'#/$defs/'+names[key]}
            return {key:share(item) for key,item in value.items()}
        if isinstance(value, list):return [share(item) for item in value]
        return value
    result = share(normalized)
    if names:result['$defs'] = {name:nodes[key] for key,name in names.items()}
    return result


def invoke_model(request,schema,instructions,*,timeout=TIMEOUT,model=MODEL,effort=REASONING_EFFORT,knowledge=None,guide=None,guide_info=None,game_rules=None,rules_info=None,decision_dir=None,max_output_bytes=8192,deadline=None):
    """Return a validated reply and diagnostics; failures belong to caller fallback."""
    started = time.monotonic()
    deadline = min(started + timeout, deadline) if deadline is not None else started + timeout
    if timeout <= 0:raise TimeoutError('No model wait budget remains')
    executable = resolve_executable()
    env = os.environ.copy()
    for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL', 'DYLD_INSERT_LIBRARIES',
                'VCMI_PLAYTEST_PROFILE', 'VCMI_PROBE_PROFILE'):
        env.pop(key, None)
    version = subprocess.run([executable, '--version'], capture_output=True, env=env, timeout=min(2,max(0.001,deadline-time.monotonic())))
    if version.returncode or version.stdout.decode('utf-8').strip() != VERSION:
        raise ValueError('unsupported Codex CLI version; requires 0.160.0')
    with tempfile.TemporaryDirectory(prefix='vcmi-decision-') as folder:
        workspace = Path(folder)
        projected, history = bounded_history(without_unknown_army_values(request) if request.get('protocol') == 2 else request)
        model_request = encode_request(projected)
        if request.get('protocol') == 2 and len(compact_json(model_request).encode('utf-8')) > SOFT_INPUT_BYTES:
            raise ValueError('context_overflow: complete strategic facts exceed the input budget')
        shared_context = model_request is not projected
        model_input = compact_json(model_request)
        encoding = {'format':('shared-json-v3' if 'field_defaults' in model_request else 'shared-json-v2' if 'fields' in model_request else 'shared-json-v1') if shared_context else 'json',
                    'original_bytes':len(json.dumps(request).encode('utf-8')),
                    'sent_bytes':len(model_input.encode('utf-8')),
                    'shared_values':len(model_request['shared']) if shared_context else 0,
                    'field_sets':len(model_request.get('fields', [])) if shared_context else 0,
                    'parts':context_parts(projected), 'original_parts':context_parts(request),
                    'history':history, 'soft_input_budget_bytes':SOFT_INPUT_BYTES,
                    'over_soft_input_budget':len(model_input.encode('utf-8')) > SOFT_INPUT_BYTES}
        references = {}
        if shared_context:instructions += '\n' + SHARED_CONTEXT_INSTRUCTIONS
        if history['applied']:instructions += '\n' + HISTORY_INSTRUCTIONS
        (workspace / 'instructions.txt').write_text(instructions, encoding='utf-8')
        original_schema_bytes = len(compact_json(schema).encode('utf-8'))
        # Only the model copy uses references; local validation retains reply_schema().
        model_schema = _compact_response_schema(schema) if request.get('protocol') == 2 else schema
        (workspace / 'schema.json').write_text(compact_json(model_schema), encoding='utf-8')
        encoding['instruction_bytes'] = len(instructions.encode('utf-8'))
        encoding['original_reply_schema_bytes'] = original_schema_bytes
        encoding['reply_schema_bytes'] = len(compact_json(model_schema).encode('utf-8'))
        if decision_dir:
            (Path(decision_dir) / 'codex-instructions.txt').write_text(instructions,encoding='utf-8')
            (Path(decision_dir) / 'input-encoding.json').write_text(compact_json(encoding), encoding='utf-8')
        config = {
            'model_provider': 'openai', 'forced_login_method': 'chatgpt',
            'model_reasoning_effort': effort, 'model_catalog_json': str(ROOT / 'model.json'),
            'model_instructions_file': str(workspace / 'instructions.txt'),
            'web_search': 'disabled', 'project_doc_max_bytes': 0, 'skills.include_instructions': False,
            'tools.update_plan.enabled': False, 'tools.experimental_request_user_input.enabled': False,
            'include_environment_context': False, 'include_apps_instructions': False,
            'history.persistence': 'none', 'analytics.enabled': False,
            'suppress_unstable_features_warning': True,
            'features.skip_host_skill_discovery': True,
        }
        config.update({'features.' + name: False for name in DISABLED})
        if knowledge is not None:
            snapshot=workspace/'knowledge.json'
            snapshot.write_text(compact_json(knowledge),encoding='utf-8')
            config.update({'mcp_servers.nk3_knowledge.command':os.sys.executable,
                'mcp_servers.nk3_knowledge.args':[str(ROOT/'knowledge_server.py'),str(snapshot)],
                'mcp_servers.nk3_knowledge.enabled_tools':['search_knowledge','read_lesson'],
                'mcp_servers.nk3_knowledge.startup_timeout_sec':2,
                'mcp_servers.nk3_knowledge.tool_timeout_sec':2,
                'mcp_servers.nk3_knowledge.default_tools_approval_mode':'approve'})
        reference_tools = [('strategy_guide',guide,guide_info),('game_rules',game_rules,rules_info)]
        for kind,bundle,_ in reference_tools:
            if bundle is None:continue
            key='mcp_servers.nk3_'+kind+'.'
            config.update({key+'command':os.sys.executable,
                key+'args':[str(ROOT/'strategy_guide_server.py'),str(bundle.root),str(workspace/(kind+'-calls.jsonl')),bundle.bundle_hash,kind],
                key+'enabled_tools':['read_'+kind],key+'startup_timeout_sec':2,
                key+'tool_timeout_sec':2,key+'default_tools_approval_mode':'approve'})
        command = [executable, 'exec', '--ignore-user-config', '--ignore-rules', '--ephemeral',
                   '--skip-git-repo-check', '--json', '--color', 'never', '-s', 'read-only',
                   '-m', model, '-C', folder, '--output-schema', str(workspace / 'schema.json'),
                   '-o', str(workspace / 'answer.json')]
        for key, value in config.items():
            command += ['-c', key + '=' + json.dumps(value)]
        command += ['-']
        (workspace / 'request.json').write_text(model_input, encoding='utf-8')
        timing = {'preparation_seconds':round(time.monotonic()-started,3), 'events':[]}
        model_started = time.monotonic()
        event_offset = 0
        def observe_events():
            nonlocal event_offset
            with (workspace / 'events.jsonl').open('rb') as events:
                events.seek(event_offset)
                for line in events:
                    if not line.endswith(b'\n'):break
                    event_offset += len(line)
                    event = json.loads(line)
                    timing['events'].append({'type':event.get('type'),
                        'seconds':round(time.monotonic()-model_started,3)})
        with (workspace / 'request.json').open('rb') as stdin, \
                (workspace / 'events.jsonl').open('wb') as stdout, \
                (workspace / 'stderr.log').open('wb') as stderr:
            # Inherit the native transport's process group/Windows Job. Never detach
            # a model process from game cancellation or recorder cleanup.
            child = subprocess.Popen(command, stdin=stdin, stdout=stdout, stderr=stderr, env=env, cwd=folder)
            try:
                while child.poll() is None:
                    # CLI milestones, not a server queue/first-token trace.
                    observe_events()
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Codex decision deadline exceeded')
                    if stdout.tell() > LIMIT or stderr.tell() > LIMIT:
                        raise ValueError('Codex output limit exceeded')
                    time.sleep(.02)
                if child.returncode:
                    raise ValueError('Codex failed with exit code ' + str(child.returncode))
            except BaseException as error:
                error.usage = _event_usage(workspace / 'events.jsonl')
                raise
            finally:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=1)
                observe_events()
                timing['model_process_seconds'] = round(time.monotonic()-model_started,3)
                timing['process_returncode'] = child.returncode
                for kind,_,info in reference_tools:
                    audit=workspace/(kind+'-calls.jsonl')
                    if not audit.exists():continue
                    audits=[json.loads(line) for line in audit.read_text().splitlines()]
                    if info is not None:
                        info['calls']=audits
                        info['requested_ids']=list(dict.fromkeys(i for c in audits for i in c['ids']))
                        info['returned_files']=[f for c in audits for f in c['files']]
                    if decision_dir:
                        (Path(decision_dir)/(kind.replace('_','-')+'-calls.jsonl')).write_bytes(audit.read_bytes())
                if decision_dir:
                    (Path(decision_dir) / 'codex-timing.json').write_text(compact_json(timing),encoding='utf-8')
                    (Path(decision_dir) / 'codex-request.json').write_text(model_input, encoding='utf-8')
                    (Path(decision_dir) / 'codex-schema.json').write_text(compact_json(model_schema), encoding='utf-8')
                    if (workspace / 'answer.json').is_file():
                        with (workspace / 'answer.json').open('rb') as answer_stream:
                            (Path(decision_dir) / 'codex-answer.json').write_bytes(answer_stream.read(LIMIT))
                    for name in ('events.jsonl', 'stderr.log'):
                        with (workspace / name).open('rb') as stream:
                            (Path(decision_dir) / ('codex-' + name)).write_bytes(stream.read(LIMIT))
        try:
            if time.monotonic() >= deadline:
                raise TimeoutError('Codex decision deadline exceeded')
            events_path = workspace / 'events.jsonl'
            answer_path = workspace / 'answer.json'
            if events_path.stat().st_size > LIMIT or answer_path.stat().st_size > max_output_bytes:
                raise ValueError('Codex output limit exceeded')
            completed, usage = False, None
            for line in events_path.read_text(encoding='utf-8').splitlines():
                event = json.loads(line)
                if event.get('type') in ('turn.failed', 'error'):
                    raise ValueError('Codex turn failed')
                item = event.get('item')
                if item and item.get('type') not in ('agent_message','reasoning'):
                    allowed = (knowledge is not None and item.get('server')=='nk3_knowledge'
                               and item.get('tool') in ('search_knowledge','read_lesson')) or (
                               any(bundle is not None and item.get('server')=='nk3_'+kind
                                   and item.get('tool')=='read_'+kind for kind,bundle,_ in reference_tools))
                    if not (item.get('type')=='mcp_tool_call' and allowed):
                        raise ValueError('unexpected Codex item: ' + str(item.get('type')))
                if event.get('type') == 'turn.completed':
                    completed, usage = True, event.get('usage')
            if time.monotonic() >= deadline:
                raise TimeoutError('Codex decision deadline exceeded')
            if not completed:
                raise ValueError('Codex turn did not complete')
            reply=json.loads(answer_path.read_text(encoding='utf-8'))
            return reply, {'provider': 'codex', 'model': model, 'reasoning_effort': effort,
                           'cli': VERSION, 'usage': usage, 'references': references,
                           'input_encoding': encoding,
                           'duration_seconds': round(time.monotonic() - started, 3)}
        except BaseException as error:
            error.usage = _event_usage(workspace / 'events.jsonl')
            raise


def _event_usage(path):
    """Retain completed reported usage even when answer validation/process handling fails."""
    usage = None
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            try:event = json.loads(line)
            except ValueError:continue
            if isinstance(event,dict) and event.get('type') == 'turn.completed':usage = event.get('usage')
    except (OSError,UnicodeError):pass
    return usage
