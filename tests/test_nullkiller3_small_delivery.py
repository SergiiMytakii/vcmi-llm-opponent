"""Small, explicit compatible hero deliveries execute through the real engine."""
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

from fixtures.fog_maps import scenario
from playtesting.runs import copy_snapshot_file
from test_nullkiller3_campaign import campaign_records
from test_nullkiller3_native import native_records

ROOT=Path(__file__).resolve().parents[1]
DATA=Path('Library/Application Support/vcmi')


def delivery_world(merge='silverPegasus'):
    world=scenario();objects=world['objects.json']
    # Exact army composition from the reported playtest: the recipient has
    # seven occupied slots; only the donor's two silver pegasi can merge.
    hero=next(o for o in objects.values() if o['type']=='hero' and o['options']['owner']=='red')
    hero['options']['army']=[dict(type='core:'+kind,amount=count) for kind,count in
        (('warUnicorn',18),('grandElf',68),('dendroidSoldier',27),('silverPegasus',35),
         ('centaurCaptain',85),('centaur',96),('battleDwarf',77))]
    donor=copy.deepcopy(hero);donor.update(x=5,y=12)
    donor['options'].update(type='orrin',army=[dict(type='core:'+kind,amount=count) for kind,count in
        [('pegasus',5),('gremlin',16)]+([(merge,2)] if merge else [])])
    objects['small_donor']=donor
    world['header.json']['players']['red']['heroes']['small_donor']={'type':'orrin'}
    for key in [k for k,o in objects.items() if o['type'] in ('monster','resource','mine')]:del objects[key]
    town=next(o for o in objects.values() if o['type']=='town' and o['options']['owner']=='red')
    town['options']['buildings']['allOf']=['fort','townHall']
    town['options']['buildings']['noneOf'] += [f'{prefix}{level}' for prefix in ('dwellingLvl','dwellingUpLvl')
                                              for level in range(1,8)]
    return world


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('VCMI_NK3_STRATEGY_CONFIG'),
                     'requires an isolated native build and licensed profile')
class SmallHeroDeliveryTest(unittest.TestCase):
    def test_explicit_small_merge_completes_without_discarding_incompatible_stacks(self):
        self.run_delivery('silverPegasus',133496)

    def test_explicit_delivery_below_the_autonomous_500_threshold_completes(self):
        self.run_delivery('centaur',132650)

    def test_disjoint_donor_is_rejected_without_discarding_units(self):
        self.run_delivery(None,132436)

    def run_delivery(self,merge,expected):
        config=json.loads(Path(os.environ['VCMI_NK3_STRATEGY_CONFIG']).read_text())
        output=Path(tempfile.mkdtemp(prefix='nk3-small-delivery-',dir=ROOT/'.build/playtests'))
        print('\nSmall delivery evidence:',output,flush=True)
        fixture=output/'fixture';shutil.copytree(config['profile_template'],fixture,copy_function=copy_snapshot_file)
        with zipfile.ZipFile(fixture/DATA/'Maps/SmallDelivery.vmap','w') as archive:
            for name,value in delivery_world(merge).items():archive.writestr(name,json.dumps(value))
        probe=ROOT/'tests/fixtures/nk3_strategy_probe.py'
        config.update(profile_template=str(fixture),map_resource='Maps/SmallDelivery.vmap',
            players={'red':'Nullkiller3','blue':'EmptyAI'},nk3_mode='model',references={},
            controller=[sys.executable,str(probe)],controller_sources=[str(probe)],
            purpose='integration',case_id='nk3-small-delivery',headless=True,max_seconds=12,
            decision_timeout_seconds=2,experience_mode='off')
        config.pop('save_resource',None)
        path=output/'config.json';path.write_text(json.dumps(config));run=output/'game'
        subprocess.run([sys.executable,str(ROOT/'scripts/playtest.py'),'prepare','--config',str(path),'--out',str(run)],
                       check=True,capture_output=True)
        env=dict(os.environ,NK3_PROBE_MODE='small_hero_delivery' if merge else 'disjoint_hero_delivery')
        env.pop('VCMI_NK3_SEED_CAMPAIGN',None)
        with (output/'driver.log').open('w') as log:
            child=subprocess.Popen([sys.executable,str(ROOT/'scripts/playtest.py'),'run','--run',str(run)],
                                   env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+17
                while child.poll() is None and time.monotonic()<deadline:
                    records=campaign_records(run)
                    if not merge and any(r['day']>=2 for r in native_records(run)):break
                    if any(r['day']>=2 or r['statuses'].get('small-delivery',{}).get('state')=='completed'
                           for r in records):break
                    time.sleep(.03)
            finally:
                (run/'STOP').touch(exist_ok=True);child.wait(timeout=15)
        launch=json.loads((run/'launch.json').read_text())
        self.assertTrue(launch['cleanup_complete']);self.assertTrue(launch['protected_files_unchanged'])
        requests=[json.loads(p.read_text()) for p in (run/'decisions').glob('*/request.json')]
        self.assertTrue(requests,'no actual strategic request')
        opening=min(requests,key=lambda r:int(r['request_id'].rsplit(':',1)[1]))
        self.assertEqual(max(h['army_value'] for h in opening['observation']['heroes']),132436)
        records=campaign_records(run)
        completed=[r for r in records if r['statuses'].get('small-delivery',{}).get('state')=='completed']
        if not merge:
            trace=native_records(run);self.assertTrue(trace,'no native own-army observations')
            self.assertFalse(completed,'empty exchange falsely completed the goal')
            self.assertTrue(all(h['army'] in (132436,3146) for r in trace for h in r['heroes']),
                            'incompatible troops were discarded or moved')
            self.assertFalse(any(r['confirmed_deliveries'] for r in records),'empty exchange produced a receipt')
            text=(run/'engine-logs/VCMI_Client_log.txt').read_text(errors='replace')
            outcomes=[json.JSONDecoder().raw_decode(text[m.end():].lstrip())[0]
                      for m in re.finditer('NK3_STRATEGY ',text)]
            self.assertTrue(any(not r['accepted'] and r['fallback_reason'].startswith(
                'reinforcement_source_has_no_compatible_stack:') for r in outcomes),
                'incompatible source intent was not rejected at the native boundary')
            return
        self.assertTrue(completed,'explicit small compatible handoff did not execute: '+str(run))
        receipt=next(d for d in completed[0]['confirmed_deliveries'] if d['goal']['id']=='small-delivery')
        self.assertEqual(receipt['recipient_after'],expected)
        self.assertEqual(receipt['source_after'],3146)
        self.assertEqual(receipt['day'],1)
        donor=next(h for h in completed[0]['heroes'] if h['ref']==receipt['source_ref'])
        self.assertEqual(donor['army_value'],3146,'unrelated donor units were lost')
        (output/'receipt.json').write_text(json.dumps(receipt,indent=2))


if __name__=='__main__':unittest.main()
