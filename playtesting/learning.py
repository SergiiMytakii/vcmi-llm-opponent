"""Supervise one independent analyst and all its model descendants."""
import os
from pathlib import Path
import signal
import subprocess
import sys

from .runs import ROOT


def publish_knowledge(database):
    subprocess.run([sys.executable,str(ROOT/'controller/analyze.py'),'--database',str(database),
        '--publish-only'],check=True,timeout=5,capture_output=True)
    return Path(database).with_suffix('.knowledge.json')


class LearningRuntime:
    def __init__(self,run,manifest):
        self.run=Path(run);self.manifest=manifest;self.child=None;self.stream=None;self.command=None
        self.directory=self.run/'learning'
        self.journal=self.directory/'turns.jsonl'

    def start(self,env):
        self.directory.mkdir(parents=True,exist_ok=True)
        env['VCMI_NK3_LEARNING_JOURNAL']=str(self.journal)
        experience=self.manifest.get('experience',{})
        if experience.get('mode')!='learn':return
        finish=self.directory/'FINISH'
        if finish.exists():finish.unlink()
        database=experience['database']
        publish_knowledge(database)
        players=','.join(str(i) for i,color in enumerate(('red','blue','tan','green','orange','purple','teal','pink'))
            if self.manifest.get('players',{}).get(color)=='Nullkiller3')
        command=[sys.executable,str(ROOT/'controller/analyze.py'),'--database',database,
            '--journal',str(self.journal),'--players',players,
            '--stop-file',str(self.run/'STOP'),'--finish-file',str(self.directory/'FINISH'),
            '--records',str(self.directory/'calls'),
            '--max-calls',str(self.manifest.get('analysis_max_calls',12)),
            '--max-tokens',str(self.manifest.get('analysis_max_tokens',200000)),
            '--timeout',str(self.manifest.get('analysis_timeout_seconds',60)),
            '--interval',str(self.manifest.get('analysis_interval_seconds',5)),
            '--idle-turns',str(self.manifest.get('analysis_idle_turns',2)),
            '--mine-turns',str(self.manifest.get('analysis_mine_turns',2)),
            '--scouting-turns',str(self.manifest.get('analysis_scouting_turns',3)),
            '--model',self.manifest.get('analysis_model','gpt-6.1-sol'),
            '--effort',self.manifest.get('analysis_reasoning_effort','low')]
        self.command=command
        self.stream=(self.directory/'runtime.log').open('wb')
        try:
            if os.name=='nt':
                from scripts.windows_process import JobProcess
                self.child=JobProcess(command,cwd=ROOT,env=env,log=self.stream,
                    cleanup_path=self.directory/'cleanup.json')
            else:
                self.child=subprocess.Popen(command,stdout=self.stream,stderr=subprocess.STDOUT,
                    env=env,start_new_session=True)
        except OSError:
            self.stream.close();self.stream=None;raise

    def finish(self,natural=False):
        if self.child is None:return
        if natural:
            (self.directory/'FINISH').touch()
            try:self.child.wait(timeout=self.manifest.get('analysis_timeout_seconds',60)+7)
            except subprocess.TimeoutExpired:pass
        if os.name=='nt':
            self.child.close()
        else:
            # Clean the entire owned group even when its root already exited.
            try:os.killpg(self.child.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:self.child.wait(timeout=2)
            except subprocess.TimeoutExpired:pass
            # A reparented model/MCP process can survive the root's exit.
            try:os.killpg(self.child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        self.child.wait(timeout=3)
        if self.stream:self.stream.close()
        # Drain durable own receipts after cancelling models; this never invokes GPT.
        if self.command and self.journal.is_file():
            result=subprocess.run([*self.command,'--collect-only'],capture_output=True,timeout=5)
            (self.directory/'collection-final.json').write_bytes(result.stdout)
            if result.returncode:raise RuntimeError('final own telemetry collection failed')
