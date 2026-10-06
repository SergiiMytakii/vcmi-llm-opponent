import argparse
import json
import os
import sys

from .runs import prepare
from .reports import report, compare, episode, outcome
from .launcher import run_game
from .controller import replay


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Private, repeatable VCMI playtests")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare", help="Snapshot a fixture and versioned inputs; never overwrite")
    p.add_argument("--config", required=True)
    p.add_argument("--out", required=True)
    p = commands.add_parser("run", help="Launch one fresh isolated macOS developer game")
    p.add_argument("--run", required=True)
    p = commands.add_parser("replay", help="Repeat a recorded observation against a fresh controller version; no game")
    p.add_argument("--source-run", required=True)
    p.add_argument("--decision", required=True)
    p.add_argument("--target-run", required=True)
    p = commands.add_parser("stop", help="Request cleanup of this tester-owned run")
    p.add_argument("--run", required=True)
    p = commands.add_parser('continue', help='Release exactly one reviewed block of game days')
    p.add_argument('--run', required=True)
    p.add_argument('--completed-day', type=int, required=True)
    p = commands.add_parser("report", help="Summarize replies, engine results, and manual episodes")
    p.add_argument("--run", required=True)
    p = commands.add_parser("compare", help="Compare runs and flag different starting conditions")
    p.add_argument("--runs", nargs="+", required=True)
    p = commands.add_parser("episode", help="Record a concrete problem without changing the strategy")
    p.add_argument("--run", required=True)
    p.add_argument("--decision", required=True)
    p.add_argument("--category", choices=["integration", "missing_information", "missing_action", "strategy"], required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--evidence")
    p = commands.add_parser("outcome", help="Attach reviewed evidence of the game result")
    p.add_argument("--run", required=True)
    p.add_argument("--result", choices=["llm_win", "llm_loss", "draw", "aborted"], required=True)
    p.add_argument("--evidence", required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.config, args.out)
            print(json.dumps({"run_id": result["run_id"], "status": result["status"]}))
        elif args.command == "report":
            result = report(args.run)
            print(json.dumps({"run_id": result["run_id"], "counts": result["counts"], "match_outcome": result["match_outcome"]}))
        elif args.command == "compare":
            print(json.dumps(compare(args.runs), ensure_ascii=False, indent=2))
        elif args.command == "episode":
            print(json.dumps(episode(args.run, args.decision, args.category, args.text, args.evidence)))
        elif args.command == "outcome":
            print(json.dumps(outcome(args.run, args.result, args.evidence)))
        elif args.command == "run":
            result = run_game(args.run)
            print(json.dumps(result))
            if (result["reason"] in ("setup_failed", "assignment_mismatch", "cleanup_failed")
                    or (result["reason"] == "process_exit" and result["returncode"] != 0)
                    or not result["protected_files_unchanged"]):
                sys.exit(1)
        elif args.command == "replay":
            result = replay(args.source_run, args.decision, args.target_run)
            print(json.dumps(result))
            if result["status"] != "reply_valid":
                sys.exit(1)
        elif args.command == 'continue':
            from .turn_review import continue_review
            print(json.dumps(continue_review(args.run, args.completed_day)))
        elif args.command == "stop":
            from pathlib import Path
            from .runs import load
            if load(args.run)["status"] != "running":
                raise ValueError("run is not running")
            (Path(args.run) / "STOP").touch(exist_ok=False)
            print("stop requested")
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"playtest: {error}", file=sys.stderr)
        sys.exit(1)
