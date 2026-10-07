"""Playtest CLI checks with real files and controller processes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import sqlite3


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
                sys.executable, str(ROOT / "tests/fixtures/recruit_first.py")],
            "references": {"prompt": str(self.prompt)},
            "players": {"red": "ExternalAI", "blue": "Nullkiller2"},
            "seed": None, "difficulty": "normal", "max_seconds": 60,
            "decision_timeout_seconds": 2,
            "experience_database": str(self.root / "fixture-experience.sqlite3"),
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

    def test_nullkiller3_records_native_comparison_mode(self):
        self.settings.update(players={"red":"Nullkiller3", "blue":"Nullkiller2"}, nk3_mode="native")
        self.assertEqual(self.prepare()["nk3_mode"], "native")

    def test_native_terminal_journal_accepts_only_recipient_own_execution(self):
        from controller.evaluation import TelemetryCollector
        self.settings.update(players={'red':'Nullkiller3','blue':'Nullkiller3'},experience_mode='learn')
        manifest=self.prepare();journal=self.root/'own-turns.jsonl'
        event=dict(version=1,game='red-game',generation='session',player=0,day=1,
                   sequence=1,phase='execution',complete=True,observation=dict(player=0,day=1),
                   own_result=dict(player=0,day=1,sequence=1,outcome='effects_observed',
                       action=dict(kind='build',before=dict(player=0),after=dict(player=0))))
        foreign={**event,'sequence':2,'own_result':{**event['own_result'],
            'action':dict(kind='battle',player=1)}}
        terminal={**event,'phase':'terminal','sequence':3,
            'observation':dict(player=0,day=1,terminal_result='loss')}
        terminal.pop('own_result')
        journal.write_text(''.join(json.dumps(e)+'\n' for e in (event,foreign,terminal)))
        collector=TelemetryCollector(manifest['experience']['database'],journal,{0});collector.poll()
        with sqlite3.connect(manifest['experience']['database']) as db:
            rows=[json.loads(r[0]) for r in db.execute('SELECT payload FROM turn_events')]
        self.assertEqual([r['sequence'] for r in rows],[1,3])
        self.assertEqual(rows[-1]['observation']['terminal_result'],'loss')

    def test_nullkiller3_rejects_ambiguous_comparison_mode(self):
        self.settings.update(players={"red":"Nullkiller3", "blue":"Nullkiller2"}, nk3_mode="silent")
        self.config.write_text(json.dumps(self.settings))
        result = self.cli("prepare", "--config", self.config, "--out", self.run_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nk3_mode", result.stderr)
        self.assertFalse(self.run_dir.exists())

    def test_recorder_and_controller_accept_512_kib_and_reject_one_byte_more(self):
        self.settings['controller'] = [sys.executable, str(ROOT / 'controller/main.py')]
        self.prepare()
        for size in (262145, 524288, 524289):
            with self.subTest(size=size):
                request = self.request()
                request['observation']['note'] = ''
                request['observation']['note'] = 'x' * (size - len(json.dumps(request).encode('utf-8')))
                raw = json.dumps(request).encode('utf-8')
                self.assertEqual(len(raw), size)
                result = subprocess.run(
                    [sys.executable, str(ROOT / 'scripts/playtest_controller.py')],
                    input=raw, capture_output=True, timeout=5,
                    env={**os.environ, 'VCMI_PLAYTEST_RUN':str(self.run_dir),
                         'VCMI_CODEX_EXECUTABLE':'/missing/codex'})
                if size <= 524288:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout)['action_id'], 'end')
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, b'')

    def test_off_comparison_never_opens_or_changes_the_lesson_library(self):
        library = self.root / 'lessons.sqlite3'
        library.write_bytes(b'unchanged private library')
        self.settings.update(experience_mode='off', experience_database=str(library))
        manifest = self.prepare()
        self.assertEqual(manifest['experience']['mode'], 'off')
        result = self.hook(self.request())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(library.read_bytes(), b'unchanged private library')
        self.assertFalse((self.run_dir / 'experience.sqlite3').exists())

    def test_prepares_private_snapshot_and_refuses_to_overwrite_a_run(self):
        manifest = self.prepare()
        self.assertEqual(manifest["case_id"], "trial")
        self.assertEqual(manifest["status"], "prepared")
        self.assertEqual((self.run_dir / "references/prompt.md").read_text(),
                         "Choose an offered action.")
        self.prompt.write_text("changed after preparation")
        self.assertEqual((self.run_dir / "references/prompt.md").read_text(),
                         "Choose an offered action.")
        source = self.data / "Maps/Trial.h3m"
        copied = self.run_dir / "profile" / DATA_PATH / "Maps/Trial.h3m"
        self.assertNotEqual(source.stat().st_ino, copied.stat().st_ino)
        copied.write_bytes(b"run-only modification")
        self.assertEqual(source.read_bytes(), b"private map fixture")
        source.write_bytes(b"template-only modification")
        self.assertEqual(copied.read_bytes(), b"run-only modification")
        result = self.cli("prepare", "--config", self.config, "--out", self.run_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads((self.run_dir / "manifest.json").read_text())["run_id"],
                         manifest["run_id"])

    def test_evaluation_learns_live_and_freezes_baseline_for_offline_replay(self):
        library = self.root / 'experience.sqlite3'
        with sqlite3.connect(library) as db:
            db.execute('CREATE TABLE fixture(value TEXT)')
            db.execute('INSERT INTO fixture VALUES(?)',('known lesson',))
        self.settings.update(purpose='evaluation',experience_database=str(library))
        manifest = self.prepare()
        self.assertEqual(manifest['experience']['mode'],'learn')
        self.assertEqual(manifest['experience']['database'],str(library.resolve()))
        frozen = self.run_dir / manifest['experience']['baseline']['path']
        before = frozen.read_bytes()
        with sqlite3.connect(library) as db:
            db.execute('INSERT INTO fixture VALUES(?)',('later lesson',))
        self.assertEqual(frozen.read_bytes(),before)
        self.assertEqual(self.hook(self.request()).returncode,0)
        frozen.write_bytes(b'corrupted frozen experience')
        result = self.hook(self.request())
        self.assertNotEqual(result.returncode,0)

    def test_evaluation_without_existing_experience_enables_learning_in_live_controller(self):
        library = self.root / 'new-experience.sqlite3'
        probe = self.root / 'experience_probe.py'
        probe.write_text('''import json, os, sys
request = json.load(sys.stdin)
assert os.environ['VCMI_EXPERIENCE_MODE'] == 'learn'
assert os.environ['VCMI_EXPERIENCE_DB'] == sys.argv[1]
print(json.dumps({'protocol':1, 'request_id':request['request_id'], 'action_id':'end'}))
''')
        self.settings.update(purpose='evaluation',experience_database=str(library),
                             controller=[sys.executable,str(probe),str(library.resolve())])
        manifest = self.prepare()
        self.assertIsNone(manifest['experience']['baseline'])
        result = self.hook(self.request())
        self.assertEqual(result.returncode,0,result.stderr)

    def test_offline_replay_reads_frozen_experience_without_writing_live_library(self):
        library = self.root / 'experience.sqlite3'
        with sqlite3.connect(library) as db:
            db.execute('CREATE TABLE fixture(value TEXT)')
        probe = self.root / 'replay_probe.py'
        probe.write_text('''import json, os, sqlite3, sys
request = json.load(sys.stdin)
if os.environ['VCMI_EXPERIENCE_MODE'] == 'learn':
    with sqlite3.connect(os.environ['VCMI_EXPERIENCE_DB']) as db:
        db.execute('INSERT INTO fixture VALUES(?)',('live',))
else:
    assert os.environ['VCMI_EXPERIENCE_MODE'] == 'read_only'
    assert os.environ['VCMI_EXPERIENCE_DB'].endswith('experience-before.sqlite3')
print(json.dumps({'protocol':1, 'request_id':request['request_id'], 'action_id':'end'}))
''')
        self.settings.update(purpose='evaluation',experience_database=str(library),
                             controller=[sys.executable,str(probe)])
        self.prepare()
        result = self.hook(self.request())
        self.assertEqual(result.returncode,0,result.stderr)
        decision = next((self.run_dir / 'decisions').iterdir()).name
        target = self.root / 'replay'
        result = self.cli('prepare','--config',self.config,'--out',target)
        self.assertEqual(result.returncode,0,result.stderr)
        before = library.read_bytes()
        result = self.cli('replay','--source-run',self.run_dir,'--decision',decision,'--target-run',target)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(library.read_bytes(),before)

    def test_game_run_purposes_use_the_same_persistent_default(self):
        self.settings.pop('experience_database')
        home=self.root/'home';home.mkdir()
        env={**os.environ,'HOME':str(home),'APPDATA':str(home/'AppData/Roaming'),'XDG_DATA_HOME':str(home/'data')}
        env.pop('VCMI_EXPERIENCE_DB',None)
        paths=[]
        for purpose in ('integration','training','evaluation'):
            self.settings['purpose']=purpose
            self.config.write_text(json.dumps(self.settings))
            run=self.root/purpose
            result=self.cli('prepare','--config',self.config,'--out',run,env=env)
            self.assertEqual(result.returncode,0,result.stderr)
            manifest=json.loads((run/'manifest.json').read_text())
            paths.append(manifest['experience']['database'])
            self.assertFalse(Path(paths[-1]).is_relative_to(run.resolve()))
        self.assertEqual(len(set(paths)),1)

    def test_integration_game_uses_the_configured_shared_experience_owner(self):
        manifest = self.prepare()
        self.assertEqual(manifest['experience']['database'],str(self.root.resolve()/'fixture-experience.sqlite3'))
        self.assertEqual(manifest['experience']['mode'],'learn')

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

    def test_saved_game_requires_an_existing_private_save(self):
        self.settings['save_resource'] = 'Saves/Missing.vsgm1'
        self.config.write_text(json.dumps(self.settings))
        result = self.cli('prepare', '--config', self.config, '--out', self.run_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('save', result.stderr)
        self.assertFalse(self.run_dir.exists())

    def test_saved_game_snapshot_records_content_and_rejects_escape(self):
        import hashlib
        (self.data / 'Saves').mkdir()
        saved = self.data / 'Saves/Resume.vsgm1'
        saved.write_bytes(b'private saved state')
        self.settings['save_resource'] = 'Saves/Resume.vsgm1'
        manifest = self.prepare()
        self.assertEqual(manifest['save_sha256'], hashlib.sha256(b'private saved state').hexdigest())
        saved.write_bytes(b'changed source save')
        self.assertEqual((self.run_dir / 'profile' / DATA_PATH / 'Saves/Resume.vsgm1').read_bytes(),
                         b'private saved state')
        self.settings['save_resource'] = 'Saves/../Maps/Trial.h3m'
        self.config.write_text(json.dumps(self.settings))
        result = self.cli('prepare', '--config', self.config, '--out', self.root / 'escaped')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('save_resource', result.stderr)

    def test_report_keeps_campaign_declarations_separate_from_confirmed_progress(self):
        self.prepare()
        decision = self.run_dir / 'decisions/one'
        decision.mkdir()
        request = self.request()
        request['memory'] = {'campaign':{'main_hero_ref':'object:7'},
                             'campaign_review':{'required':True,'reasons':['visible_threat_changed']},
                             'recent_results':[{'sequence':1,'day':1,'outcome':'completed',
                                                'action':{'kind':'transfer','destination':7,'amount':20}}]}
        (decision/'request.json').write_text(json.dumps(request))
        (decision/'result.json').write_text(json.dumps({'status':'reply_valid','request_id':'0:1','action_id':'end'}))
        (decision/'stdout.bin').write_text(json.dumps({'protocol':1,'request_id':'0:1','action_id':'end',
             'campaign':{'decision':'retain','reason':'Army delivered','evidence_refs':['result:1'],'plan':None}}))
        (decision/'explanation.json').write_text(json.dumps({'provider':'codex','usage':{'input_tokens':100,'output_tokens':30}}))
        self.assertEqual(self.cli('report','--run',self.run_dir).returncode,0)
        report = json.loads((self.run_dir/'report.json').read_text())
        self.assertEqual(report['decisions'][0]['campaign']['decision'], 'retain')
        self.assertEqual(report['campaign_metrics']['confirmed_reinforcements'][0]['amount'],20)
        self.assertEqual(report['model_metrics']['usage']['input_tokens'],100)
        self.assertEqual(report['match_outcome'],'unconfirmed')

    def test_report_counts_confirmed_own_battles_without_inferring_loss_from_task_net_changes(self):
        self.prepare()
        logs=self.run_dir/'engine-logs';logs.mkdir()
        records=[
            {'day':1,'sequence':1,'outcome':'battle_won','action':{'kind':'battle','source':'own_battle_result',
                'actor_ref':'object:0','army_loss_value':267}},
            {'day':1,'sequence':2,'outcome':'reconciled_unknown','action':{'kind':'visit',
                'before':{'heroes':[{'army_value':1000}]},'after':{'heroes':[{'army_value':20}]}}},
            {'day':1,'sequence':3,'outcome':'effects_observed','action':{'kind':'transfer',
                'before':{'heroes':[{'army_value':1000}]},'after':{'heroes':[{'army_value':700}]}}}]
        (logs/'VCMI_Client_log.txt').write_text(''.join('[2026-10-05 03:00:00.000] INFO [test] ai - NK3_EXECUTION '+json.dumps(r)+'\n' for r in records))
        result=self.cli('report','--run',self.run_dir)
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads((self.run_dir/'report.json').read_text())
        self.assertEqual(report['native_metrics']['battle_outcomes'],{'battle_won':1})
        self.assertEqual(report['native_metrics']['own_battle_loss_value'],267)
        self.assertEqual(len(report['native_execution']),3)
        self.assertEqual(report['match_outcome'],'unconfirmed','a battle victory became a match victory')

    def test_report_preserves_battle_origin_forecast_scope_and_retreat_cost_unknowns(self):
        self.prepare()
        logs=self.run_dir/'engine-logs';logs.mkdir()
        records=[
            {'day':2,'sequence':10,'outcome':'battle_won','action':{'kind':'battle','source':'own_battle_result',
                'actor_ref':'object:0','goal_id':'base','campaign_revision':4,'battle_origin':'campaign_operation',
                'own_side':'attacker','army_value_before':1000,'army_loss_value':100,
                'own_casualties':[{'creature_id':0,'count':2}],
                'selected_route':{'army_loss_estimate':250,'loss_estimate':{'path_component':50,'target_component':200},
                    'scope':'whole_native_route'}}},
            {'day':2,'sequence':11,'outcome':'battle_lost','action':{'kind':'battle','source':'own_battle_result',
                'actor_ref':'object:14','goal_id':'','battle_origin':'incoming_attack','own_side':'defender',
                'army_value_before':1000,'army_loss_value':0,'own_hero_return':'escape'}},
            {'day':1,'sequence':1,'outcome':'battle_won','action':{'kind':'battle','source':'own_battle_result',
                'actor_ref':'object:0','army_loss_value':20}}]
        (logs/'VCMI_Client_log.txt').write_text(''.join('[2026-10-07 00:00:00.000] INFO [test] ai - NK3_EXECUTION '+json.dumps(r)+'\n' for r in records))
        result=self.cli('report','--run',self.run_dir)
        self.assertEqual(result.returncode,0,result.stderr)
        value=json.loads((self.run_dir/'report.json').read_text())
        battles=value['battle_comparisons']
        self.assertEqual([b['origin'] for b in battles],['campaign_operation','incoming_attack','unknown'])
        self.assertEqual(battles[0]['campaign_revision'],4)
        self.assertEqual(battles[0]['forecast']['loss_estimate']['target_component'],200)
        self.assertEqual(battles[0]['actual_loss_ratio'],.1)
        self.assertEqual(battles[0]['actual_casualties'],[{'creature_id':0,'count':2}])
        self.assertEqual(battles[0]['comparison'],'route_estimate_not_single_battle')
        self.assertIsNone(battles[1]['forecast'])
        self.assertTrue(battles[1]['retreat_cost_unmeasured'])
        self.assertEqual(battles[1]['own_hero_return'],'escape')
        self.assertIsNone(battles[2]['actual_casualties'])
        self.assertEqual(battles[2]['comparison'],'unknown')
        self.assertIn('incoming_attack',(self.run_dir/'report.md').read_text())

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

    def test_model_timeout_is_forwarded_as_retryable_without_an_end_turn_reply(self):
        self.settings['controller'] = [sys.executable, '-c', 'import sys; sys.exit(75)']
        self.prepare()
        result = self.hook(self.request())
        self.assertEqual(result.returncode, 75)
        self.assertEqual(result.stdout, '')
        record = json.loads(next((self.run_dir / 'decisions').glob('*/result.json')).read_text())
        self.assertEqual(record['status'], 'timeout')
        self.assertEqual(record['returncode'], 75)

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

    def test_reused_batch_step_ids_from_distinct_choices_stay_unconfirmed(self):
        self.prepare()
        for request_id in ('0:1:0','0:1:1','0:1:2'):
            request = {**self.request(), 'request_id':request_id}
            self.assertEqual(self.hook(request).returncode, 0)
        logs = self.run_dir / 'engine-logs'
        logs.mkdir()
        (logs/'VCMI_Client_log.txt').write_text(
            'ExternalAI request 0:1:0 selected end\n'
            'ExternalAI request 0:1:2 selected recruit-0\n'
            'ExternalAI batch step request=0:1:2 action=recruit-0 source=0:1:0\n'
            'ExternalAI recruit result observed=0 request=0:1:2 action=recruit-0\n'
            'ExternalAI request 0:1:1 selected end\n'
            'ExternalAI request 0:1:2 selected recruit-0\n'
            'ExternalAI batch step request=0:1:2 action=recruit-0 source=0:1:1\n'
            'ExternalAI recruit result observed=1 request=0:1:2 action=recruit-0\n'
            'ExternalAI request 0:1:2 selected end\n')
        self.assertEqual(self.cli('report','--run',self.run_dir).returncode, 0)
        report = json.loads((self.run_dir/'report.json').read_text())
        self.assertEqual(len(report['batch_steps']), 2)
        self.assertEqual([s['execution'] for s in report['batch_steps']], ['unconfirmed','unconfirmed'])
        model_after_load = next(d for d in report['decisions'] if d['request_id']=='0:1:2')
        self.assertEqual(model_after_load['execution'], 'unconfirmed')

    def test_comparison_requires_resolved_frozen_experience_to_match(self):
        from unittest.mock import patch
        sys.path.insert(0, str(ROOT))
        from playtesting.reports import compare
        summaries = [{'run_id':str(i), 'match_outcome':'llm_loss', 'assignment_matches':True,
                      'counts':{}, 'latency_seconds':{}, 'model_metrics':{},
                      'campaign_metrics':{}, 'references':{}} for i in range(2)]
        manifests = [{'experience_mode':'read_only',
                      'experience':{'mode':'read_only','baseline':{'sha256':str(i)}}} for i in range(2)]
        with patch('playtesting.reports.load', side_effect=manifests), patch('playtesting.reports.report', side_effect=summaries):
            result = compare(['a', 'b'])
        self.assertFalse(result['same_start_conditions'])
        self.assertFalse(result['comparable_for_strategy'])
        manifests[1]['experience']['baseline']['sha256'] = '0'
        with patch('playtesting.reports.load', side_effect=manifests), patch('playtesting.reports.report', side_effect=summaries):
            self.assertTrue(compare(['a', 'b'])['comparable_for_strategy'])
        for manifest in manifests: manifest['experience']['mode'] = 'learn'
        with patch('playtesting.reports.load', side_effect=manifests), patch('playtesting.reports.report', side_effect=summaries):
            self.assertFalse(compare(['a', 'b'])['comparable_for_strategy'])

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
