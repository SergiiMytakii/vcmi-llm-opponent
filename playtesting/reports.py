"""Evidence-based reports: a proposed action is not a completed game command."""
from collections import Counter
import json
from pathlib import Path
import re
import statistics
import uuid

from .runs import digest, load, now, write_json


def read_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def native_records(path, marker):
    """Read bounded multiline JSON from the pinned AI logger, preserving gaps."""
    records, errors, buffer = [], 0, ''
    start=re.compile(r'^\[[^]]+\]\s+INFO\s+\[[^]]+\]\s+ai - '+re.escape(marker)+r' (\{.*)$')
    decoder=json.JSONDecoder()
    if not path.is_file():return records, errors
    with path.open(encoding='utf-8',errors='replace') as stream:
        for line in stream:
            match=start.match(line)
            if match:
                if buffer:errors+=1
                buffer=match[1]
            elif buffer:
                if line.startswith('['):
                    errors+=1;buffer='';continue
                buffer+=line
            else:continue
            if len(buffer)>1024*1024:
                errors+=1;buffer='';continue
            try:
                value, unused=decoder.raw_decode(buffer)
            except ValueError:continue
            if isinstance(value,dict):records.append(value)
            else:errors+=1
            buffer=''
    return records, errors+bool(buffer)


def report(run):
    run = Path(run).resolve()
    manifest = load(run)
    decisions = []
    for directory in sorted((run / "decisions").iterdir()):
        if directory.is_dir():
            record = read_json(directory / "result.json", {"status": "incomplete"})
            record = {**record, "decision_id": directory.name, "execution": "unconfirmed"}
            if record["status"] == "started":
                record["status"] = "incomplete"
            try:
                request = read_json(directory / "request.json", {})
            except (ValueError, UnicodeError):
                request = {}
                record["request_error"] = "invalid request.json; raw input preserved"
            if isinstance(request, dict):
                record["action"] = next((a for a in request.get("actions", [])
                                         if isinstance(a, dict) and a.get("id") == record.get("action_id")), None)
                record['campaign_review'] = request.get('memory', {}).get('campaign_review')
                record['observed_memory'] = {key:request.get('memory', {}).get(key)
                    for key in ('campaign','recent_results','own_force_changes')}
            reply_path = directory / 'stdout.bin'
            if record['status'] == 'reply_valid' and reply_path.is_file() and reply_path.stat().st_size <= 8192:
                try:
                    reply = json.loads(reply_path.read_bytes())
                    if isinstance(reply, dict) and reply.get('campaign') is not None:
                        record['campaign'] = reply['campaign']
                        record['campaign_source'] = 'controller declaration; acceptance requires later memory'
                except (ValueError, UnicodeError):
                    pass
            explanation = directory / "explanation.json"
            if explanation.is_file() and explanation.stat().st_size <= 64 * 1024:
                try:
                    metadata = read_json(explanation, {})
                    if isinstance(metadata, dict):
                        for key in ('experience','experience_error','provider','usage','input_encoding'):
                            if key in metadata:
                                record[key] = metadata[key]
                    if isinstance(metadata, dict) and isinstance(metadata.get("explanation"), str):
                        record["explanation"] = metadata["explanation"]
                        record["explanation_source"] = "controller declaration"
                except (ValueError, UnicodeError):
                    record["explanation_error"] = "invalid explanation.json; raw file preserved"
            decisions.append(record)
    decisions.sort(key=lambda r: r.get("started_at", r["decision_id"]))
    counts = dict(Counter(d["status"] for d in decisions))
    ids = Counter(d.get("request_id") for d in decisions)
    logfile = run / "engine-logs/VCMI_Client_log.txt"
    native_execution, execution_errors=native_records(logfile,'NK3_EXECUTION')
    native_strategy, strategy_errors=native_records(logfile,'NK3_STRATEGY')
    native_battles=[r for r in native_execution if isinstance(r.get('action'),dict) and r['action'].get('kind')=='battle'
                    and r.get('action',{}).get('source')=='own_battle_result'
                    and r.get('outcome') in ('battle_won','battle_lost','battle_draw')]
    native_requests=[r for r in native_strategy if r.get('requested') is True]
    native_waits=[r['elapsed_ms'] for r in native_requests if type(r.get('elapsed_ms')) is int and r['elapsed_ms']>=0]
    native_wait_p95=(statistics.quantiles(native_waits,n=100,method='inclusive')[94]
                     if len(native_waits)>1 else native_waits[0] if native_waits else None)
    assignments, selected = {}, {}
    execution_ids = Counter()
    batch_steps = []
    results = {}
    unattributed = 0
    if logfile.is_file():
        with logfile.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                assignments.update(re.findall(r"Player (\w+) will be lead by (\w+)", line))
                selections = re.findall(r"ExternalAI request (\S+) selected (\S+)", line)
                selected.update(selections)
                execution_ids.update(request_id for request_id, unused in selections)
                for request_id, action_id, source in re.findall(r"ExternalAI batch step request=(\S+) action=(\S+) source=(\S+)", line):
                    batch_steps.append({'request_id':request_id, 'action_id':action_id,
                                        'chosen_in_request':source, 'execution':'engine_selected'})
                matches = re.findall(r"ExternalAI build result[^\n]*observed=([01]) request=(\S+) action=(\S+)", line)
                for observed, request_id, action_id in matches:
                    results[(request_id, action_id)] = "build_observed" if observed == "1" else "build_not_observed"
                for kind, observed, request_id, action_id in re.findall(
                        r"ExternalAI (move|recruit|transfer|upgrade|hire hero) result[^\n]*observed=([01]) request=(\S+) action=(\S+)", line):
                    label = kind.replace(' ', '_')
                    results[(request_id, action_id)] = label + ('_progress_observed' if kind == 'move' and observed == '1'
                                                              else '_observed' if observed == '1' else '_not_observed')
                if not matches and re.search(r"ExternalAI build result[^\n]*observed=[01]", line):
                    unattributed += 1
    for decision in decisions:
        request_id, action_id = decision.get("request_id"), decision.get("action_id")
        if request_id and ids[request_id] == 1 and execution_ids[request_id] <= 1:
            if (request_id, action_id) in results:
                decision["execution"] = results[(request_id, action_id)]
            elif selected.get(request_id) == action_id and action_id is not None:
                decision["execution"] = "engine_selected"
            if decision["status"] != "reply_valid" and selected.get(request_id) == "end":
                decision["execution"] = "engine_selected_fallback_end"
        decision['batch_steps'] = [step for step in batch_steps if step['chosen_in_request'] == request_id]
    for step in batch_steps:
        # Repeated model IDs after load remain ambiguous, including their queue.
        if ids[step['chosen_in_request']] == 1 and execution_ids[step['request_id']] == 1:
            step['execution'] = results.get((step['request_id'],step['action_id']), 'engine_selected')
        else:
            step['execution'] = 'unconfirmed'
    timings = sorted(d["duration_seconds"] for d in decisions if "duration_seconds" in d)
    episodes = [read_json(path, {}) for path in sorted((run / "episodes").glob("*.json"))]
    outcome = read_json(run / "outcome.json", {})
    usage = Counter()
    providers = Counter()
    changes, reinforcements, main_losses = [], [], []
    seen_results, seen_losses = set(), set()
    for decision in decisions:
        providers[decision.get('provider', 'unknown')] += 1
        for key, count in (decision.get('usage') or {}).items():
            if type(count) is int and count >= 0: usage[key] += count
        assessment = decision.get('campaign')
        if isinstance(assessment, dict):
            changes.append({'request_id':decision.get('request_id'), 'decision':assessment.get('decision'),
                            'reason':assessment.get('reason'), 'evidence_refs':assessment.get('evidence_refs')})
        memory = decision.get('observed_memory', {})
        main = (memory.get('campaign') or {}).get('main_hero_ref')
        player = str(decision.get('request_id','')).split(':')[0]
        for result in memory.get('recent_results') or []:
            identity = (player, result.get('sequence'))
            action = result.get('action', {})
            if (identity not in seen_results and result.get('outcome') == 'completed'
                    and action.get('kind') in ('recruit','transfer','upgrade')
                    and main == 'object:' + str(action.get('destination'))):
                reinforcements.append({'day':result.get('day'), 'kind':action['kind'],
                                       'amount':action.get('amount'), 'main_hero_ref':main})
                seen_results.add(identity)
        for loss in memory.get('own_force_changes') or []:
            identity = (player, loss.get('day'), loss.get('hero'))
            if identity not in seen_losses and main == 'object:' + str(loss.get('hero')):
                main_losses.append(loss)
                seen_losses.add(identity)
        decision.pop('observed_memory', None)
    value = {
        "run_id": manifest["run_id"], "case_id": manifest["case_id"], "purpose": manifest["purpose"],
        "generated_at": now(), "match_outcome": outcome.get("outcome", "unconfirmed"),
        "outcome_source": "manual evidence" if outcome else "none",
        "launch": read_json(run / "launch.json", {"reason": "not_launched"}),
        "assignment_matches": assignments == manifest["players"] if assignments else None,
        "observed_assignments": assignments, "expected_assignments": manifest["players"],
        "counts": counts, "decision_count": len(decisions), "decisions": decisions,
        "batch_steps":batch_steps,
        "native_execution":native_execution,
        "native_strategy":native_strategy,
        "native_metrics":{
            "execution_outcomes":dict(Counter(r.get('outcome','unknown') for r in native_execution)),
            "battle_outcomes":dict(Counter(r['outcome'] for r in native_battles)),
            "own_battle_loss_value":sum(r['action']['army_loss_value'] for r in native_battles
                if type(r['action'].get('army_loss_value')) is int and r['action']['army_loss_value']>=0),
            "requests_by_player_day":dict(Counter(str(r.get('player'))+':'+str(r.get('day')) for r in native_requests)),
            "accepted_responses":sum(r.get('accepted') is True for r in native_requests),
            "fallback_reasons":dict(Counter(r.get('fallback_reason','unknown') for r in native_requests if r.get('accepted') is False)),
            "charged_tokens":sum(r['charged_tokens'] for r in native_requests if type(r.get('charged_tokens')) is int),
            "wait_ms_median":statistics.median(native_waits) if native_waits else None,
            "wait_ms_p95":native_wait_p95,
            "record_errors":execution_errors+strategy_errors,
            "limits":"Task records contain observed net own-state changes; battle records contain acknowledged own casualties and battle outcomes. A battle victory is not a match victory. A reconciled unknown result is not a confirmed command; effects do not prove full task completion or gross purchase cost. Request metrics cover finished/cancelled logger records; charged tokens may include conservative reservations for unknown usage."},
        "model_metrics": {'providers':dict(providers), 'usage':dict(usage),
                          'timeouts':counts.get('timeout',0), 'fallbacks':providers.get('fallback',0)},
        "campaign_metrics": {'assessments':changes, 'confirmed_reinforcements':reinforcements,
                             'main_hero_losses':main_losses,
                             'limits':'Assessments are declarations. Missing later observations cannot prove delivery, loss, idle time or route waste.'},
        "latency_seconds": {"median": statistics.median(timings) if timings else None,
                            "max": max(timings) if timings else None},
        "unattributed_build_results": unattributed,
        "episodes": episodes, "references": manifest["references"],
        "experience":manifest.get('experience',{}),
        "randomness": "uncontrolled" if manifest.get("seed") is None else "declared; engine application unconfirmed",
    }
    write_json(run / "report.json", value)
    lines = [f"# Playtest {manifest['case_id']}", "", f"Run: `{manifest['run_id']}`",
             f"Outcome: **{value['match_outcome']}** ({value['outcome_source']})",
             f"Launch: `{value['launch']['reason']}`; assignment matches: `{value['assignment_matches']}`",
             f"Decisions: {len(decisions)}; batch steps: {len(batch_steps)}; statuses: `{json.dumps(counts)}`",
             f"Model: `{value['model_metrics']}`",
             f"Native consequences: {len(native_execution)}; outcomes: `{value['native_metrics']['execution_outcomes']}`; incomplete records: {value['native_metrics']['record_errors']}",
             f"Latency: `{value['latency_seconds']}`; randomness: {value['randomness']}", "",
             "Selection, confirmed execution, and match outcome are separate evidence.", "",
             "| Decision | Request | Reply | Execution | Seconds | Explanation (controller declaration) |",
             "| --- | --- | --- | --- | --- | --- |"]
    for d in decisions:
        cells = [d["decision_id"], d.get("request_id", "?"), d.get("action_id", d["status"]),
                 d["execution"], d.get("duration_seconds", "?"), d.get("explanation", "unavailable")[:512]]
        lines.append("| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in cells) + " |")
    lines += ["", f"Episodes: {len(episodes)}; see `episodes/`. Raw exchanges: `decisions/`.",
              "Repeated request IDs (e.g. load) are left unconfirmed rather than joined ambiguously.",
              "Native net resource changes and owned-state snapshots are in `report.json`. Unknown recovery is not command confirmation.",
              ""]
    (run / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return value


def attach(run, evidence):
    run = Path(run).resolve()
    source = Path(evidence).resolve()
    name = uuid.uuid4().hex + source.suffix
    destination = run / "evidence" / name
    import shutil
    shutil.copyfile(source, destination)
    return {"path": str(destination.relative_to(run)), "sha256": digest(destination)}


def episode(run, decision_id, category, text, evidence=None):
    run = Path(run).resolve()
    if not decision_id or Path(decision_id).name != decision_id or not (run / "decisions" / decision_id).is_dir():
        raise ValueError("unknown decision ID")
    if not text.strip():
        raise ValueError("episode text is required")
    value = {"created_at": now(), "decision_id": decision_id, "category": category, "text": text,
             "evidence": attach(run, evidence) if evidence else None}
    identifier = uuid.uuid4().hex
    write_json(run / "episodes" / (identifier + ".json"), value)
    return {"episode_id": identifier}


def outcome(run, result, evidence):
    run = Path(run).resolve()
    if (run / "outcome.json").exists():
        raise ValueError("outcome already recorded; preserve the original evidence")
    value = {"created_at": now(), "outcome": result, "evidence": attach(run, evidence),
             "source": "manual review"}
    write_json(run / "outcome.json", value)
    return value


def compare(runs):
    manifests = [load(Path(run)) for run in runs]
    keys = ("case_id", "purpose", "map_sha256", "save_resource", "save_sha256", "players", "seed", "difficulty", "profile_sha256", "model", "reasoning_effort", "experience_mode")
    implementation = ("engine_sha256", "engine_sources", "controller_sources", "references")
    implementation_changes = [key for key in implementation if any(m.get(key) != manifests[0].get(key) for m in manifests[1:])]
    mismatches = [key for key in keys if any(m.get(key) != manifests[0].get(key) for m in manifests[1:])]
    experiences = [(m.get("experience") or {}) for m in manifests]
    modes = [e.get("mode", m.get("experience_mode", "learn")) for e, m in zip(experiences, manifests)]
    snapshots = [(e.get("baseline") or {}).get("sha256") for e in experiences]
    if any(mode != modes[0] for mode in modes[1:]): mismatches.append("resolved_experience_mode")
    if modes[0] == "read_only" and any(s != snapshots[0] for s in snapshots[1:]):
        mismatches.append("experience_snapshot_sha256")
    frozen_experience = all(mode in ("off", "read_only") for mode in modes)
    reports = [report(run) for run in runs]
    return {"same_start_conditions": not mismatches, "different_fields": mismatches,
            "implementation_different_fields":implementation_changes,
            "comparable_for_strategy": not mismatches and frozen_experience and all(r["assignment_matches"] is True
                and r["match_outcome"] in ("llm_win", "llm_loss", "draw") for r in reports),
            "randomness_controlled": False,
            "warning": "Repeated games are required; a declared seed is not proof that VCMI used it.",
            "runs": [{"run_id": r["run_id"], "outcome": r["match_outcome"], "counts": r["counts"],
                      "latency_seconds": r["latency_seconds"], "model_metrics":r["model_metrics"],
                      "campaign_metrics":r["campaign_metrics"], "assignment_matches": r["assignment_matches"],
                      "references": r["references"]} for r in reports]}
