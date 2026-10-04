"""ExternalAI stdin/stdout entrypoint. Diagnostics never share the reply channel."""
import json
import os
from pathlib import Path
import sys
import time
import subprocess
import sqlite3

from codex import choose, validate_request
from experience import Experience


def main():
    raw = sys.stdin.buffer.read(512 * 1024 + 1)
    if len(raw) > 512 * 1024:
        raise ValueError('request too large')
    request = json.loads(raw.decode('utf-8'))
    validate_request(request)
    request.pop('experience', None)  # Only the controller's library supplies experience.
    started = time.monotonic()
    experience = None
    experience_error = None
    try:
        experience = Experience.for_request(request)
        if experience:
            request['experience'] = experience.prepare(request)
    except (OSError, ValueError, TypeError, sqlite3.Error) as error:
        experience_error = str(error)
        if experience:
            experience.close()
        experience = None
    try:
        reply, metadata = choose(request)
    except (TimeoutError, subprocess.TimeoutExpired) as error:
        reply = None
        metadata = {'provider': 'fallback', 'reason': str(error), 'retryable': True,
                    'duration_seconds': round(time.monotonic() - started, 3)}
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        action = next(a for a in request['actions'] if a['kind'] == 'end_turn')
        reply = {'protocol': 1, 'request_id': request['request_id'], 'action_id': action['id']}
        metadata = {'provider': 'fallback', 'reason': str(error),
                    'duration_seconds': round(time.monotonic() - started, 3)}
    if experience:
        try:
            if reply is not None and 'learning' in reply:
                metadata['experience'] = experience.accept(request, reply)
            else:
                if reply is not None and metadata['provider'] == 'fallback':
                    experience.record_fallback(request, reply)
                metadata['experience'] = {'lessons_supplied':len(request['experience']['lessons'])}
        except (OSError, ValueError, TypeError, sqlite3.Error) as error:
            experience_error = str(error)
        finally:
            experience.close()
    if reply is not None:
        reply.pop('learning', None)
    if experience_error:
        metadata['experience_error'] = experience_error
    metadata['request_bytes'] = len(raw)
    metadata.update(request_id=request['request_id'], action_id=reply['action_id'] if reply else None)
    print(json.dumps(metadata), file=sys.stderr)
    decision_dir = os.environ.get('VCMI_PLAYTEST_DECISION_DIR')
    if decision_dir:
        (Path(decision_dir) / 'explanation.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    if reply is None:
        # EX_TEMPFAIL reaches the engine through the recorder. No game command
        # or learning episode is fabricated for an unanswered model request.
        raise SystemExit(75)
    sys.stdout.buffer.write((json.dumps(reply, ensure_ascii=False) + "\n").encode('utf-8'))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
