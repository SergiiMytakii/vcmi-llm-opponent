"""ExternalAI stdin/stdout entrypoint. Diagnostics never share the reply channel."""
import json
import os
from pathlib import Path
import sys
import time
import subprocess
import sqlite3
import uuid

from codex import choose, validate_request, MODEL, REASONING_EFFORT, TIMEOUT, LEGACY_TIMEOUT
from experience import Experience


def main():
    raw = sys.stdin.buffer.read(512 * 1024 + 1)
    if len(raw) > 512 * 1024:
        raise ValueError('request too large')
    request = json.loads(raw.decode('utf-8'))
    validate_request(request)
    request.pop('experience', None)  # Raw learning context never enters strategy.
    # The playtest recorder supplies its own immutable decision directory.
    # Direct launches retain the same model-call artifacts under their profile.
    decision_dir = os.environ.get('VCMI_PLAYTEST_DECISION_DIR')
    if not decision_dir:
        profile = os.environ.get('VCMI_PROFILE_DIR')
        root = Path(profile) / 'logs' if profile else Path(__file__).resolve().parents[1] / '.build' / 'logs'
        directory = root / 'decisions' / uuid.uuid4().hex
        directory.mkdir(parents=True, mode=0o700)
        decision_dir = str(directory)
        os.environ['VCMI_PLAYTEST_DECISION_DIR'] = decision_dir
    (Path(decision_dir) / 'request.json').write_bytes(raw)
    started = time.monotonic()
    experience = None
    experience_error = None
    try:
        experience = Experience.for_request(request)
        if experience:
            experience.observe(request)
    except (OSError, ValueError, TypeError, sqlite3.Error) as error:
        experience_error = str(error)
        if experience:
            experience.close()
        experience = None
    try:
        reply, metadata = choose(request)
    except (TimeoutError, subprocess.TimeoutExpired) as error:
        reply = None
        metadata = {'provider': 'fallback', 'reason': str(error), 'retryable': request['protocol'] == 1,
                    'duration_seconds': round(time.monotonic() - started, 3)}
        metadata.update(getattr(error,'diagnostics',{}))
        if getattr(error,'usage',None) is not None:metadata['usage']=error.usage
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        if request['protocol'] == 2:
            reply = None
        else:
            action = next(a for a in request['actions'] if a['kind'] == 'end_turn')
            reply = {'protocol': 1, 'request_id': request['request_id'], 'action_id': action['id']}
        metadata = {'provider': 'fallback', 'reason': str(error),
                    'duration_seconds': round(time.monotonic() - started, 3)}
        metadata.update(getattr(error,'diagnostics',{}))
        if request['protocol'] == 2:
            metadata['failure_kind'] = 'invalid_reply' if isinstance(error,(ValueError,TypeError)) else 'controller_error'
            if getattr(error,'usage',None) is not None:metadata['usage'] = error.usage
    if experience:
        try:
            if reply is not None:
                if metadata['provider']=='fallback':experience.record_fallback(request,reply)
                else:experience.record_decision(request,reply)
            metadata['experience']={'collection_only':True,'episodes_assessed':0,'lessons_updated':0,'lessons_supplied':0}
        except (OSError, ValueError, TypeError, sqlite3.Error) as error:
            experience_error = str(error)
        finally:
            experience.close()
    if experience_error:
        metadata['experience_error'] = experience_error
    metadata['requested_model'] = MODEL
    metadata['requested_reasoning_effort'] = REASONING_EFFORT
    metadata['decision_timeout_seconds'] = (min(TIMEOUT, request['budget']['wait_ms']/1000 - 2)
                                            if request['protocol'] == 2 else LEGACY_TIMEOUT)
    metadata['request_bytes'] = len(raw)
    metadata.update(request_id=request['request_id'], action_id=reply.get('action_id') if reply else None)
    print(json.dumps(metadata), file=sys.stderr)
    decision_dir = os.environ.get('VCMI_PLAYTEST_DECISION_DIR')
    if decision_dir:
        (Path(decision_dir) / 'explanation.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    if reply is None:
        # EX_TEMPFAIL reaches the engine through the recorder. No game command
        # or learning episode is fabricated for an unanswered model request.
        raise SystemExit(1 if request['protocol']==2 and metadata.get('failure_kind') else 75)
    if request['protocol'] == 2:
        usage = metadata.get('usage')
        known = metadata.get('usage_complete',True) and isinstance(usage,dict) and all(type(usage.get(k)) is int and usage[k]>=0 for k in ('input_tokens','output_tokens'))
        reply['usage'] = {k:usage[k] if known else 0 for k in ('input_tokens','output_tokens')}
        reply['usage']['known'] = known
    (Path(decision_dir) / 'reply.json').write_text(json.dumps(reply, ensure_ascii=False), encoding='utf-8')
    sys.stdout.buffer.write((json.dumps(reply, ensure_ascii=False, separators=(',', ':')) + "\n").encode('utf-8'))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
