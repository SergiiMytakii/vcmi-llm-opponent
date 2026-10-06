"""Town threat forecasts through the native DTO seam; no game launch."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('VCMI_SOURCE', ROOT / '.build/vcmi-nk3'))
LIBRARY = Path(os.environ.get('VCMI_LIBRARY', ROOT / '.build/nk3-mac/bin/libvcmi.dylib'))


@unittest.skipUnless((SOURCE / 'Global.h').exists() and LIBRARY.exists(), 'requires native VCMI headers and library')
class ThreatForecastTest(unittest.TestCase):
    def proof(self, body):
        source = r'''
#include "Global.h"
#include "Forecasts.h"
#include "KnownLandApproach.h"
#include <stdexcept>
using namespace nullkiller3;
JsonNode json(const std::string & text) { JsonParsingSettings p; p.strict=true; p.mode=JsonParsingSettings::JsonFormatMode::JSON; return JsonNode(text.data(),text.size(),p,"threat forecast proof"); }
void require(bool ok) { if(!ok) throw std::runtime_error("threat forecast contract failed"); }
int main() {
''' + body + '\n}'
        with tempfile.TemporaryDirectory() as folder:
            cpp=Path(folder)/'proof.cpp'; binary=Path(folder)/'proof'; cpp.write_text(source)
            cmd=[os.environ.get('CXX','c++'),'-std=c++20','-DVCMI_DLL=1','-DBOOST_ALL_DYN_LINK',
                 '-I'+str(SOURCE),'-I'+str(SOURCE/'lib'),'-I'+str(SOURCE/'include'),'-I'+str(ROOT/'engine/Nullkiller3')]
            boost=next((ROOT/'.build/conan/p').glob('boost*/p/include'),None)
            if boost: cmd.append('-I'+str(boost))
            compiled=subprocess.run(cmd+[str(cpp),str(LIBRARY),'-Wl,-rpath,'+str(LIBRARY.parent),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_stale_unconnected_sighting_does_not_create_an_urgent_defense_front(self):
        self.proof(r'''
auto world=json(R"({"day":11,"enemy_players":[1],"objects":[{"ref":"enemy","kind":"hero","owner":1,"position":[4,5,0],"last_seen_day":9,"army_interval":{"upper":13603}}],"visible_objects":[],"towns":[{"ref":"town","position":[32,33,0],"defense_value":1515}],"heroes":[],"enemy_approaches":[],"forecasts":{"routes":[]}})");
world["forecasts"]["threats"]=forecastThreats(world);
require(world["forecasts"]["threats"][0]["advance_scenario_day"].isNull());
CampaignState campaign;
auto defenses=forecastDefenses(world,campaign);
require(defenses[0]["status"].String()=="no_observed_front");
require(defenses[0]["threats"].Vector().empty());
require(defenses[0]["unconfirmed_threats"].Vector().size()==1);
''')

    def test_visible_enemy_without_open_connection_does_not_demand_defense(self):
        self.proof(r'''
auto world=json(R"({"day":3,"enemy_players":[1],"objects":[{"ref":"enemy","kind":"hero","owner":1,"position":[2,0,0],"last_seen_day":3,"army_interval":{"upper":10000}}],"towns":[{"ref":"town","position":[0,0,0],"defense_value":200}],"heroes":[],"forecasts":{"routes":[]}})");
world["visible_objects"]=world["objects"];
for(const auto status:{"no_complete_visible_land_connection","neutral_encounter_required_on_known_land_connections"}) {
 world["enemy_approaches"]=json(R"([{"source_ref":"enemy","target_ref":"town"}])");
 world["enemy_approaches"][0]["status"].String()=status;
 world["forecasts"]["threats"]=forecastThreats(world);
 require(world["forecasts"]["threats"][0]["advance_scenario_day"].isNull());
 CampaignState campaign;auto result=forecastDefenses(world,campaign);
 require(result[0]["status"].String()=="no_observed_front");
 require(result[0]["opposing_upper_sum"].Integer()==0);
 require(result[0]["unconfirmed_threats"].Vector().size()==1);
}
''')

    def test_open_current_approach_keeps_defense_and_uses_route_length(self):
        self.proof(r'''
auto world=json(R"({"day":3,"enemy_players":[1],"objects":[{"ref":"enemy","kind":"hero","owner":1,"position":[2,0,0],"last_seen_day":3,"army_interval":{"upper":10000}}],"towns":[{"ref":"town","position":[0,0,0],"defense_value":200}],"heroes":[],"enemy_approaches":[{"source_ref":"enemy","target_ref":"town","status":"no_visible_neutral_barrier_on_known_land_connection","known_land_steps":81}],"forecasts":{"routes":[]}})");
world["visible_objects"]=world["objects"];
world["forecasts"]["threats"]=forecastThreats(world);
require(world["forecasts"]["threats"][0]["advance_scenario_day"].Integer()==5);
CampaignState campaign;auto result=forecastDefenses(world,campaign);
require(result[0]["status"].String()=="insufficient_current_force");
require(result[0]["scenario_deadline_day"].Integer()==5);
world["objects"][0]["army_interval"]["upper"]=JsonNode();
world["forecasts"]["threats"]=forecastThreats(world);
require(forecastDefenses(world,campaign)[0]["status"].String()=="unbounded_opposition");
''')

    def test_open_approach_length_excludes_a_shorter_guarded_shortcut(self):
        self.proof(r'''
std::vector<KnownLandTile> tiles(5);
tiles[0].neighbors={1,2};tiles[1].neighbors={3};tiles[1].neutralGuards={"guard"};
tiles[2].neighbors={4};tiles[4].neighbors={3};
auto approach=knownLandApproach(tiles,0,3);
require(approach["status"].String()=="no_visible_neutral_barrier_on_known_land_connection");
require(approach["known_land_steps"].Integer()==3);
''')

if __name__=="__main__": unittest.main()
