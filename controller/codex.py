"""Subscription-only, one-shot Codex decision transport for CLI 0.160.0."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from strategy import strategy_schema, validate_strategy
from experience import learning_schema, validate_learning
from batch import validate_batch


ROOT = Path(__file__).resolve().parent
MODEL = 'gpt-6.1-sol'
VERSION = 'codex-cli 0.160.0'
TIMEOUT = 35  # Leaves room for the recorder (37s) and native exchange (40s).
LIMIT = 1024 * 1024
DISABLED = '''shell_tool unified_exec shell_snapshot apps plugins remote_plugin memories
multi_agent multi_agent_v2 goals browser_use browser_use_external computer_use image_generation
view_image skill_search skill_mcp_dependency_install hooks tool_suggest sleep_tool
workspace_dependencies code_mode code_mode_host code_mode_only unbounded_connection_retries
realtime_conversation deferred_executor send_message_to_user_async request_permissions_tool
token_budget current_time_reminder deferred_tool_world_state standalone_web_search'''.split()


def validate_request(request):
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
    fields = {'protocol', 'request_id', 'action_id'}
    if isinstance(reply, dict) and 'follow_up_action_ids' in reply:
        fields.add('follow_up_action_ids')
    if request.get('experience', {}).get('mode') == 'learn':
        fields.add('learning')
    if isinstance(reply, dict) and 'strategy' in reply and 'memory' in request:
        fields.add('strategy')
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
    if 'learning' in reply:
        validate_learning(request['experience'], reply['learning'])
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
    """Return a validated reply and diagnostics; failures belong to caller fallback."""
    validate_request(request)
    started = time.monotonic()
    executable = resolve_executable()
    env = os.environ.copy()
    for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL', 'DYLD_INSERT_LIBRARIES',
                'VCMI_PLAYTEST_PROFILE', 'VCMI_PROBE_PROFILE'):
        env.pop(key, None)
    version = subprocess.run([executable, '--version'], capture_output=True, env=env, timeout=2)
    if version.returncode or version.stdout.decode('utf-8').strip() != VERSION:
        raise ValueError('unsupported Codex CLI version; requires 0.160.0')
    with tempfile.TemporaryDirectory(prefix='vcmi-decision-') as folder:
        workspace = Path(folder)
        instructions = (ROOT / 'instructions.txt').read_text(encoding='utf-8')
        references = {}
        for name in ('PROMPT', 'KNOWLEDGE'):
            path = os.environ.get('VCMI_PLAYTEST_' + name)
            if path:
                raw = Path(path).read_bytes()
                if len(raw) > 32768:
                    raise ValueError('strategy reference is too large')
                instructions += '\n\n' + name + '\n' + raw.decode('utf-8')
                references[name.lower()] = hashlib.sha256(raw).hexdigest()
        (workspace / 'instructions.txt').write_text(instructions, encoding='utf-8')
        schema = {'type': 'object', 'additionalProperties': False,
                  'required': ['protocol', 'request_id', 'action_id'], 'properties': {
                      'protocol': {'type': 'integer', 'enum': [1]},
                      'request_id': {'type': 'string', 'enum': [request['request_id']]},
                      'action_id': {'type': 'string', 'enum': [a['id'] for a in request['actions']]}}}
        if 'memory' in request:
            schema['required'].append('strategy')
            schema['properties']['strategy'] = strategy_schema(request)
        limit = request['observation'].get('batch_action_limit', 1)
        if type(limit) is not int or not 1 <= limit <= 32:
            raise ValueError('invalid batch action limit')
        if limit > 1:
            schema['required'].append('follow_up_action_ids')
            schema['properties']['follow_up_action_ids'] = {
                'type': 'array', 'maxItems': limit - 1,
                'items': {'type': 'string', 'enum': [a['id'] for a in request['actions']]}}
        if request.get('experience', {}).get('mode') == 'learn':
            schema['required'].append('learning')
            schema['properties']['learning'] = learning_schema(request['experience'])
        (workspace / 'schema.json').write_text(json.dumps(schema), encoding='utf-8')
        config = {
            'model_provider': 'openai', 'forced_login_method': 'chatgpt',
            'model_reasoning_effort': 'medium', 'model_catalog_json': str(ROOT / 'model.json'),
            'model_instructions_file': str(workspace / 'instructions.txt'),
            'web_search': 'disabled', 'project_doc_max_bytes': 0, 'skills.include_instructions': False,
            'tools.update_plan.enabled': False, 'tools.experimental_request_user_input.enabled': False,
            'include_environment_context': False, 'include_apps_instructions': False,
            'history.persistence': 'none', 'analytics.enabled': False,
            'suppress_unstable_features_warning': True,
            'features.skip_host_skill_discovery': True,
        }
        config.update({'features.' + name: False for name in DISABLED})
        command = [executable, 'exec', '--ignore-user-config', '--ignore-rules', '--ephemeral',
                   '--skip-git-repo-check', '--json', '--color', 'never', '-s', 'read-only',
                   '-m', MODEL, '-C', folder, '--output-schema', str(workspace / 'schema.json'),
                   '-o', str(workspace / 'answer.json')]
        for key, value in config.items():
            command += ['-c', key + '=' + json.dumps(value)]
        command += ['-']
        (workspace / 'request.json').write_text(json.dumps(request), encoding='utf-8')
        with (workspace / 'request.json').open('rb') as stdin, \
                (workspace / 'events.jsonl').open('wb') as stdout, \
                (workspace / 'stderr.log').open('wb') as stderr:
            # Inherit the native transport's process group/Windows Job. Never detach
            # a model process from game cancellation or recorder cleanup.
            child = subprocess.Popen(command, stdin=stdin, stdout=stdout, stderr=stderr, env=env, cwd=folder)
            try:
                while child.poll() is None:
                    if time.monotonic() - started >= TIMEOUT:
                        raise TimeoutError('Codex decision deadline exceeded')
                    if stdout.tell() > LIMIT or stderr.tell() > LIMIT:
                        raise ValueError('Codex output limit exceeded')
                    time.sleep(.02)
                if child.returncode:
                    raise ValueError('Codex failed with exit code ' + str(child.returncode))
            finally:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=1)
                decision_dir = os.environ.get('VCMI_PLAYTEST_DECISION_DIR')
                if decision_dir:
                    for name in ('events.jsonl', 'stderr.log'):
                        with (workspace / name).open('rb') as stream:
                            (Path(decision_dir) / ('codex-' + name)).write_bytes(stream.read(LIMIT))
        events_path = workspace / 'events.jsonl'
        answer_path = workspace / 'answer.json'
        if events_path.stat().st_size > LIMIT or answer_path.stat().st_size > 8192:
            raise ValueError('Codex output limit exceeded')
        completed, usage = False, None
        for line in events_path.read_text(encoding='utf-8').splitlines():
            event = json.loads(line)
            if event.get('type') in ('turn.failed', 'error'):
                raise ValueError('Codex turn failed')
            item = event.get('item')
            if item and item.get('type') not in ('agent_message', 'reasoning'):
                raise ValueError('unexpected Codex item: ' + str(item.get('type')))
            if event.get('type') == 'turn.completed':
                completed, usage = True, event.get('usage')
        if not completed or time.monotonic() - started >= TIMEOUT:
            raise ValueError('Codex turn did not complete before deadline')
        reply = validate_reply(request, json.loads(answer_path.read_text(encoding='utf-8')))
        return reply, {'provider': 'codex', 'model': MODEL, 'reasoning_effort': 'medium',
                       'cli': VERSION, 'usage': usage, 'references': references,
                       'duration_seconds': round(time.monotonic() - started, 3)}
