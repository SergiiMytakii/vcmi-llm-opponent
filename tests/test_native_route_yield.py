"""Opt-in regression on a private saved game whose main army is blocked by an idle helper.

VCMI_NATIVE_ROUTE_YIELD_CONFIG supplies the compatible engine, copied profile/save,
and ordinary tester limits. This never launches or changes the user's live game.
"""
import json
import shutil
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NATIVE_ROUTE_YIELD_CONFIG'),
                     'requires a private compatible obstructed save fixture')
class NativeRouteYieldTest(unittest.TestCase):
    def test_unassigned_helper_yields_and_main_gets_actual_route_without_phantom_exploration(self):
        config_path=Path(os.environ['VCMI_NATIVE_ROUTE_YIELD_CONFIG']).resolve()
        config=json.loads(config_path.read_text())
        for key in ('engine','profile_template'):
            config[key]=str((config_path.parent/config[key]).resolve())
        with tempfile.TemporaryDirectory(prefix='route-yield-',dir=ROOT/'.build') as folder:
            folder=Path(folder);controller=folder/'retain.py'
            shutil.copy2(ROOT/'tests/fixtures/strategic_intent.py',folder/'strategic_intent.py')
            controller.write_text("""import json,sys,os
from pathlib import Path
from strategic_intent import with_intent
r=json.load(sys.stdin)
run=Path(os.environ['VCMI_PLAYTEST_RUN']);first=run/'probe-first-day'
if not first.exists():first.write_text(str(r['observation']['day']))
if r['observation']['day']>int(first.read_text()):(run/'STOP').touch()
print(json.dumps(with_intent(r,dict(protocol=2,request_id=r['request_id'],identity=r['identity'],decision='retain',reason='Preserve saved plan for isolated transport proof',evidence_refs=['observation:offensive_preparation'],victory_method='Transport proof only',assignments=r['observation']['strategy_assignments'],alternatives=[dict(approach='economy',benefit='Preserve plan',cost='Waiting',uncertainty='Route under test'),dict(approach='defense',benefit='Compare protection',cost='Diversion',uncertainty='Unknown opponent')],reconsider_when=[dict(goal_id=r['campaign']['goals'][0]['id'],kind='deadline_missed')],plan=None,usage=dict(input_tokens=0,output_tokens=0,known=True)))))
""")
            config.update(controller=[sys.executable,str(controller)],controller_sources=[str(controller)],
                          engine_sources=[],references={},purpose='integration',headless=True,
                          experience_mode='off',strategy_guide={'mode':'off'},max_seconds=25,
                          decision_timeout_seconds=10)
            path=folder/'config.json';path.write_text(json.dumps(config));run=folder/'run'
            subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(path),'--out',str(run)],check=True,capture_output=True)
            result=subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'run','--run',str(run)],capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stderr+result.stdout)
            launch=json.loads((run/'launch.json').read_text())
            self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
            observations=[json.loads(p.read_text())['observation'] for p in run.glob('decisions/*/request.json')]
            self.assertTrue(observations,'fixture must reach actual strategic caller')
            first=min(observations,key=lambda o:o['day']);main=first['main_army_idle']['hero_ref']
            towns={t['ref'] for t in first['towns']}
            def main_routes(o):
                return [a for q in o['forecasts']['routes'] if q['target_ref'] in towns
                        for a in q['own_arrivals'] if a['hero_ref']==main and a['army_loss_estimate']==0]
            self.assertFalse(main_routes(first),'fixture must begin with the diagnosed route obstruction')
            self.assertTrue(any(main_routes(o) for o in observations if o['day']<=first['day']+1),
                            'main must receive an actual new native route after the physical yield')
            log=(run/'engine-logs/VCMI_Client_log.txt').read_text(errors='replace')
            self.assertIn('NK3_ROUTE_REPAIR',log)
            self.assertFalse(any('NK3AI' in line and 'Performing task' in line and ' for 0 tiles' in line
                                 for line in log.splitlines()))
