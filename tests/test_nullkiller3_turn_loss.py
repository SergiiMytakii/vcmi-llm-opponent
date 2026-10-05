"""Real EndTurn during an unlocked model wait in the separate probe bundle."""
import json
import os
import re
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from test_nullkiller3_native import native_records

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/playtest.py'


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_TURN_LOSS_CONFIG'),
                     'requires the separate test-only turn-loss probe bundle')
class StrategicTurnLossTest(unittest.TestCase):
    def test_actual_turn_loss_interrupts_a_moving_chain_and_rebuilds_from_acknowledged_position(self):
        config=json.loads(Path(os.environ['VCMI_NK3_TURN_LOSS_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-movement-loss-',dir=ROOT/'.build/playtests'))
        print('\nNK3 movement-loss evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture)
        settings=fixture/'Library/Application Support/vcmi/config/settings.json'
        values=json.loads(settings.read_text())
        values.setdefault('adventure',{})['enemyMoveTime']=500
        settings.write_text(json.dumps(values))
        config.update(profile_template=str(fixture),players={'red':'Nullkiller3','blue':'EmptyAI'},
                      nk3_mode='native',references={},purpose='integration',case_id='nk3-movement-loss',
                      headless=False,max_seconds=25,experience_mode='off')
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        env=dict(os.environ,VCMI_NK3_TURN_LOSS_PROBE_MODE='movement')
        env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        logfile=run/'engine-logs/VCMI_Client_log.txt'
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+30
                while child.poll() is None and time.monotonic()<deadline:
                    if logfile.exists() and 'NK3_TEST_MOVED player=0 day=2' in logfile.read_text(errors='replace'): break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        text=logfile.read_text(errors='replace')
        self.assertIn('trigger=movement',text,'not the test-only movement driver')
        lost=text.index('Server ends turn of red')
        next_turn=text.index('Player 0 (red) starting turn, day 2')
        self.assertNotIn('NK3_NATIVE',text[lost:next_turn])
        self.assertNotIn('NK3_TEST_MOVED player=0',text[lost:next_turn])
        self.assertIn('Making turn thread has been interrupted',text)
        self.assertIn('NK3_TEST_MOVED player=0 day=2',text,'fresh turn could not continue movement')
        movements=re.findall(r'NK3_TEST_MOVED player=0 day=1 hero=(\d+) from=(.*?) to=([^\n]+)',text[:lost])
        self.assertTrue(movements,'turn loss did not occur inside a real movement chain')
        positions=lambda value: list(map(int,re.findall(r'-?\d+',value)))
        records=native_records(run)
        initial=records[0]['heroes'][0]['position']
        offset=[a-b for a,b in zip(positions(movements[0][1]),initial)]
        final=[a-b for a,b in zip(positions(movements[-1][2]),offset)]
        fresh=next(record for record in records if record['day']==2)
        self.assertEqual(fresh['heroes'][0]['position'],final,'next turn reused the pre-movement snapshot')
        self.assertFalse(list((run/'decisions').glob('*/request.json')),'native chain probe called a model')
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        self.assertTrue(json.loads((run/'report.json').read_text())['assignment_matches'])

    def test_actual_turn_loss_cancels_wait_and_next_turn_uses_fresh_native_work(self):
        config=json.loads(Path(os.environ['VCMI_NK3_TURN_LOSS_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-turn-loss-',dir=ROOT/'.build/playtests'))
        print('\nNK3 turn-loss evidence:',output,flush=True)
        probe=ROOT/'tests/fixtures/nk3_strategy_probe.py'
        config.update(players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',references={},
                      controller=[sys.executable,str(probe)],controller_sources=[str(probe)],
                      purpose='integration',case_id='nk3-test-only-turn-loss',headless=True,
                      max_seconds=15,decision_timeout_seconds=65,experience_mode='off')
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(CLI),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
        env=dict(os.environ,NK3_PROBE_MODE='slow');env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(CLI),'run','--run',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+20
                logfile=run/'engine-logs/VCMI_Client_log.txt'
                while child.poll() is None and time.monotonic()<deadline:
                    if logfile.exists():
                        text=logfile.read_text(errors='replace')
                        if 'strategic_exchange_cancelled' in text and 'NK3_NATIVE' in text: break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        text=logfile.read_text(errors='replace')
        self.assertIn('NK3_TEST_END_TURN player=0 day=1',text,'not the test-only probe bundle')
        self.assertIn('strategic_exchange_cancelled',text)
        self.assertNotIn('"accepted" : true',text)
        self.assertIn('Player 0 (red) starting turn, day 2',text)
        cancelled=text.index('strategic_exchange_cancelled')
        next_turn=text.index('Player 0 (red) starting turn, day 2')
        self.assertNotIn('NK3_NATIVE',text[cancelled:next_turn],'old worker executed tasks after losing its turn')
        self.assertIn('NK3_NATIVE',text[next_turn:],'next turn did not execute fresh native work')
        requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
        self.assertTrue(any(r['identity']['day']==1 for r in requests),'probe fired before the model wait')
        self.assertEqual(sum(any(s['question']=='opening' for s in r['signals']) for r in requests),1,'unknown opening request replayed')
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        self.assertTrue(json.loads((run/'report.json').read_text())['assignment_matches'])


if __name__=='__main__': unittest.main()
