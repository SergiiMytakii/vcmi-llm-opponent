"""Real Nullkiller3 native decisions across worlds with equal permitted observations."""
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

from fixtures.fog_maps import variants

ROOT = Path(__file__).resolve().parents[1]
DATA = Path('Library/Application Support/vcmi')


def native_records(run):
    path = run / 'engine-logs/VCMI_Client_log.txt'
    if not path.exists():
        return []
    result = []
    data = path.read_text(errors='replace')
    decoder = json.JSONDecoder()
    for match in re.finditer(r'NK3_NATIVE ', data):
        try:
            start = match.end()
            while start < len(data) and data[start].isspace(): start += 1
            record, _ = decoder.raw_decode(data, start)
            result.append(record)
        except ValueError:
            continue

    return result


def first_movement(records):
    if not records:
        return None
    start = {h['name']:h for h in records[0]['heroes']}
    for index, record in enumerate(records[1:], 1):
        if any(h['name'] in start and h['position'] != start[h['name']]['position']
               for h in record['heroes']):
            return index
    return None


@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('VCMI_NK3_NATIVE_CONFIG'),
                     'requires a separate Nullkiller3 build and private native fixture')
class Nullkiller3NativeTest(unittest.TestCase):
    def test_hidden_world_preserves_commands_but_visible_neutral_counts_change_evidence(self):
        source = Path(os.environ['VCMI_NK3_NATIVE_CONFIG']).resolve()
        config = json.loads(source.read_text())
        output = Path(tempfile.mkdtemp(prefix='nk3-visibility-', dir=ROOT / '.build/playtests'))
        print('\nNullkiller3 visibility evidence:', output, flush=True)
        fixture = output / 'fixture'
        shutil.copytree(config['profile_template'], fixture)
        config.update(profile_template=str(fixture), map_resource='Maps/NK3Visibility.vmap',
                      players={'red': 'Nullkiller3', 'blue': 'EmptyAI'}, nk3_mode='native', seed=42,
                      purpose='integration', case_id='nk3-visibility', references={},
                      headless=True, experience_mode='off', max_seconds=25)
        config.pop('save_resource', None)
        results = {}
        worlds = variants()
        # Keep the visible army too large to fight during the comparison. A
        # resolved battle reveals new permitted information and actual losses,
        # so worlds with different exact counts are no longer equivalent then.
        for name, world in worlds.items():
            guard = next(v for v in world['objects.json'].values()
                         if v['type'] == 'monster' and v['x'] == 9)
            guard['options']['amount'] = {'same_category':199, 'different_category':251}.get(name, 150)
        for name, world in worlds.items():
            with self.subTest(variant=name):
                with zipfile.ZipFile(fixture / DATA / 'Maps/NK3Visibility.vmap', 'w') as archive:
                    for filename, value in world.items():
                        archive.writestr(filename, json.dumps(value))
                path = output / (name + '.json')
                path.write_text(json.dumps(config))
                run = output / name
                subprocess.run([sys.executable, str(ROOT / 'scripts/playtest.py'), 'prepare',
                                '--config', str(path), '--out', str(run)], check=True,
                               capture_output=True)
                with (output / (name + '-driver.log')).open('w') as log:
                    process = subprocess.Popen([sys.executable, str(ROOT / 'scripts/playtest.py'),
                                                'run', '--run', str(run)], env=dict(os.environ, VCMI_AI_OPEN_MAP='0'),
                                                stdout=log, stderr=subprocess.STDOUT)
                    try:
                        deadline = time.monotonic() + 30
                        while process.poll() is None and time.monotonic() < deadline:
                            records = native_records(run)
                            if first_movement(records) is not None:
                                break
                            time.sleep(.05)
                    finally:
                        (run / 'STOP').touch(exist_ok=True)
                        process.wait(timeout=15)
                launch = json.loads((run / 'launch.json').read_text())
                self.assertTrue(launch['cleanup_complete'], str(run))
                self.assertTrue(launch['protected_files_unchanged'], str(run))
                report = json.loads((run / 'report.json').read_text())
                self.assertTrue(report['assignment_matches'], str(run))
                records = native_records(run)
                boundary = first_movement(records)
                self.assertIsNotNone(boundary, 'no confirmed native hero movement: ' + str(run))
                before, after = records[0]['heroes'], records[boundary]['heroes']
                original = {h['name']:h for h in before}
                self.assertTrue(all(h['army'] >= original[h['name']]['army']
                                    for h in after if h['name'] in original),
                                'fixture suffered combat losses before comparison')
                self.assertTrue(any(r['tasks'] for r in records[:boundary+1]), 'no native commands')
                self.assertTrue(any(r['pass'] == -1 for r in records[:boundary+1]), 'no native execution')
                self.assertFalse(list((run / 'decisions').iterdir()), 'native-only mode called a controller')
                results[name] = records[:boundary+1]
        (output / 'native-comparison.json').write_text(json.dumps(results, indent=2))
        self.assertEqual(len(results), len(variants()), 'one or more native runs failed: ' + str(output))
        visible_guard=next(o for o in results['base'][0]['visible_objects'] if o['type']==54 and o['position'][0]==9)
        interval=visible_guard['army_interval']
        # The fixture has 150 pikemen at 89 troop value each, now exact.
        self.assertEqual(interval['status'],'exact_observed')
        self.assertEqual(interval['stacks'],[{'creature_id':0,'count':150}])
        self.assertEqual(interval['lower'],13350)
        self.assertEqual(interval['upper'],13350)
        for name in ('hidden', 'hidden_insert', 'hidden_remove'):
            self.assertEqual(results[name], results['base'], str(output) + ': ' + name)
        # Exact visible counts differ even within the same UI category.
        self.assertNotEqual(results['same_category'], results['base'], str(output))
        self.assertNotEqual(results['different_category'], results['base'], str(output))


if __name__ == '__main__':
    unittest.main()
