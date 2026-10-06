"""Link the actual native evaluator object; no copied implementation or game launch."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
BUILD=Path(os.environ.get('VCMI_BUILD',ROOT/'.build/nk3-mac'))
OBJECT=Path('AI/Nullkiller2/CMakeFiles/Nullkiller2.dir/Goals/ExploreNeighbourTile.cpp.o')
NINJA=ROOT/'.venv/bin/ninja'

@unittest.skipUnless((BUILD/OBJECT).exists() and NINJA.exists(),'requires prepared native evaluator object')
class NeighbourExplorationTest(unittest.TestCase):
    def test_strategic_fallback_rejects_phantom_progress_and_keeps_discovery(self):
        recipe=subprocess.check_output([str(NINJA),'-C',str(BUILD),'-t','commands',str(OBJECT)],text=True)
        command=shlex.split(recipe.strip().splitlines()[-1])
        compiler=command[0]
        with tempfile.TemporaryDirectory() as folder:
            obj=Path(folder)/'driver.o';binary=Path(folder)/'driver'
            command[command.index('-c')+1]=str(ROOT/'tests/neighbour_exploration_driver.cpp')
            command[command.index('-o')+1]=str(obj)
            command=[x for x in command if x!='-MD']
            for flag in ('-MF','-MT'):
                if flag in command:
                    i=command.index(flag);command[i:i+2]=[]
            subprocess.run(command,cwd=BUILD,check=True,capture_output=True,text=True)
            sdk=os.environ.get('SDKROOT','/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk')
            subprocess.run([compiler,'-isysroot',sdk,str(obj),str(BUILD/OBJECT),str(BUILD/'bin/libvcmi.dylib'),
                '-Wl,-dead_strip','-Wl,-rpath,'+str(BUILD/'bin'),'-o',str(binary)],check=True,capture_output=True,text=True)
            result=subprocess.run([str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
