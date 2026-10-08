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
#include "StrategicDecision.h"
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
            compiled=subprocess.run(cmd+[str(cpp),str(ROOT/'engine/Nullkiller3/Forecasts.cpp'),str(ROOT/'engine/Nullkiller3/CampaignState.cpp'),str(LIBRARY),'-Wl,-rpath,'+str(LIBRARY.parent),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_closing_approach_changes_defense_question_without_daily_repetition(self):
        self.proof(r'''
auto defense=json(R"({"town_ref":"town","status":"insufficient_current_force","scenario_deadline_day":12,"threats":[{"source_ref":"enemy","army_interval":{"lower":10000,"upper":15000},"movement_scenario":{"turns":3}}]})");
const auto distant=defenseSignal(defense,true);
defense["scenario_deadline_day"].Integer()=13;
require(defenseSignal(defense,true).facts==distant.facts);
defense["threats"][0]["movement_scenario"]["turns"].Integer()=1;
require(defenseSignal(defense,true).facts!=distant.facts);
''')

    def test_unflaggable_monsters_screen_a_visible_enemy_without_forcing_a_hold(self):
        self.proof(r'''
for(const auto owner:{PlayerColor::UNFLAGGABLE,PlayerColor::NEUTRAL}) {
 std::vector<KnownLandTile> land(3);
 land[0].neighbors={1};land[1].neighbors={0,2};land[2].neighbors={1};
 if(isNeutralMonsterGuard(Obj::MONSTER,owner)) land[1].neutralGuards={"visible-monster"};
 auto approach=knownLandApproach(land,0,2);
 require(approach["status"].String()=="neutral_encounter_required_on_known_land_connections");
 require(approach["example_guard_refs"][0].String()=="visible-monster");
 approach["source_ref"].String()="enemy";approach["target_ref"].String()="town";
 auto world=json(R"({"day":1,"enemy_players":[1],"objects":[{"ref":"enemy","kind":"hero","owner":1,"position":[2,0,0],"last_seen_day":1,"army_interval":{"upper":6400}}],"towns":[{"ref":"town","position":[0,0,0],"defense_value":5400}],"heroes":[],"forecasts":{"routes":[]}})");
 world["visible_objects"]=world["objects"];world["enemy_approaches"].Vector().push_back(approach);
 world["forecasts"]["threats"]=forecastThreats(world);
 require(world["forecasts"]["threats"][0]["assessment"].String()=="guarded_approach");
 require(world["forecasts"]["threats"][0]["advance_scenario_day"].isNull());
 CampaignState campaign;auto defense=forecastDefenses(world,campaign);
 require(defense[0]["status"].String()=="no_observed_front");
 require(defense[0]["opposing_upper_sum"].Integer()==0);
}
require(!isNeutralMonsterGuard(Obj::MONSTER,PlayerColor(1)));
require(!isNeutralMonsterGuard(Obj::MINE,PlayerColor::UNFLAGGABLE));
''')

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

    def test_distant_open_approach_is_not_an_urgent_defense_deadline(self):
        self.proof(r'''
auto world=json(R"({"day":3,"enemy_players":[1],"objects":[{"ref":"enemy","kind":"hero","owner":1,"position":[2,0,0],"last_seen_day":3,"army_interval":{"upper":10000}}],"towns":[{"ref":"town","position":[0,0,0],"defense_value":200}],"heroes":[],"enemy_approaches":[{"source_ref":"enemy","target_ref":"town","status":"no_visible_neutral_barrier_on_known_land_connection","known_land_steps":81}],"forecasts":{"routes":[]}})");
world["visible_objects"]=world["objects"];
world["forecasts"]["threats"]=forecastThreats(world);
require(world["forecasts"]["threats"][0]["assessment"].String()=="observed_open_approach");
require(world["forecasts"]["threats"][0]["advance_scenario_day"].isNull());
require(world["forecasts"]["threats"][0]["earliest_possible_day"].isNull());
CampaignState campaign;auto result=forecastDefenses(world,campaign);
require(result[0]["status"].String()=="observed_threat_timing_unknown");
require(result[0]["scenario_deadline_day"].isNull());
require(result[0]["threats"].Vector().size()==1);
require(result[0]["opposing_upper_sum"].Integer()==10000);
''')

    def test_adjacent_legal_enemy_approach_keeps_local_defense(self):
        self.proof(r'''
auto world=json(R"({"day":3,"enemy_players":[1],"objects":[{"ref":"enemy","kind":"hero","owner":1,"position":[1,0,0],"last_seen_day":3,"army_interval":{"upper":10000}}],"towns":[{"ref":"town","position":[0,0,0],"defense_value":200}],"heroes":[],"enemy_approaches":[{"source_ref":"enemy","target_ref":"town","status":"no_visible_neutral_barrier_on_known_land_connection","known_land_steps":1}],"forecasts":{"routes":[]}})");
world["visible_objects"]=world["objects"];world["forecasts"]["threats"]=forecastThreats(world);
require(world["forecasts"]["threats"][0]["advance_scenario_day"].Integer()==3);
require(world["forecasts"]["threats"][0]["earliest_possible_day"].isNull());
CampaignState campaign;auto result=forecastDefenses(world,campaign);
require(result[0]["status"].String()=="insufficient_current_force");
require(result[0]["scenario_deadline_day"].Integer()==3);
world["objects"][0]["army_interval"]["upper"]=JsonNode();
world["forecasts"]["threats"]=forecastThreats(world);
require(forecastDefenses(world,campaign)[0]["status"].String()=="unbounded_opposition");
''')

    def test_direct_approach_days_compare_with_own_return_without_inventing_an_eta(self):
        self.proof(r'''
auto world=json(R"({"day":10,"enemy_players":[1],"objects":[{"ref":"enemy","kind":"hero","owner":1,"position":[30,0,0],"last_seen_day":10,"army_interval":{"upper":10000}}],"towns":[{"ref":"town","position":[0,0,0],"defense_value":200}],"heroes":[{"ref":"main","army_value":20000}],"enemy_approaches":[{"source_ref":"enemy","target_ref":"town","status":"no_visible_neutral_barrier_on_known_land_connection","known_land_steps":30,"movement_scenario":{"turns":2,"daily_points":2000}}],"forecasts":{"routes":[{"target_ref":"town","own_arrivals":[{"hero_ref":"main","day":12,"army_value":20000,"army_loss_estimate":0}]}]}})");
world["visible_objects"]=world["objects"];world["forecasts"]["threats"]=forecastThreats(world);
const auto & threat=world["forecasts"]["threats"][0];
require(threat["advance_scenario_day"].Integer()==11);
require(threat["earliest_possible_day"].isNull()); // Conditional full-turn scenario, not a guaranteed ETA.
CampaignState campaign;auto defense=forecastDefenses(world,campaign);
require(defense[0]["status"].String()=="insufficient_current_force");
require(defense[0]["own_arrivals"].Vector().empty()); // Day12 is too late for the day11 scenario.
world["forecasts"]["routes"][0]["own_arrivals"][0]["day"].Integer()=11;
require(forecastDefenses(world,campaign)[0]["status"].String()=="conditional_force_available");
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

    def test_visible_movement_costs_produce_one_two_three_turn_scenarios(self):
        self.proof(r'''
std::vector<KnownLandTile> land(7);
for(size_t i=0;i<6;++i) { land[i].neighbors={i+1};land[i].movementCosts={100}; }
require(knownLandApproach(land,0,2,200)["movement_scenario"]["turns"].Integer()==1);
require(knownLandApproach(land,0,4,200)["movement_scenario"]["turns"].Integer()==2);
require(knownLandApproach(land,0,6,200)["movement_scenario"]["turns"].Integer()==3);
for(size_t i=0;i<6;++i) land[i].movementCosts={50};
require(knownLandApproach(land,0,6,200)["movement_scenario"]["turns"].Integer()==2);
land[3].neutralGuards={"screen"};
require(knownLandApproach(land,0,6,200)["movement_scenario"].isNull());
land[3].neutralGuards.clear();land[3].movementCosts.clear();
require(knownLandApproach(land,0,6,200)["movement_scenario"].isNull());
''')

if __name__=="__main__": unittest.main()
