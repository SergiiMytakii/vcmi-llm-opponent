"""Public native callbacks: start snapshot, restore gap and log-only diagnostics."""
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_NATIVE_BUILD'),
                     'requires the prepared NK3 client build on macOS')
class BattleCallbackTest(unittest.TestCase):
    def test_start_snapshot_and_unknown_restoration_do_not_extend_saved_memory(self):
        build=Path(os.environ['VCMI_NK3_NATIVE_BUILD']).resolve()
        cache=(build/'CMakeCache.txt').read_text()
        source=Path(next(line.split('=',1)[1] for line in cache.splitlines()
                         if line.startswith('CMAKE_HOME_DIRECTORY:')))
        # Reuse this build's complete native link contract, replacing only its entry point.
        ninja=next(line.split('=',1)[1] for line in cache.splitlines() if line.startswith('CMAKE_MAKE_PROGRAM:'))
        commands=subprocess.check_output([ninja,'-C',str(build),'-t','commands','vcmiclient'],text=True)
        args=shlex.split(commands.splitlines()[-1]);args=args[args.index('&&')+1:];args=args[:args.index('&&')]
        with tempfile.TemporaryDirectory(prefix='nk3-callback-',dir=ROOT/'.build') as folder:
            folder=Path(folder);binary=folder/'callbacks'
            args[args.index('clientapp/CMakeFiles/vcmiclient.dir/EntryPoint.cpp.o')]=str(ROOT/'tests/nullkiller3_battle_callback_driver.cpp')
            args[args.index('bin/vcmiclient')]=str(binary)
            compile_line=next(line for line in commands.splitlines() if 'NativeCampaign.cpp.o' in line and ' -c ' in line)
            includes=[a for a in shlex.split(compile_line) if a.startswith('-I') or a.startswith('-D')]
            # -isystem is a separate pair in native compilation.
            parts=shlex.split(compile_line)
            for i,part in enumerate(parts):
                if part=='-isystem':includes.extend([part,parts[i+1]])
            args[1:1]=['-std=c++20',*includes]
            # AI internals are hidden in libvcmi; exercise the actual compiled
            # owner objects without changing production exports for testing.
            args.extend(str(p) for p in sorted((build/'AI').rglob('*.cpp.o')))
            result=subprocess.run(args,cwd=build,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr[-4000:])
            result=subprocess.run([str(binary),str(folder/'journal.jsonl')],text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('memory isolation passed',result.stdout)


if __name__=='__main__':unittest.main()
