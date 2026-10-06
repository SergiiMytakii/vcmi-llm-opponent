"""Independent analyst cancellation, exclusivity and unavailable knowledge."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'controller'))
from analyze import analyst_lock
from knowledge import snapshot_for_request
from playtesting.learning import LearningRuntime


class LearningRuntimeTest(unittest.TestCase):
    def test_only_one_analyst_can_own_a_database(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'experience.sqlite3'
            code=f"import sys;sys.path.insert(0,{str(ROOT/'controller')!r});from analyze import analyst_lock\nwith analyst_lock({str(path)!r}):print('owned')"
            with analyst_lock(path):
                result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=3)
                self.assertNotEqual(result.returncode,0)
            result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=3)
            self.assertEqual(result.returncode,0,result.stderr)

    @unittest.skipIf(os.name=='nt','POSIX process-group proof')
    def test_stop_cleans_descendant_even_when_analyst_root_already_exited(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);ready=folder/'ready'
            runtime=LearningRuntime(folder,{})
            runtime.directory.mkdir()
            descendant=f"import signal,time,pathlib;signal.signal(signal.SIGTERM,signal.SIG_IGN);pathlib.Path({str(ready)!r}).touch();time.sleep(60)"
            parent=f"import subprocess,sys;subprocess.Popen([sys.executable,'-c',{descendant!r}])"
            runtime.child=subprocess.Popen([sys.executable,'-c',parent],start_new_session=True)
            try:
                deadline=time.monotonic()+3
                while not ready.exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(ready.exists())
                runtime.child.wait(timeout=3)
                runtime.finish()
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    states=subprocess.check_output(['ps','-axo','pgid=,stat='],text=True).splitlines()
                    active=[s for s in states if s.split()[0]==str(runtime.child.pid) and not s.split()[1].startswith('Z')]
                    if not active:break
                    time.sleep(.01)
                self.assertEqual(active,[])
            finally:
                try:os.killpg(runtime.child.pid,signal.SIGKILL)
                except ProcessLookupError:pass

    def test_corrupt_provenance_is_unavailable_instead_of_blocking_strategy(self):
        rules={'engine_version':'1.8','engine_revision':'fixture','mods':[{'id':'core','version':''}]}
        from experience import execution_context
        current=execution_context({'rules':rules,'execution_mechanism':'native_campaign_v3'})
        for broken in ('bad',None,[],{},True,-1,1.5):
            lesson={'id':'one','rule':'Check current facts.','conditions':['tempo'],'evidence_contexts':[
                {**current,'supporting_games':broken}]}
            with patch.dict(os.environ,{'VCMI_EXPERIENCE_MODE':'learn'},clear=True), patch(
                'knowledge.Path.read_bytes',return_value=json.dumps({'version':1,'lessons':[lesson]}).encode()):
                self.assertEqual(snapshot_for_request({'protocol':2,'observation':{'rules':rules}})['lessons'],[])

    def test_default_database_publication_is_available_without_an_environment_override(self):
        with patch.dict(os.environ,{'VCMI_EXPERIENCE_MODE':'learn'},clear=True), patch(
            'knowledge.Path.read_bytes',return_value=json.dumps({'version':1,'revision':'published','lessons':[]}).encode()) as read:
            snapshot=snapshot_for_request({'protocol':2,'observation':{}})
            self.assertEqual(snapshot['revision'],'published')
            self.assertEqual(read.call_count,1)

    def test_missing_or_corrupt_knowledge_does_not_require_strategy_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'knowledge.json'
            for content in ('invalid','[]','null','1',json.dumps({'version':1,'lessons':[{'rule':'advice','evidence_contexts':'corrupt'}]})):
                path.write_text(content)
                with patch.dict(os.environ,{'VCMI_EXPERIENCE_MODE':'read_only','VCMI_KNOWLEDGE_FILE':str(path),
                    'VCMI_PLAYTEST_KNOWLEDGE':str(Path(folder)/'missing-guide')}):
                    snapshot=snapshot_for_request({'protocol':2,'observation':{}})
                    self.assertEqual(snapshot['lessons'],[])


if __name__=='__main__':unittest.main()
