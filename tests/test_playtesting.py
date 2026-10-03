"""Playtest CLI checks with real files and controller processes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "playtest.py"
DATA_PATH = Path("Library/Application Support/vcmi")


class PlaytestingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="playtest Зов ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = self.root / "fixture-home"
        self.data = self.profile / "Library/Application Support/vcmi"
        (self.data / "Maps").mkdir(parents=True)
        (self.data / "config").mkdir()
        (self.data / "Maps/Trial.h3m").write_bytes(b"private map fixture")
        (self.data / "config/settings.json").write_text('{}')
        self.prompt = self.root / "strategy.md"
        self.prompt.write_text("Choose an offered action.")
        self.config = self.root / "config.json"
        self.run_dir = self.root / "run"
        self.settings = {
            "version": 1, "case_id": "trial", "purpose": "integration",
            "engine": str(sys.executable), "profile_template": str(self.profile),
            "map_resource": "Maps/Trial.h3m", "controller": [
                sys.executable, str(ROOT / "controller/main.py")],
            "references": {"prompt": str(self.prompt)},
            "players": {"red": "ExternalAI", "blue": "Nullkiller2"},
            "seed": None, "difficulty": "normal", "max_seconds": 60,
            "decision_timeout_seconds": 2,
        }

    def cli(self, *args, **kwargs):
        return subprocess.run([sys.executable, str(CLI), *map(str, args)],
                              text=True, capture_output=True, timeout=10, **kwargs)

    def prepare(self):
        self.config.write_text(json.dumps(self.settings))
        result = self.cli("prepare", "--config", self.config, "--out", self.run_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads((self.run_dir / "manifest.json").read_text())

    def hook(self, request):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/playtest_controller.py")],
            input=json.dumps(request), text=True, capture_output=True, timeout=5,
            env={**os.environ, "VCMI_PLAYTEST_RUN": str(self.run_dir)},
        )

    def request(self):
        return {"protocol": 1, "request_id": "0:1", "observation": {"player": 0, "day": 1},
                "actions": [{"id": "end", "kind": "end_turn"}]}

    def test_prepares_private_snapshot_and_refuses_to_overwrite_a_run(self):
        manifest = self.prepare()
        self.assertEqual(manifest["case_id"], "trial")
        self.assertEqual(manifest["status"], "prepared")
        self.assertEqual((self.run_dir / "references/prompt.md").read_text(),
                         "Choose an offered action.")
        self.prompt.write_text("changed after preparation")
        self.assertEqual((self.run_dir / "references/prompt.md").read_text(),
                         "Choose an offered action.")
        result = self.cli("prepare", "--config", self.config, "--out", self.run_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads((self.run_dir / "manifest.json").read_text())["run_id"],
                         manifest["run_id"])

    def test_engine_hook_keeps_protocol_clean_and_records_the_actual_exchange(self):
        self.prepare()
        request = {"protocol": 1, "request_id": "0:1", "observation": {"player": 0, "day": 1},
                   "actions": [{"id": "end", "kind": "end_turn"},
                               {"id": "build-0", "kind": "build"}]}
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/playtest_controller.py")],
            input=json.dumps(request), text=True, capture_output=True, timeout=5,
            env={**os.environ, "VCMI_PLAYTEST_RUN": str(self.run_dir)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "protocol": 1, "request_id": "0:1", "action_id": "build-0"})
        directories = list((self.run_dir / "decisions").iterdir())
        self.assertEqual(len(directories), 1)
        decision = directories[0]
        self.assertEqual(json.loads((decision / "request.json").read_text()), request)
        record = json.loads((decision / "result.json").read_text())
        self.assertEqual(record["status"], "reply_valid")
        self.assertEqual(record["action_id"], "build-0")
        self.assertEqual(record["execution"], "unconfirmed")
        self.assertGreaterEqual(record["duration_seconds"], 0)

    def test_report_requires_engine_evidence_and_does_not_call_an_exit_a_victory(self):
        self.prepare()
        decision = self.run_dir / "decisions/one"
        decision.mkdir()
        (decision / "result.json").write_text(json.dumps({
            "status": "reply_valid", "request_id": "0:1", "action_id": "build-0",
            "duration_seconds": 0.3, "execution": "unconfirmed"}))
        (self.run_dir / "launch.json").write_text(json.dumps({"reason": "process_exit", "returncode": 0}))
        logs = self.run_dir / "engine-logs"
        logs.mkdir()
        (logs / "VCMI_Client_log.txt").write_text(
            "Player red will be lead by ExternalAI\nPlayer blue will be lead by Nullkiller2\n"
            "ExternalAI request 0:1 selected build-0\n"
            "ExternalAI build result town=7 building=10 observed=1 request=0:1 action=build-0\n")
        result = self.cli("report", "--run", self.run_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.run_dir / "report.json").read_text())
        self.assertEqual(report["decisions"][0]["execution"], "build_observed")
        self.assertEqual(report["match_outcome"], "unconfirmed")
        self.assertTrue(report["assignment_matches"])
        self.assertEqual(report["counts"]["reply_valid"], 1)
        self.assertIn("unconfirmed", (self.run_dir / "report.md").read_text())

    def test_refuses_changed_profile_before_starting_any_game_process(self):
        self.prepare()
        (self.run_dir / "profile" / DATA_PATH / "config/settings.json").write_text('{"changed":true}')
        result = self.cli("run", "--run", self.run_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("profile changed", result.stderr)
        self.assertFalse((self.run_dir / "launch.json").exists())

    def test_timeout_keeps_evidence_and_returns_no_engine_reply(self):
        self.settings["controller"] = [sys.executable, "-c", "import time; time.sleep(30)"]
        self.settings["decision_timeout_seconds"] = 0.15
        self.prepare()
        result = self.hook(self.request())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        records = list((self.run_dir / "decisions").glob("*/result.json"))
        record = json.loads(records[0].read_text())
        self.assertEqual(record["status"], "timeout")
        self.assertLess(record["duration_seconds"], 2)

    def test_stale_reply_is_rejected_and_stderr_is_retained(self):
        self.settings["controller"] = [sys.executable, "-c",
            'import sys; print("debug", file=sys.stderr); '
            'print(\'{"protocol":1,"request_id":"old","action_id":"end"}\')']
        self.prepare()
        result = self.hook(self.request())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        directory = next((self.run_dir / "decisions").iterdir())
        self.assertEqual((directory / "stderr.log").read_text(), "debug\n")
        self.assertEqual(json.loads((directory / "result.json").read_text())["status"], "invalid_reply")

    def test_output_limits_fail_closed_and_keep_bounded_evidence(self):
        self.settings["controller"] = [sys.executable, "-c", "print('x'*9000)"]
        self.prepare()
        result = self.hook(self.request())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        directory = next((self.run_dir / "decisions").iterdir())
        self.assertEqual(json.loads((directory / "result.json").read_text())["status"], "output_limit")
        self.assertEqual((directory / "stdout.bin").stat().st_size, 8192)

    def test_malformed_request_is_preserved_and_report_still_describes_the_failure(self):
        self.prepare()
        result = subprocess.run([sys.executable, str(ROOT / "scripts/playtest_controller.py")],
            input="{bad json", text=True, capture_output=True, timeout=5,
            env={**os.environ, "VCMI_PLAYTEST_RUN": str(self.run_dir)})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        result = self.cli("report", "--run", self.run_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.run_dir / "report.json").read_text())
        self.assertEqual(report["counts"], {"recording_error": 1})

    @unittest.skipUnless(sys.platform == "darwin", "macOS sandbox regression")
    def test_timeout_is_recorded_inside_the_actual_game_sandbox(self):
        self.settings["controller"] = [sys.executable, "-c", "import time; time.sleep(30)"]
        self.settings["decision_timeout_seconds"] = 0.15
        self.prepare()
        sandbox = self.root / "profile.sb"
        sandbox.write_text('(version 1)\n(allow default)\n(deny file-write* (subpath "/unused-vcmi-profile"))\n')
        result = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(sandbox), sys.executable,
                                 str(ROOT / "scripts/playtest_controller.py")],
            input=json.dumps(self.request()), text=True, capture_output=True, timeout=5,
            env={**os.environ, "VCMI_PLAYTEST_RUN": str(self.run_dir)})
        self.assertNotEqual(result.returncode, 0)
        record = json.loads(next((self.run_dir / "decisions").glob("*/result.json")).read_text())
        self.assertEqual(record["status"], "timeout")

    @unittest.skipUnless(os.name != "nt" and Path(os.environ.get("EXCHANGE_DRIVER", ROOT / ".build/transport/exchange-driver")).is_file(),
                         "build the native exchange driver for ownership proof")
    def test_cleanup_stops_controller_in_the_native_adapters_separate_group(self):
        sys.path.insert(0, str(ROOT))
        from playtesting.launcher import terminate_group
        driver = Path(os.environ.get("EXCHANGE_DRIVER", ROOT / ".build/transport/exchange-driver")).resolve()
        ready, survived = self.root / "ready", self.root / "survived"
        code = (f"import pathlib,os,time; pathlib.Path({str(ready)!r}).write_text(str(os.getpid())); "
                f"time.sleep(0.8); pathlib.Path({str(survived)!r}).touch(); time.sleep(30)")
        child = subprocess.Popen([str(driver), "20000", sys.executable, "-c", code],
                                 stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
        child.stdin.close()
        deadline = time.monotonic() + 3
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        try:
            self.assertTrue(ready.exists(), "native controller did not start")
            self.assertNotEqual(os.getpgid(int(ready.read_text())), child.pid)
            terminate_group(child)
            time.sleep(0.9)
            self.assertFalse(survived.exists(), "controller survived tester cleanup")
        finally:
            if child.poll() is None:
                os.killpg(child.pid, 9)
                child.wait()
            if ready.exists():
                try:
                    os.kill(int(ready.read_text()), 9)
                except ProcessLookupError:
                    pass

    @unittest.skipUnless(os.name != "nt" and Path(os.environ.get("EXCHANGE_DRIVER", ROOT / ".build/transport/exchange-driver")).is_file(),
                         "build the native exchange driver for crash ownership proof")
    def test_cleanup_stops_reparented_native_controller_after_the_game_crashes(self):
        sys.path.insert(0, str(ROOT))
        from playtesting.launcher import terminate_group
        driver = Path(os.environ.get("EXCHANGE_DRIVER", ROOT / ".build/transport/exchange-driver")).resolve()
        ready, survived = self.root / "crash-ready", self.root / "crash-survived"
        code = (f"import pathlib,os,time; pathlib.Path({str(ready)!r}).write_text(str(os.getpid())); "
                f"time.sleep(0.8); pathlib.Path({str(survived)!r}).touch(); time.sleep(30)")
        child = subprocess.Popen([str(driver), "20000", sys.executable, "-c", code],
                                 stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
        child.stdin.close()
        deadline = time.monotonic() + 3
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        try:
            self.assertTrue(ready.exists(), "native controller did not start")
            controller_pid = int(ready.read_text())
            self.assertEqual(os.getsid(controller_pid), child.pid)
            child.kill()
            child.wait(timeout=2)
            terminate_group(child)
            time.sleep(0.9)
            self.assertFalse(survived.exists(), "reparented controller survived game crash cleanup")
        finally:
            if child.poll() is None:
                os.killpg(child.pid, 9)
                child.wait()
            if ready.exists():
                try:
                    os.kill(int(ready.read_text()), 9)
                except ProcessLookupError:
                    pass

    def test_episode_and_outcome_preserve_evidence_and_are_marked_as_manual(self):
        self.prepare()
        self.assertEqual(self.hook(self.request()).returncode, 0)
        decision = next((self.run_dir / "decisions").iterdir()).name
        evidence = self.root / "result.txt"
        evidence.write_text("Human observed the final result.")
        result = self.cli("episode", "--run", self.run_dir, "--decision", decision,
                          "--category", "strategy", "--text", "Ended a useful turn too early.", "--evidence", evidence)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.cli("outcome", "--run", self.run_dir, "--result", "llm_loss", "--evidence", evidence)
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence.unlink()
        self.assertEqual(self.cli("report", "--run", self.run_dir).returncode, 0)
        report = json.loads((self.run_dir / "report.json").read_text())
        self.assertEqual(report["match_outcome"], "llm_loss")
        self.assertEqual(report["outcome_source"], "manual evidence")
        self.assertEqual(len(report["episodes"]), 1)
        self.assertEqual(len(list((self.run_dir / "evidence").iterdir())), 2)
        self.assertIsNone(report["assignment_matches"])

    def test_source_changes_are_not_silently_attributed_to_the_old_version(self):
        script = self.root / "controller.py"
        script.write_text("print('original')")
        self.settings["controller"] = [sys.executable, str(script)]
        self.prepare()
        script.write_text("print('changed')")
        result = self.hook(self.request())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        record = json.loads(next((self.run_dir / "decisions").glob("*/result.json")).read_text())
        self.assertIn("source changed", record["error"])

    def test_repeated_ids_after_load_are_not_joined_to_one_engine_result(self):
        self.prepare()
        for unused in range(2):
            self.assertEqual(self.hook(self.request()).returncode, 0)
        logs = self.run_dir / "engine-logs"
        logs.mkdir()
        (logs / "VCMI_Client_log.txt").write_text("ExternalAI request 0:1 selected end\n")
        self.assertEqual(self.cli("report", "--run", self.run_dir).returncode, 0)
        report = json.loads((self.run_dir / "report.json").read_text())
        self.assertEqual(report["decision_count"], 2)
        self.assertTrue(all(d["execution"] == "unconfirmed" for d in report["decisions"]))

    def test_replay_uses_recorded_observation_and_comparison_flags_a_different_map(self):
        self.prepare()
        self.assertEqual(self.hook(self.request()).returncode, 0)
        decision = next((self.run_dir / "decisions").iterdir()).name
        second = self.root / "second"
        self.assertEqual(self.cli("prepare", "--config", self.config, "--out", second).returncode, 0)
        result = self.cli("replay", "--source-run", self.run_dir, "--decision", decision, "--target-run", second)
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(record["action_id"], "end")
        replay_dir = second / "decisions" / record["decision_id"]
        self.assertEqual(json.loads((replay_dir / "request.json").read_text()), self.request())
        comparison = self.cli("compare", "--runs", self.run_dir, second)
        self.assertTrue(json.loads(comparison.stdout)["same_start_conditions"])
        self.assertFalse(json.loads(comparison.stdout)["comparable_for_strategy"])
        (self.data / "Maps/Trial.h3m").write_bytes(b"different map")
        third = self.root / "third"
        self.assertEqual(self.cli("prepare", "--config", self.config, "--out", third).returncode, 0)
        comparison = self.cli("compare", "--runs", self.run_dir, third)
        self.assertFalse(json.loads(comparison.stdout)["same_start_conditions"])
        self.assertIn("map_sha256", json.loads(comparison.stdout)["different_fields"])


if __name__ == "__main__":
    unittest.main()
