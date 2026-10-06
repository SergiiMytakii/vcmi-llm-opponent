"""Real initial observations must not infer gate pairing from global map data."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

from fixtures.fog_maps import scenario

ROOT = Path(__file__).resolve().parents[1]
DATA = Path('Library/Application Support/vcmi')


def gate_world(hidden_pair=False):
    world = scenario()
    world['header.json']['mapLevels']['underground'] = dict(width=36, height=24, index=1)
    world['underground_terrain.json'] = copy.deepcopy(world['surface_terrain.json'])
    objects = world['objects.json']
    hero = copy.deepcopy(next(o for o in objects.values() if o['type']=='hero' and o['options']['owner']=='red'))
    hero['l']=1
    hero['options']['type']='orrin'
    objects['underground_hero']=hero
    world['header.json']['players']['red']['heroes']['underground_hero']={'type':'orrin'}
    # The sprite is a licensed resource placeholder; headless gate behavior and
    # visit geometry come from the subterraneanGate handler and one active tile.
    for level in (0,1):
        objects['visible_gate_'+str(level)]=dict(type='subterraneanGate',subtype='object',x=8,y=11,l=level,
            template=dict(animation='AVTGOLD0',editorAnimation='AVTGOLD0',mask=['A'],
                          visitableFrom=['+++','+-+','+++']),options={})
        if hidden_pair:
            distant=copy.deepcopy(objects['visible_gate_'+str(level)])
            distant.update(x=33,y=22)
            objects['hidden_gate_'+str(level)]=distant
    return world


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires isolated native build and licensed private profile')
class KnownPassageVisibilityTest(unittest.TestCase):
    def test_visible_untraversed_pair_has_no_cross_level_routes_and_hidden_pair_is_irrelevant(self):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-known-passages-',dir=ROOT/'.build/playtests'))
        print('\nKnown passage evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture)
        probe=ROOT/'tests/fixtures/nk3_strategy_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/KnownPassages.vmap',
            players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',references={},
            controller=[sys.executable,str(probe)],controller_sources=[str(probe)],
            purpose='integration',case_id='nk3-known-passages',headless=True,max_seconds=20,
            decision_timeout_seconds=2,experience_mode='off')
        config.pop('save_resource',None)
        observations=[]
        for name,hidden in (('base',False),('hidden',True)):
            with zipfile.ZipFile(fixture/DATA/'Maps/KnownPassages.vmap','w') as archive:
                for filename,value in gate_world(hidden).items():archive.writestr(filename,json.dumps(value))
            path=output/(name+'.json');path.write_text(json.dumps(config));run=output/name
            subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(path),'--out',str(run)],
                           check=True,capture_output=True)
            env=dict(os.environ,NK3_PROBE_MODE='valid');env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
            with (output/(name+'-driver.log')).open('w') as log:
                child=subprocess.Popen([sys.executable,str(ROOT/'scripts/playtest.py'),'run','--run',str(run)],
                                       env=env,stdout=log,stderr=subprocess.STDOUT)
                try:
                    deadline=time.monotonic()+25
                    while child.poll() is None and time.monotonic()<deadline:
                        if list((run/'decisions').glob('*/request.json')):break
                        time.sleep(.03)
                finally:
                    (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
            paths=list((run/'decisions').glob('*/request.json'))
            self.assertTrue(paths,'no actual strategic request: '+str(run))
            request=min((json.loads(p.read_text()) for p in paths),key=lambda r:int(r['request_id'].rsplit(':',1)[1]))
            own=request['observation'];heroes={h['ref']:h for h in own['heroes']}
            gates=[o for o in own['objects'] if o.get('kind')=='subterranean_gate' and o.get('visible')]
            self.assertEqual({o['position'][2] for o in gates},{0,1})
            self.assertEqual(own['observed_passages'],[])
            for target in own['frontier_options']+own['objects']:
                for arrival in target.get('own_arrivals',[]):
                    self.assertEqual(heroes[arrival['hero_ref']]['position'][2],target['position'][2],str(target))
            positions={o['ref']:o['position'] for o in own['objects']}
            positions.update({h['ref']:h['position'] for h in own['heroes']})
            for route in own['forecasts']['routes']:
                for arrival in route['own_arrivals']:
                    self.assertEqual(heroes[arrival['hero_ref']]['position'][2],positions[route['target_ref']][2])
            # Fresh-map random resource bonuses are independent of gate
            # knowledge. Compare the full movement inputs and offered routes.
            observations.append({key:own[key] for key in
                ('heroes','objects','frontier_options','observed_passages','movement_support')})
            observations[-1]['routes']=own['forecasts']['routes']
            launch=json.loads((run/'launch.json').read_text())
            self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        self.assertEqual(observations[0],observations[1])
        (output/'comparison.json').write_text(json.dumps(observations,indent=2))


if __name__=='__main__':unittest.main()
