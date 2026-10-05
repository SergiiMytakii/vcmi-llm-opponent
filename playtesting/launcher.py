"""Bounded macOS developer-game launch; never control an existing game session."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

from .reports import report, native_records
from .runs import COLORS, DATA, ROOT, now, snapshot, verify, write_json


DIFFICULTIES = {"easy": 0, "normal": 1, "hard": 2, "expert": 3, "impossible": 4}


def review_native_terminal(run, manifest):
    """Reuse the recorder/experience owner after all engine commands have stopped."""
    if manifest.get('nk3_mode')!='model' or manifest.get('experience',{}).get('mode')!='learn':return
    from .controller import exchange
    import re
    events, errors=native_records(run/'engine-logs/VCMI_Client_log.txt','NK3_TERMINAL')
    if errors:return  # An incomplete callback record is not terminal evidence.
    executions, execution_errors=native_records(run/'engine-logs/VCMI_Client_log.txt','NK3_EXECUTION')
    reviewed=set()
    for event in events:
        if (run/'STOP').exists():return
        if set(event)!={'experience_id','player','day','outcome'}:continue
        player,day,game=event['player'],event['day'],event['experience_id']
        if type(player) is not int or not 0<=player<len(COLORS) or type(day) is not int or day<1:continue
        if manifest['players'].get(COLORS[player])!='Nullkiller3' or event['outcome'] not in ('win','loss'):continue
        if not isinstance(game,str) or not re.fullmatch(r'[A-Za-z0-9-]{1,64}',game) or game in reviewed:continue
        reviewed.add(game)
        # Logger metadata binds records to this player game. Opaque hero aliases
        # and result sequences alone cannot distinguish two native opponents.
        own={}
        for result in executions:
            if (result.get('experience_id')!=game or type(result.get('player')) is not int
                    or result['player']!=player or type(result.get('day')) is not int
                    or not 1<=result['day']<=day or type(result.get('sequence')) is not int
                    or result['sequence']<1 or not isinstance(result.get('action'),dict)
                    or not isinstance(result.get('outcome'),str)):continue
            action=result['action']
            if action.get('kind')=='battle':
                if type(action.get('player')) is not int or action['player']!=player:continue
            elif any(not isinstance(action.get(state),dict) or type(action[state].get('player')) is not int
                     or action[state]['player']!=player for state in ('before','after')):continue
            own[result['sequence']]={key:result[key] for key in ('sequence','day','action','outcome')}
        recent=[];size=0
        for result in reversed(list(own.values())):
            cost=len(json.dumps(result,ensure_ascii=False).encode())
            if len(recent)>=8 or size+cost>12000:continue
            recent.append(result);size+=cost
        memory=dict(experience_id=game,execution_mechanism='native_campaign_v3',recent_results=list(reversed(recent)),
            execution_history=dict(observed=len(own),included=len(recent),
                                   omitted=len(own)-len(recent),malformed_records=execution_errors))
        request=dict(protocol=1,request_id=f'{player}:{day}:final',
            observation=dict(player=player,day=day,terminal_result=event['outcome']),
            memory=memory,actions=[dict(id='end',kind='end_turn')])
        # This response is an experience assessment. It never returns to a
        # gateway or changes a saved plan, and STOP cancels its process group.
        exchange(run,json.dumps(request).encode(),engine_owned=True,postgame=True)


def terminate_group(child, audit_path=None):
    # Native controllers have separate process groups but retain the session
    # created by start_new_session=True, even after a crash reparents them.
    # Freeze the game group so it cannot start another request during cleanup.
    errors = []
    def send(group, sig):
        try:
            os.killpg(group, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            # Check surviving members below rather than abandoning the other groups.
            errors.append({"group": group, "signal": int(sig)})
    send(child.pid, signal.SIGSTOP)
    groups = {child.pid}
    try:
        pids = map(int, subprocess.check_output(["ps", "-axo", "pid="], text=True).split())
        for pid in pids:
            try:
                if os.getsid(pid) == child.pid:
                    group = os.getpgid(pid)
                    if group > 1 and group != os.getpgrp():
                        groups.add(group)
            except ProcessLookupError:
                pass
    finally:
        for group in groups:
            send(group, signal.SIGTERM)
            send(group, signal.SIGCONT)
    try:
        child.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    # A server may outlive the client. Always clean the owned group, even after client exit.
    for group in groups:
        send(group, signal.SIGKILL)
    child.wait(timeout=2)
    # Zombies cannot execute work. A still-running owned group makes cleanup fail.
    remaining = [line.split() for line in subprocess.check_output(
        ["ps", "-axo", "pgid=,stat="], text=True).splitlines()]
    active = sorted({int(group) for group, state in remaining
                     if int(group) in groups and not state.startswith("Z")})
    audit = {"root_pid": child.pid, "groups": sorted(groups), "signal_errors": errors,
             "active_groups": active, "complete": not active}
    if audit_path:
        write_json(audit_path, audit)
    if active:
        raise RuntimeError(f"owned process groups survived cleanup: {active}")


def run_game(run):
    run = Path(run).resolve()
    manifest = verify(run, check_profile=True)
    if sys.platform != "darwin":
        raise ValueError("automatic game launch is verified only on macOS; offline recording/reporting is portable")
    engine = Path(manifest["engine"])
    if engine.name != "vcmiclient" or ".build" not in engine.parts:
        raise ValueError("use a separate developer vcmiclient under .build/, never the installed game")
    if manifest["difficulty"] not in DIFFICULTIES:
        raise ValueError("unsupported difficulty")
    if manifest.get("seed") is not None and (type(manifest["seed"]) is not int or manifest["seed"] < 0):
        raise ValueError("seed must be a nonnegative integer or null")
    if manifest["status"] != "prepared" or (run / "launch.lock").exists():
        raise ValueError("a run can be launched only once; prepare a fresh run")
    if any((run / "decisions").iterdir()):
        raise ValueError("run contains offline decisions; prepare a fresh run for a game")
    with (run / "launch.lock").open("x"):
        pass
    started = time.monotonic()
    protected = [Path.home() / "Library/Application Support/vcmi", Path.home() / "Library/Logs/vcmi"]
    before = [snapshot(path) for path in protected]
    write_json(run / "protected-before.json", before)
    child = None
    result = {"started_at": now(), "reason": "setup_failed", "returncode": None}
    try:
        sandbox = run / "profile.sb"
        sandbox.write_text("(version 1)\n(allow default)\n" + "".join(
            f"(deny file-write* (subpath {json.dumps(str(path))}))\n" for path in protected), encoding="utf-8")
        env = os.environ.copy()
        env.pop('DYLD_INSERT_LIBRARIES', None)
        env.pop('VCMI_NK3_MODE', None)
        if "nk3_mode" in manifest:
            env['VCMI_NK3_MODE'] = manifest['nk3_mode']
        profile = run / 'profile' / DATA
        env.update(VCMI_PROFILE_DIR=str(profile),
                   VCMI_PLAYTEST_RUN=str(run), VCMI_EXTERNAL_AI_EXECUTABLE=sys.executable,
                   VCMI_EXTERNAL_AI_SCRIPT=str(ROOT / "scripts/playtest_controller.py"))
        settings_path = run / "profile" / DATA / "config/settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings.setdefault("general", {}).update(lastDifficulty=DIFFICULTIES[manifest["difficulty"]], saveFrequency=1)
        if manifest.get("seed") is not None:
            settings.setdefault("server", {})["seed"] = manifest["seed"]
        names = set(manifest["players"].values())
        if len(names) == 1:
            ai = next(iter(names))
            settings.setdefault("ai", {}).update(adventureAlliedAI=ai, adventureEnemyAI=ai)
        write_json(settings_path, settings)
        prefix = ["/usr/bin/sandbox-exec", "-f", str(sandbox), str(engine)]
        help_result = subprocess.run(prefix + ["--help"], env=env, capture_output=True, timeout=10)
        (run / "preflight.stdout.log").write_bytes(help_result.stdout)
        (run / "preflight.stderr.log").write_bytes(help_result.stderr)
        # --help does not initialize directories. Refuse an older/stock executable
        # before --version or game startup can touch its default profile.
        if help_result.returncode != 0 or b'VCMI_PROFILE_DIR' not in help_result.stdout:
            raise ValueError('engine lacks native profile isolation; rebuild before launching')
        version = subprocess.run(prefix + ['--version'], env=env, capture_output=True, timeout=10)
        (run / 'preflight.stdout.log').write_bytes(help_result.stdout + version.stdout)
        (run / 'preflight.stderr.log').write_bytes(help_result.stderr + version.stderr)
        paths = dict(line.strip().split(':', 1) for line in version.stdout.decode('utf-8').splitlines()
                     if line.strip().startswith('user ') and ':' in line)
        expected = {'user data': profile, 'user cache': profile / 'cache', 'user config': profile / 'config',
                    'user logs': profile / 'logs', 'user saves': profile / 'Saves',
                    'user extracted': profile / 'cache/extracted'}
        if version.returncode or any(paths.get(key, '').strip() != str(value) for key, value in expected.items()):
            raise ValueError('engine writable paths do not match the isolated profile')
        with socket.socket() as port_socket:
            port_socket.bind(("127.0.0.1", 0))
            port = port_socket.getsockname()[1]
        logs = run / "engine-logs"
        logs.mkdir()
        scenario = (["--testsave", manifest["save_resource"]] if manifest.get("save_resource")
                    else ["--testmap", manifest["map_resource"]])
        args = ["--nointro", "--disable-video", "--onlyAI", *scenario,
                "--savefrequency", "1", "--serverport", str(port), "--logLocation", str(logs)]
        args += ["--headless"] if manifest.get("headless", False) else ["--spectate", "--spectate-skip-battle", "--spectate-skip-battle-result"]
        if len(names) > 1:
            if b"--ai" not in help_result.stdout:
                raise ValueError("this engine lacks per-player --ai selection")
            for color in COLORS:
                if color in manifest["players"]:
                    args += ["--ai", manifest["players"][color]]
        command = prefix + args
        write_json(run / "command.json", command)
        manifest["status"] = "running"
        write_json(run / "manifest.json", manifest)
        with (run / "runtime.log").open("wb") as log:
            child = subprocess.Popen(command, cwd=engine.parent, env=env, stdout=log,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            result.update(pid=child.pid, reason="deadline")
            write_json(run / "launch.json", result)
            deadline = time.monotonic() + manifest["max_seconds"]
            log_offset, partial, assignments = 0, b"", {}
            while time.monotonic() < deadline:
                if (run / "STOP").exists():
                    result["reason"] = "requested_stop"
                    break
                if child.poll() is not None:
                    result["reason"] = "process_exit"
                    break
                logfile = logs / "VCMI_Client_log.txt"
                if logfile.is_file():
                    import re
                    with logfile.open("rb") as stream:
                        stream.seek(log_offset)
                        chunk = stream.read(256 * 1024)
                        log_offset = stream.tell()
                    lines = (partial + chunk).split(b"\n")
                    partial = lines.pop()[-4096:]
                    for line in lines:
                        assignments.update(re.findall(r"Player (\w+) will be lead by (\w+)", line.decode("utf-8", errors="replace")))
                    if assignments and any(manifest["players"].get(c) != ai for c, ai in assignments.items()):
                        result["reason"] = "assignment_mismatch"
                        break
                time.sleep(0.2)
    except KeyboardInterrupt:
        result["reason"] = "interrupted"
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result.update(reason="setup_failed", error=str(error))
    finally:
        if child is not None:
            try:
                terminate_group(child, run / "cleanup.json")
                result["cleanup_complete"] = True
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                result.update(reason="cleanup_failed", error=str(error), cleanup_complete=False)
            result["returncode"] = child.returncode
        after = [snapshot(path) for path in protected]
        result.update(finished_at=now(), elapsed_seconds=round(time.monotonic() - started, 3),
                      protected_files_unchanged=before == after)
        write_json(run / "launch.json", result)
        manifest["status"] = "finished"
        write_json(run / "manifest.json", manifest)
        if (result.get('cleanup_complete') and result.get('protected_files_unchanged')
                and result['reason'] not in ('requested_stop','interrupted','assignment_mismatch','setup_failed')):
            review_native_terminal(run,manifest)
        report(run)
    return result
