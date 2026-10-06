"""Private native turn-review receipts and explicit continuation."""
import json
from pathlib import Path

from .runs import DATA, digest, load, now, write_json


def sync_review(run):
    """Publish a pause only after the native save has completed and been hashed."""
    run = Path(run)
    source = run / 'turn-review/native-state.json'
    if not source.exists():
        return None
    state = json.loads(source.read_text())
    if state['status'] == 'paused':
        resource = Path(state['save_resource'])
        if resource.is_absolute() or '..' in resource.parts or resource.parts[0] != 'Saves':
            raise ValueError('native review checkpoint is outside Saves')
        save = run / 'profile' / DATA / resource
        if not save.is_file() or not save.stat().st_size:
            raise ValueError('native review checkpoint is missing or empty')
        state.update(save_sha256=digest(save), save_size=save.stat().st_size)
        receipt = run / 'turn-review' / f"checkpoint-{state['completed_day']}.json"
        if not receipt.exists():
            write_json(receipt, {**state, 'recorded_at': now(), 'run_id': load(run)['run_id']})
    target = run / 'turn-review/state.json'
    if not target.exists() or json.loads(target.read_text()) != state:
        write_json(target, state)
    return state


def continue_review(run, completed_day):
    run = Path(run).resolve()
    manifest = load(run)
    if manifest['status'] != 'running' or not manifest.get('review_interval_days'):
        raise ValueError('run is not running in turn-review mode')
    state = sync_review(run)
    if not state or state['status'] != 'paused':
        raise ValueError('run has no completed checkpoint awaiting review')
    if state['completed_day'] != completed_day:
        raise ValueError('completed day does not match the paused checkpoint')
    (run / 'turn-review' / f"continue-{state['next_day']}").touch(exist_ok=False)
    return {'status': 'continue_requested', 'completed_day': completed_day}
