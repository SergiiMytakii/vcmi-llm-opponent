"""Artifact pickup proof at the native site-receipt seam; never builds or launches a game."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('VCMI_TEST_SOURCE', ROOT / '.build/vcmi-nk3'))
LIBRARY = Path(os.environ.get('VCMI_TEST_LIBRARY', ROOT / '.build/nk3-mac/bin/libvcmi.dylib'))

@unittest.skipUnless((SOURCE / 'Global.h').exists() and LIBRARY.exists(), 'requires existing native headers/library')
class ArtifactVisitReceiptsTest(unittest.TestCase):
    def proof(self, body):
        code = r'''
#include "Global.h"
#include "KeymasterAccess.h"
#include "NativePersistence.h"
#include <stdexcept>
using namespace nullkiller3;
JsonNode json(const std::string & t) {JsonParsingSettings p;p.strict=true;p.mode=JsonParsingSettings::JsonFormatMode::JSON;return JsonNode(t.data(),t.size(),p,"artifact receipt proof");}
void require(bool ok,const char * why) {if(!ok) throw std::runtime_error(why);}
int main(){
''' + body + '\n}'
        with tempfile.TemporaryDirectory() as folder:
            cpp = Path(folder) / 'proof.cpp'
            executable = Path(folder) / 'proof'
            cpp.write_text(code)
            includes = [SOURCE, SOURCE / 'lib', SOURCE / 'include', ROOT / 'engine/Nullkiller3']
            boost = os.environ.get('VCMI_TEST_BOOST_INCLUDE')
            if boost:
                includes.append(Path(boost))
            else:
                includes.extend((ROOT / '.build/conan/p').glob('boost*/p/include'))
            command = [os.environ.get('CXX', 'c++'), '-std=c++20', '-DVCMI_DLL=1', '-DBOOST_ALL_DYN_LINK',
                       *[f'-I{path}' for path in includes], str(cpp), str(LIBRARY),
                       '-Wl,-rpath,' + str(LIBRARY.parent), '-o', str(executable)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_disappeared_artifact_without_own_pickup_never_confirms_visit(self):
        self.proof(r'''
auto facts=json(R"({"kind":"artifact","actor_owned":true,"target_visible":true,"target_present":false,"visited_by_player":false})");
require(!keySiteVisitConfirmed(facts),"disappeared artifact falsely confirmed pickup");
''')

    def test_exact_acknowledged_pickup_survives_pending_checkpoint(self):
        self.proof(r'''
auto event=json(R"({"kind":"artifact","day":3,"target_id":100,"position":[2,0,0],"artifact_instance_id":900,
"goal":{"id":"pickup","kind":"visit_site","actor_ref":"hero","target_ref":"item","deadline_day":5,"complete_when":{"kind":"site_visited","value":0}},
"inventory_before":[10,20],"visit_started":false,"acknowledged":false})");
require(validArtifactVisitEvidence(event),"valid pickup baseline rejected");
require(!artifactVisitConfirmed(event),"pending start invented callback");
JsonNode saved;saved["object_ids"]=json(R"({"100":0,"101":1})");
auto task=json(R"({"version":1,"action":{"kind":"visit","goal_id":"pickup","native_goal_type":1},
"before":{"day":3,"player":0,"resources":[0,0,0,0,0,0,0],"heroes":[{"ref":"hero","position":[0,0,0],"army_value":500}],"towns":[]}})");
task["action"]["artifact_visit"]=event;saved["pending_native_task"]=task;
auto loaded=restoreNativeNamespace(saved);
require(loaded["pending_native_task"]==task,"checkpoint lost exact pending pickup identity");
require(!artifactVisitConfirmed(loaded["pending_native_task"]["action"]["artifact_visit"]),"loaded start invented acknowledgment");
event["visit_started"].Bool()=true;event["acknowledged"].Bool()=true;
event["inventory_after"]=json(R"([10,20,901])");
require(!artifactVisitConfirmed(event),"different instance of same type fulfilled pickup");
event["inventory_after"]=json(R"([10,20,900])");require(artifactVisitConfirmed(event),"exact instance pickup not confirmed");
task["action"]["artifact_visit"]=event;saved["pending_native_task"]=task;
loaded=restoreNativeNamespace(saved);
require(artifactVisitConfirmed(loaded["pending_native_task"]["action"]["artifact_visit"]),"checkpoint lost acknowledged own pickup");
recordStrategicSiteVisit(saved,event);loaded=restoreNativeNamespace(saved);
require(loaded["site_receipts"]["pickup"]["goal"]==event["goal"],"receipt changed target/actor snapshot");
require(artifactVisitConfirmed(loaded["site_receipts"]["pickup"]["artifact_visit"]),"receipt lost inventory proof");
auto facts=event;facts["actor_owned"].Bool()=false;
require(!keySiteVisitConfirmed(facts),"nonowned actor completed pickup");
facts["actor_owned"].Bool()=true;require(keySiteVisitConfirmed(facts),"own exact callback pickup rejected");
event["inventory_before"]=json(R"([10,20,900])");
require(!artifactVisitConfirmed(event),"preexisting artifact fulfilled unrelated pickup");
''')

    def test_artifact_admission_requires_visible_available_site(self):
        self.proof(r'''
auto object=json(R"({"kind":"artifact","visible":true,"visited":false})");
require(strategicSiteAvailable(object),"ordinary visible artifact omitted from existing sites");
object["visible"].Bool()=false;require(!strategicSiteAvailable(object),"hidden artifact admitted");
object["visible"].Bool()=true;object["visited"].Bool()=true;
require(!strategicSiteAvailable(object),"already consumed artifact admitted");
''')

if __name__ == '__main__':
    unittest.main()
