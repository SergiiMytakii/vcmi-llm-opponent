"""Record the one-shot ExternalAI protocol without putting diagnostics on stdout."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from .runs import load, now, verify, write_json


INPUT_LIMIT = 512 * 1024
OUTPUT_LIMIT = 8192
STDERR_LIMIT = 64 * 1024


def kill_controller(child, own_group=False):
    # Stay in the engine's process group/Windows Job: its cancellation owns this entire tree.
    # For an earlier wrapper timeout, kill its direct child; native exchange then
    # removes the inherited descendants when the wrapper exits.
    if own_group:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        # Native exchange owns the inherited group/Job and removes descendants when
        # this wrapper exits. ps is unavailable inside the actual macOS game sandbox.
        child.kill()
    child.wait(timeout=2)


def validate_reply(request, raw):
    reply = json.loads(raw)
    if request.get('protocol') == 2:
        from controller.native_strategy import validate_reply as validate_native
        return validate_native(request,reply,wire=True)
    fields = {"protocol", "request_id", "action_id"}
    if isinstance(reply, dict) and 'follow_up_action_ids' in reply:
        fields.add('follow_up_action_ids')
    if isinstance(reply, dict) and 'campaign' in reply and 'campaign' in request.get('memory', {}):
        from controller.strategy import validate_campaign
        validate_campaign(request, reply['campaign'], reply.get('strategy'))
        fields.add('campaign')
    if isinstance(reply, dict) and 'strategy' in reply and 'memory' in request:
        from controller.strategy import validate_strategy
        validate_strategy(request, reply['strategy'])
        fields.add('strategy')
    if (isinstance(reply, dict) and request.get('memory', {}).get('campaign')
            and reply.get('strategy') is not None and not reply.get('campaign')):
        from controller.strategy import validate_campaign
        validate_campaign(request, {'decision':'retain', 'reason':'Operational alignment',
                                   'evidence_refs':['observation:day'], 'plan':None}, reply['strategy'])
    if not isinstance(reply, dict) or set(reply) != fields:
        raise ValueError("invalid reply fields")
    if type(reply["protocol"]) is not int or reply["protocol"] != request["protocol"]:
        raise ValueError("unsupported reply protocol")
    if reply["request_id"] != request["request_id"]:
        raise ValueError("stale request_id")
    if not isinstance(reply["action_id"], str) or reply["action_id"] not in {a["id"] for a in request["actions"]}:
        raise ValueError("action_id was not offered")
    from controller.batch import validate_batch
    validate_batch(request, reply)
    return reply


def exchange(run, raw, engine_owned=False, postgame=False):
    run = Path(run).resolve()
    manifest = load(run)
    directory = run / "decisions" / uuid.uuid4().hex
    directory.mkdir(mode=0o700)
    started = time.monotonic()
    result = {"run_id": manifest["run_id"], "decision_id": directory.name, "started_at": now(), "status": "started",
              "execution": "unconfirmed"}
    write_json(directory / "result.json", result)
    (directory / "request.json").write_bytes(raw)
    child = None
    own_group = os.name != "nt" and (not engine_owned or postgame)
    output = b""
    if postgame:result['purpose']='postgame_reflection'
    try:
        verify(run)
        if len(raw) > INPUT_LIMIT:
            raise ValueError("request too large")
        request = json.loads(raw)
        if isinstance(request,dict) and request.get('protocol') == 2:
            from controller.native_strategy import validate_request as validate_native
            validate_native(request)
        elif (not isinstance(request, dict) or type(request.get("protocol")) is not int or request["protocol"] != 1
                or not isinstance(request.get("request_id"), str)
                or not isinstance(request.get("observation"), dict)
                or not isinstance(request.get("actions"), list) or not request["actions"]):
            raise ValueError("invalid protocol request")
        result.update(request_id=request["request_id"], observation=request["observation"],
                      protocol=request['protocol'], action_count=len(request.get("actions",[])))
        env = os.environ.copy()
        # Keep Codex authentication in its ordinary home; the native shim is for VCMI only.
        for key in ("DYLD_INSERT_LIBRARIES", "VCMI_PLAYTEST_PROFILE", "VCMI_PROBE_PROFILE"):
            env.pop(key, None)
        env["VCMI_PLAYTEST_DECISION_DIR"] = str(directory)
        experience = manifest.get('experience',{})
        baseline = experience.get('baseline')
        env['VCMI_EXPERIENCE_MODE'] = experience.get('mode','off') if engine_owned else 'read_only' if baseline else 'off'
        env['VCMI_EXPERIENCE_DB'] = experience.get('database','') if engine_owned else str(run / baseline['path']) if baseline else ''
        if env['VCMI_EXPERIENCE_MODE']=='read_only':
            env['VCMI_KNOWLEDGE_FILE']=str(Path(env['VCMI_EXPERIENCE_DB']).with_suffix('.knowledge.json'))
        else:env.pop('VCMI_KNOWLEDGE_FILE',None)
        for name, reference in manifest["references"].items():
            env["VCMI_PLAYTEST_" + name.upper()] = str(run / reference["path"])
        with (directory / "request.json").open("rb") as stdin, \
                (directory / "stdout.bin").open("wb") as stdout, \
                (directory / "stderr.log").open("wb") as stderr:
            child = subprocess.Popen(manifest["controller"], stdin=stdin, stdout=stdout, stderr=stderr,
                                     cwd=directory, env=env, start_new_session=own_group)
            deadline = started + manifest["decision_timeout_seconds"]
            while True:
                if (directory / "stdout.bin").stat().st_size > OUTPUT_LIMIT:
                    result["status"] = "output_limit"
                    break
                if (directory / "stderr.log").stat().st_size > STDERR_LIMIT:
                    result["status"] = "stderr_limit"
                    break
                if child.poll() is not None:
                    result["status"] = ("timeout" if child.returncode == 75 else
                                        "controller_exit" if child.returncode else "received")
                    break
                if postgame and (run / 'STOP').exists():
                    result['status']='requested_stop'
                    break
                if time.monotonic() >= deadline:
                    result["status"] = "timeout"
                    break
                time.sleep(0.02)
            if child.poll() is None:
                kill_controller(child, own_group)
            elif own_group:
                kill_controller(child, own_group)
            result["returncode"] = child.returncode
        for filename, limit in (("stdout.bin", OUTPUT_LIMIT), ("stderr.log", STDERR_LIMIT)):
            path = directory / filename
            with path.open("r+b") as stream:
                stream.truncate(min(path.stat().st_size, limit))
        if result["status"] == "received":
            output = (directory / "stdout.bin").read_bytes()
            try:
                reply = validate_reply(request, output)
                result.update(status="reply_valid", action_id=reply.get("action_id"))
                if request['protocol'] == 2:
                    plan = reply.get('plan') or request.get('campaign')
                    result.update(strategy_revision=plan['revision'], strategic_decision=reply['decision'], usage=reply['usage'])
            except (ValueError, KeyError, TypeError) as error:
                result.update(status="invalid_reply", error=str(error))
                output = b""
        # Optional controller-written diagnostics; kept separate from the engine reply.
        # These are declarations, not proof of internal reasoning or reference consumption.
        metadata = directory / "explanation.json"
        if metadata.is_file() and metadata.stat().st_size <= STDERR_LIMIT:
            result["explanation_file"] = "explanation.json"
    except (OSError, ValueError, KeyError, TypeError, InterruptedError) as error:
        result.update(status="recording_error", error=str(error))
        output = b""
    finally:
        if child is not None and child.poll() is None:
            kill_controller(child, own_group)
        result.update(finished_at=now(), duration_seconds=round(time.monotonic() - started, 6))
        write_json(directory / "result.json", result)
    return output, result


def replay(source_run, decision_id, target_run):
    source_run, target_run = Path(source_run).resolve(), Path(target_run).resolve()
    if Path(decision_id).name != decision_id or not decision_id:
        raise ValueError("invalid decision ID")
    source = source_run / "decisions" / decision_id / "request.json"
    if source_run == target_run or load(target_run)["status"] != "prepared":
        raise ValueError("replay requires a separate prepared target run")
    raw = source.read_bytes()
    output, result = exchange(target_run, raw)
    write_json(target_run / "decisions" / result["decision_id"] / "replay-source.json", {
        "run_id": load(source_run)["run_id"], "decision_id": decision_id,
        "kind": "decision-only; does not execute an engine command or restore controller memory",
    })
    return result


def main():
    os.umask(0o077)
    try:
        raw = sys.stdin.buffer.read(INPUT_LIMIT + 1)
        output, result = exchange(os.environ["VCMI_PLAYTEST_RUN"], raw, engine_owned=True)
        if result["status"] != "reply_valid":
            print("playtest controller: " + result["status"], file=sys.stderr)
            sys.exit(75 if result["status"] == "timeout" else 1)
        sys.stdout.buffer.write(output)
        sys.stdout.buffer.flush()
    except (OSError, ValueError, KeyError) as error:
        print(f"playtest controller: {error}", file=sys.stderr)
        sys.exit(1)
