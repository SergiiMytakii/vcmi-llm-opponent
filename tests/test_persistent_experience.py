"""Knowledge survives replacement of the controller checkout."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class PersistentExperienceTest(unittest.TestCase):
    def test_two_controller_builds_share_knowledge_outside_build_directories(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();home=root/'home';home.mkdir()
            env={**os.environ,'HOME':str(home),'APPDATA':str(home/'AppData/Roaming'),'XDG_DATA_HOME':str(home/'data')}
            env.pop('VCMI_EXPERIENCE_DB',None)
            paths=[]
            for name in ('build-one','build-two'):
                build=root/name
                shutil.copytree(ROOT/'controller',build/'controller',ignore=shutil.ignore_patterns('__pycache__'))
                code="from experience import DEFAULT_DB,Experience;import json; s=Experience(DEFAULT_DB); s.db.execute(\"INSERT OR IGNORE INTO lessons(id,rule,conditions) VALUES('persisted','Preserved rule','[]')\");s.db.commit();print(json.dumps({'path':str(DEFAULT_DB),'count':s.db.execute('SELECT count(*) FROM lessons').fetchone()[0]}));s.close()"
                result=subprocess.run([sys.executable,'-c',code],cwd=build/'controller',env=env,capture_output=True,text=True,check=True)
                data=json.loads(result.stdout);paths.append(data['path'])
                self.assertFalse(Path(data['path']).is_relative_to(build))
                self.assertEqual(data['count'],1)
                shutil.rmtree(build)
            self.assertEqual(paths[0],paths[1])
            self.assertTrue(Path(paths[0]).is_file())

if __name__=='__main__':unittest.main()
