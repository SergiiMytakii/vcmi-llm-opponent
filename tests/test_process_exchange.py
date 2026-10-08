"""Real subprocess checks; build exchange-driver before running this module."""
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("EXCHANGE_DRIVER", ROOT / ".build" / "exchange-driver"))


class ProcessExchangeTest(unittest.TestCase):
    def test_pending_background_does_not_delay_foreground_eof_or_destruction(self):
        driver=DRIVER.parent/('background-exchange-driver.exe' if os.name=='nt' else 'background-exchange-driver')
        with tempfile.TemporaryDirectory() as folder:
            slow=Path(folder)/'slow.py';fast=Path(folder)/'fast.py'
            slow.write_text('import sys,time\nsys.stdin.read()\ntime.sleep(30)\n')
            fast.write_text('import sys,time\ntime.sleep(.2)\nsys.stdin.read()\nprint("foreground")\n')
            result=subprocess.run([str(driver),sys.executable,str(slow),str(fast)],
                                  text=True,capture_output=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('foreground completed without waiting',result.stdout)
            self.assertIn('fresh foreground transport after spent time and spawn failure, without callback',result.stdout)

    def test_controller_json_is_minified_without_changing_escaped_strings(self):
        driver = DRIVER.parent / ('json-transport-driver.exe' if os.name == 'nt' else 'json-transport-driver')
        facts = {'values':[1, True, None, [], {}], 'text':'Привет \" герой \\ путь\n\t',
                 'literal':'\\\" \" : , \\n'}
        result = subprocess.run([str(driver)], input=json.dumps(facts, ensure_ascii=False, indent=4),
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), facts)
        self.assertEqual(result.stdout, json.dumps(facts, ensure_ascii=False, separators=(',', ':')))

    def exchange(self, code, timeout=2000, request="request"):
        return subprocess.run(
            [str(DRIVER), str(timeout), sys.executable, "-c", code],
            input=request, text=True, capture_output=True, timeout=5,
        )

    def test_delivers_stdin_eof_and_collects_reply(self):
        result = self.exchange("import sys; print(sys.stdin.read().upper())")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "REQUEST\n")

    def test_accepts_512_kib_request_and_rejects_one_byte_more(self):
        code = "import sys; print(len(sys.stdin.buffer.read()))"
        for size in (262145, 524288):
            with self.subTest(size=size):
                result = self.exchange(code, request="x" * size)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, str(size) + "\n")
        result = self.exchange(code, request="x" * 524289)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("request too large", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_hung_controller_is_killed_within_bound(self):
        start = time.monotonic()
        result = self.exchange("import time; time.sleep(30)", timeout=150)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("timeout", result.stderr)
        self.assertLess(time.monotonic() - start, 2)

    def test_cancellation_interrupts_an_active_request(self):
        result = subprocess.run(
            [str(DRIVER), "20000", sys.executable, "-c", "import time; time.sleep(30)"],
            input="request", text=True, capture_output=True, timeout=2,
            env={**os.environ, "EXCHANGE_CANCEL_MS": "100"},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cancelled", result.stderr)

    def test_timeout_kills_descendants_too(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "should-not-exist"
            descendant = f"import time,pathlib; time.sleep(0.6); pathlib.Path({str(marker)!r}).touch()"
            result = self.exchange(
                f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{descendant!r}]); time.sleep(30)",
                timeout=200,
            )
            self.assertIn("timeout", result.stderr)
            time.sleep(0.7)
            self.assertFalse(marker.exists(), "descendant survived controller timeout")

    def test_oversized_reply_is_not_returned(self):
        result = self.exchange("print('x' * 8193)")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reply too large", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_strategic_reply_limit_includes_wire_usage_and_stays_bounded(self):
        for size in (8193, 32769, 33792, 33793):
            with self.subTest(size=size):
                result = subprocess.run(
                    [str(DRIVER), "2000", sys.executable, "-c",
                     f"import sys; sys.stdin.read(); sys.stdout.write('x' * {size})"],
                    input="request", text=True, capture_output=True, timeout=5,
                    env={**os.environ, "EXCHANGE_REPLY_BYTES": "33792"})
                if size <= 33792:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(len(result.stdout.encode()), size)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("reply too large", result.stderr)
                    self.assertEqual(result.stdout, "")

    def test_nonzero_exit_does_not_return_partial_reply(self):
        result = self.exchange("import sys; print('partial'); sys.exit(7)")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_retryable_controller_exit_is_a_timeout_without_an_action(self):
        result = self.exchange("import sys; sys.stdin.read(); sys.exit(75)")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertIn('timeout', result.stderr)

    def test_early_exit_while_receiving_large_request_does_not_kill_host(self):
        result = self.exchange("import sys; sys.exit(7)", request="x" * 200000)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotEqual(result.stderr, "")
        self.assertEqual(result.stdout, "")

    def test_unicode_script_path_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="Зов героя ") as directory:
            script = Path(directory) / "ответ AI.py"
            script.write_text("import sys; print(sys.stdin.read())", encoding="utf-8")
            result = subprocess.run(
                [str(DRIVER), "2000", sys.executable, str(script)],
                input="ok", text=True, capture_output=True, timeout=5,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "ok\n")

    def test_descendant_inheriting_stdout_cannot_hold_request_open(self):
        result = self.exchange(
            "import subprocess,sys; "
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
            "print('done')"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "done\n")


if __name__ == "__main__":
    unittest.main()
