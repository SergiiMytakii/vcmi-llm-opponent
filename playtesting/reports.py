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
            explanation = directory / "explanation.json"
            if explanation.is_file() and explanation.stat().st_size <= 64 * 1024:
                try:
                    metadata = read_json(explanation, {})
                    if isinstance(metadata, dict):
                        for key in ('experience','experience_error'):
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
    assignments, selected = {}, {}
    results = {}
    unattributed = 0
    if logfile.is_file():
        with logfile.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                assignments.update(re.findall(r"Player (\w+) will be lead by (\w+)", line))
                selected.update(re.findall(r"ExternalAI request (\S+) selected (\S+)", line))
                matches = re.findall(r"ExternalAI build result[^\n]*observed=([01]) request=(\S+) action=(\S+)", line)
                for observed, request_id, action_id in matches:
                    results[(request_id, action_id)] = "build_observed" if observed == "1" else "build_not_observed"
                if not matches and re.search(r"ExternalAI build result[^\n]*observed=[01]", line):
                    unattributed += 1
    for decision in decisions:
        request_id, action_id = decision.get("request_id"), decision.get("action_id")
        if request_id and ids[request_id] == 1:
            if (request_id, action_id) in results:
                decision["execution"] = results[(request_id, action_id)]
            elif selected.get(request_id) == action_id and action_id is not None:
                decision["execution"] = "engine_selected"
            if decision["status"] != "reply_valid" and selected.get(request_id) == "end":
                decision["execution"] = "engine_selected_fallback_end"
    timings = sorted(d["duration_seconds"] for d in decisions if "duration_seconds" in d)
    episodes = [read_json(path, {}) for path in sorted((run / "episodes").glob("*.json"))]
    outcome = read_json(run / "outcome.json", {})
    value = {
        "run_id": manifest["run_id"], "case_id": manifest["case_id"], "purpose": manifest["purpose"],
        "generated_at": now(), "match_outcome": outcome.get("outcome", "unconfirmed"),
        "outcome_source": "manual evidence" if outcome else "none",
        "launch": read_json(run / "launch.json", {"reason": "not_launched"}),
        "assignment_matches": assignments == manifest["players"] if assignments else None,
        "observed_assignments": assignments, "expected_assignments": manifest["players"],
        "counts": counts, "decision_count": len(decisions), "decisions": decisions,
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
             f"Decisions: {len(decisions)}; statuses: `{json.dumps(counts)}`",
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
    keys = ("case_id", "purpose", "engine_sha256", "engine_sources", "map_sha256", "save_resource", "save_sha256", "players", "seed", "difficulty", "profile_sha256")
    mismatches = [key for key in keys if any(m.get(key) != manifests[0].get(key) for m in manifests[1:])]
    reports = [report(run) for run in runs]
    return {"same_start_conditions": not mismatches, "different_fields": mismatches,
            "comparable_for_strategy": not mismatches and all(r["assignment_matches"] is True
                and r["match_outcome"] in ("llm_win", "llm_loss", "draw") for r in reports),
            "randomness_controlled": False,
            "warning": "Repeated games are required; a declared seed is not proof that VCMI used it.",
            "runs": [{"run_id": r["run_id"], "outcome": r["match_outcome"], "counts": r["counts"],
                      "latency_seconds": r["latency_seconds"], "assignment_matches": r["assignment_matches"],
                      "references": r["references"]} for r in reports]}
