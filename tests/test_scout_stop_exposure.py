"""Player-visible scout stop exposure through the native DTO seam; no game launch."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('VCMI_SOURCE', ROOT / '.build/vcmi-nk3'))
LIBRARY = Path(os.environ.get('VCMI_LIBRARY', ROOT / '.build/nk3-mac/bin/libvcmi.dylib'))


@unittest.skipUnless((SOURCE / 'Global.h').exists() and LIBRARY.exists(), 'requires native VCMI headers and library')
class ScoutStopExposureTest(unittest.TestCase):
    def proof(self, body):
        source = r'''
#include "Global.h"
#include "KnownLandApproach.h"
#include "StrategicDecision.h"
#include <stdexcept>
using namespace nullkiller3;
JsonNode json(const std::string & text) { JsonParsingSettings p; p.strict=true; p.mode=JsonParsingSettings::JsonFormatMode::JSON; return JsonNode(text.data(),text.size(),p,"scout exposure proof"); }
void require(bool ok) { if(!ok) throw std::runtime_error("scout exposure contract failed"); }
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

    def test_helper_route_progress_does_not_repeat_the_same_safety_question(self):
        self.proof(r'''
auto review=json(R"({"hero_ref":"helper","reason":"automatic_helper_approaches_stronger_visible_enemy","status":"conditional_unchanged_route","origin":[0,0,0],"stop_positions":[[3,0,0]],"target_position":[10,0,0],"own_strength":107,"visible_threats":[{"enemy_ref":"enemy","position":[50,0,0],"army_interval":{"lower":10000,"upper":15000},"tile_distance":47,"known_land_approach":{"status":"no_visible_neutral_barrier_on_known_land_connection","known_land_steps":47,"movement_scenario":{"status":"conditional_direct_land_approach","turns":3,"daily_points":2000}}}]})");
RequestArbiter arbiter;arbiter.beginTurn(1,{280000,120000,40000});
auto first=arbiter.consider({automaticSafetySignal(review,1,true)});
require(first.request);arbiter.dispatched(first);arbiter.finished(22000,73532);
review["origin"]=json("[1,0,0]");review["stop_positions"]=json("[[4,0,0]]");
review["visible_threats"][0]["tile_distance"].Integer()=46;
review["visible_threats"][0]["known_land_approach"]["known_land_steps"].Integer()=46;
require(!arbiter.consider({automaticSafetySignal(review,1,true)}).request);
RequestArbiter restored(arbiter.save());
restored.beginTurn(1,{280000,120000,40000});
require(!restored.consider({automaticSafetySignal(review,1,true)}).request);
''')

    def test_helper_safety_reconsiders_new_threats_and_keeps_strict_unknown_and_passage_reviews(self):
        self.proof(r'''
auto review=json(R"({"hero_ref":"helper","reason":"automatic_helper_approaches_stronger_visible_enemy","status":"conditional_unchanged_route","origin":[0,0,0],"stop_positions":[[3,0,0]],"target_position":[10,0,0],"own_strength":107,"visible_threats":[{"enemy_ref":"enemy","position":[50,0,0],"army_interval":{"lower":10000,"upper":15000},"tile_distance":47,"known_land_approach":{"status":"no_visible_neutral_barrier_on_known_land_connection","known_land_steps":47,"movement_scenario":{"status":"conditional_direct_land_approach","turns":3,"daily_points":2000}}}]})");
RequestArbiter arbiter;arbiter.beginTurn(1,{280000,120000,40000});
auto first=arbiter.consider({automaticSafetySignal(review,1,true)});
arbiter.dispatched(first);arbiter.finished(22000,73532);
auto changed=review;changed["visible_threats"][0]["enemy_ref"].String()="new_enemy";
require(arbiter.consider({automaticSafetySignal(changed,1,true)}).request);
changed=review;changed["visible_threats"][0]["position"]=json("[49,0,0]");
require(arbiter.consider({automaticSafetySignal(changed,1,true)}).request);
changed=review;changed["visible_threats"][0]["army_interval"]["lower"].Integer()=20000;
require(arbiter.consider({automaticSafetySignal(changed,1,true)}).request);
changed=review;changed["own_strength"].Integer()=100;
require(arbiter.consider({automaticSafetySignal(changed,1,true)}).request);
changed=review;changed["target_position"]=json("[11,0,0]");
require(arbiter.consider({automaticSafetySignal(changed,1,true)}).request);
changed=review;changed["visible_threats"][0]["known_land_approach"]["movement_scenario"]["turns"].Integer()=2;
require(arbiter.consider({automaticSafetySignal(changed,1,true)}).request);
require(arbiter.consider({automaticSafetySignal(review,2,true)}).request);
// Missing movement evidence never receives the coarser comparison.
review["visible_threats"][0]["known_land_approach"].Struct().erase("movement_scenario");
first=arbiter.consider({automaticSafetySignal(review,1,true)});
arbiter.dispatched(first);arbiter.finished(1000,100);
changed=review;changed["stop_positions"]=json("[[4,0,0]]");
require(arbiter.consider({automaticSafetySignal(changed,1,true)}).request);
// Passage crossing remains critical and exact, independent of helper coalescing.
review["reason"].String()="passage_crossing_requires_fresh_decision";
auto crossing=automaticSafetySignal(review,1,true);require(crossing.critical);
first=arbiter.consider({crossing});arbiter.dispatched(first);arbiter.finished(1000,100);
changed=review;changed["stop_positions"]=json("[[4,0,0]]");
require(arbiter.consider({automaticSafetySignal(changed,1,true)}).request);
''')

    def test_multiple_visible_threats_keep_the_saved_review_loadable(self):
        self.proof(r'''
std::vector<KnownLandTile> land(13);JsonNode positions;positions.Vector();
for(size_t i=0;i<land.size();++i) {
 positions.Vector().push_back(json("["+std::to_string(i)+",0,0]"));
 if(i) { land[i].neighbors.push_back(i-1);land[i].movementCosts.push_back(100); }
 if(i+1<land.size()) { land[i].neighbors.push_back(i+1);land[i].movementCosts.push_back(100); }
}
auto review=json(R"({"hero_ref":"helper","reason":"automatic_helper_approaches_stronger_visible_enemy","status":"conditional_unchanged_route","origin":[0,0,0],"stop_positions":[[3,0,0]],"target_position":[10,0,0],"own_strength":107,"visible_threats":[]})");
auto threat=json(R"({"enemy_ref":"enemy","position":[12,0,0],"army_interval":{"basis":"UI creature counts and public creature AI values; enemy combat bonuses and intentions unknown","lower":10000,"upper":15000},"tile_distance":9})");
threat["known_land_approach"]=knownLandApproach(land,12,3,500);
for(int i=0;i<16;++i) {
 threat["enemy_ref"].String()="enemy"+std::to_string(i);
 review["visible_threats"].Vector().push_back(threat);
}
RequestArbiter arbiter;arbiter.beginTurn(1,{280000,120000,40000});
auto before=review;
for(auto & threat:before["visible_threats"].Vector()) threat["known_land_approach"].Struct().erase("movement_scenario");
if(before.toCompactString().size()>8192) throw std::runtime_error("baseline "+std::to_string(before.toCompactString().size()));
require(automaticSafetySignal(review,1,true).facts.size()<=before.toCompactString().size());
auto first=arbiter.consider({automaticSafetySignal(review,1,true)});
arbiter.dispatched(first);arbiter.finished(22000,73532);
// NativeCampaign::restoreArbiter rejects saved fact strings above 8192 bytes.
for(const auto & [question,facts]:arbiter.save().addressed) require(facts.size()<=8192);
RequestArbiter restored(arbiter.save());
require(!restored.consider({automaticSafetySignal(review,1,true)}).request);
require(review["visible_threats"][0]["known_land_approach"]["movement_scenario"]["assumptions"].isString());
// One unknown enemy retains exact route facts without duplicating known prose.
review["visible_threats"][0]["known_land_approach"].Struct().erase("movement_scenario");
require(automaticSafetySignal(review,1,true).facts.size()<=before.toCompactString().size());
first=restored.consider({automaticSafetySignal(review,1,true)});
require(first.request);restored.dispatched(first);restored.finished(1000,100);
for(const auto & [question,facts]:restored.save().addressed) require(facts.size()<=8192);
auto moved=review;moved["stop_positions"]=json("[[4,0,0]]");
require(restored.consider({automaticSafetySignal(moved,1,true)}).request);
''')

    def test_helper_review_retains_conditional_approach_turns_for_reconsideration(self):
        self.proof(r'''
std::vector<KnownLandTile> land(13);JsonNode positions;positions.Vector();
for(size_t i=0;i<land.size();++i) {
 positions.Vector().push_back(json("["+std::to_string(i)+",0,0]"));
 if(i) { land[i].neighbors.push_back(i-1);land[i].movementCosts.push_back(100); }
 if(i+1<land.size()) { land[i].neighbors.push_back(i+1);land[i].movementCosts.push_back(100); }
}
auto world=json(R"({"enemy_players":[1],"visible_objects":[{"ref":"enemy","kind":"hero","owner":1,"position":[12,0,0],"army_interval":{"lower":10000}}]})");
auto exposure=scoutStopExposure(positions[0],json(R"([{"position":[3,0,0],"turn":0}])"),true,world,land,positions,true);
auto review=helperStopReview(positions[0],107,exposure,land,positions,500);
require(review["visible_threats"][0]["known_land_approach"]["movement_scenario"]["turns"].Integer()==2);
require(review["visible_threats"][0]["known_land_approach"]["movement_scenario"]["status"].String()=="conditional_direct_land_approach");
require(review["enemy_movement_unknown"].Bool());
''')

    def test_directed_portal_and_gate_connections_expose_cross_level_enemy(self):
        self.proof(r'''
JsonNode positions=json("[[0,0,0],[1,0,0],[1,0,1],[2,0,1]]");
std::vector<KnownLandTile> land(4);
land[0].neighbors={1};land[0].movementCosts={100};
land[1].neighbors={0};land[1].movementCosts={100};
land[2].neighbors={3};land[2].movementCosts={100};
land[3].neighbors={2};land[3].movementCosts={100};
JsonNode links;
require(recordObservedPortal(links,positions[2],positions[1],false,false));
require(validObservedPassages(links));
require(!passageLinkFrom(links[0],positions[1]));
require(observedPassageKnown(links,positions[2],positions[1]));
require(!observedPassageKnown(links,positions[1],positions[2]));
require(!passageLinkFrom(links[0],positions[2],true));
addKnownPassageEdges(land,positions,links,0);
require(knownLandApproach(land,3,0)["status"].String()=="no_visible_neutral_barrier_on_known_land_connection");
require(knownLandApproach(land,0,3)["status"].String()=="no_complete_visible_land_connection");
auto world=json(R"({"enemy_players":[1],"visible_objects":[{"ref":"enemy","kind":"hero","owner":1,"position":[2,0,1],"army_interval":{"lower":30000}}]})");
auto exposure=scoutStopExposure(positions[1],json("[{\"position\":[0,0,0],\"turn\":0,\"interaction\":false}]"),true,world,land,positions);
require(exposure["visible_threats"].Vector().size()==1);
require(exposure["visible_threats"][0]["enemy_ref"].String()=="enemy");
JsonNode gates;require(recordObservedPassage(gates,positions[1],positions[2]));
require(validObservedPassages(gates));
require(observedPassageKnown(gates,positions[2],positions[1]));
require(!observedPassageKnown(gates,positions[2],positions[0]));
require(passageLinkFrom(gates[0],positions[1],true));require(passageLinkFrom(gates[0],positions[2],true));
JsonNode portals;require(recordObservedPortal(portals,positions[0],positions[1],true,true));
require(recordObservedPortal(portals,positions[0],positions[3],true,true));
require(portals.Vector().size()==2); // One observed exit never erases another.
require(passageLinkFrom(portals[0],positions[1],true));
''')

    def test_helper_approach_needs_a_model_choice_but_collection_away_stays_automatic(self):
        self.proof(r'''
std::vector<KnownLandTile> land(13);
JsonNode positions;positions.Vector();
for(size_t i=0;i<land.size();++i) {
 positions.Vector().push_back(json("["+std::to_string(i)+",0,0]"));
 if(i) land[i].neighbors.push_back(i-1);
 if(i+1<land.size()) land[i].neighbors.push_back(i+1);
}
auto world=json(R"({"enemy_players":[1],"visible_objects":[{"ref":"enemy","kind":"hero","owner":1,"position":[12,0,0],"army_interval":{"lower":10000,"upper":15000}}]})");
auto origin=json("[0,0,0]");
auto route=json(R"([{"position":[3,0,0],"turn":0}])");
route.Vector().push_back(ordinaryStopNode(json("[4,0,0]"),0,EPathNodeAction::BLOCKING_VISIT,true));
auto exposure=scoutStopExposure(origin,route,true,world,land,positions,true);
auto review=helperStopReview(origin,107,exposure,land,positions);
require(!review.isNull());
require(review["stop_positions"]==json("[[3,0,0]]"));
require(review["enemy_movement_unknown"].Bool());
require(helperStopReview(origin,20000,exposure,land,positions).isNull());
land[9].neutralGuards={"screen"};
exposure=scoutStopExposure(origin,json(R"([{"position":[3,0,0],"turn":0}])"),true,world,land,positions,true);
require(helperStopReview(origin,107,exposure,land,positions).isNull());
land[9].neutralGuards.clear();
origin=json("[3,0,0]");
route=json(R"([{"position":[0,0,0],"turn":0}])");
route.Vector().push_back(ordinaryStopNode(json("[1,0,0]"),0,EPathNodeAction::BLOCKING_VISIT,true));
exposure=scoutStopExposure(origin,route,true,world,land,positions,true);
require(helperStopReview(origin,107,exposure,land,positions).isNull());
require(helperStopReview(origin,107,scoutStopExposure(origin,json("[]"),false,world,land,positions,true),land,positions).isNull());
''')

    def test_multiday_stop_is_current_turn_position_with_visible_enemy_context(self):
        self.proof(r'''
auto world=json(R"({"enemy_players":[1],"visible_objects":[{"ref":"enemy","kind":"hero","owner":1,"position":[2,0,0],"army_interval":{"lower":500,"upper":1000}}]})");
auto origin=json("[0,0,0]");
auto nodes=json(R"([{"position":[1,0,0],"turn":0},{"position":[2,0,0],"turn":1}])");
std::vector<KnownLandTile> land(3);land[0].neighbors={1};land[1].neighbors={0,2};land[2].neighbors={1};
auto positions=json("[[0,0,0],[1,0,0],[2,0,0]]");
auto result=scoutStopExposure(origin,nodes,true,world,land,positions);
require(result["status"].String()=="conditional_unchanged_route");
require(result["stop_positions"]==json("[[1,0,0]]"));
require(result["visible_threats"][0]["enemy_ref"].String()=="enemy");
require(result["visible_threats"][0]["tile_distance"].Integer()==1);
require(result["visible_threats"][0]["known_land_approach"]["known_land_steps"].Integer()==1);
require(result["visible_threats"][0]["army_interval"]["lower"].Integer()==500);
require(result["enemy_movement_unknown"].Bool());
''')

    def test_automatic_departure_reviews_the_town_left_without_protection(self):
        self.proof(r'''
std::vector<KnownLandTile> land(7);JsonNode positions;positions.Vector();
for(size_t i=0;i<7;++i) { positions.Vector().push_back(json("["+std::to_string(i)+",0,0]"));
 if(i) land[i].neighbors.push_back(i-1);if(i+1<7) land[i].neighbors.push_back(i+1); }
auto world=json(R"({"enemy_players":[1],"towns":[{"ref":"town","position":[0,0,0],"defense_value":100}],"heroes":[{"ref":"main","position":[1,0,0],"army_value":2000}],"visible_objects":[{"ref":"enemy","kind":"hero","owner":1,"position":[6,0,0],"army_interval":{"lower":1000}}]})");
auto origin=json("[1,0,0]");auto exposure=scoutStopExposure(origin,json(R"([{"position":[3,0,0],"turn":0}])"),true,world,land,positions,true);
require(!townStopReview("main",origin,exposure,world,land,positions).isNull());
world["towns"][0]["defense_value"].Integer()=1500;
require(townStopReview("main",origin,exposure,world,land,positions).isNull());
world["towns"][0]["defense_value"].Integer()=100;land[4].neutralGuards={"screen"};
require(townStopReview("main",origin,exposure,world,land,positions).isNull());
land[4].neutralGuards.clear();world["heroes"].Vector().push_back(json(R"({"ref":"defender","position":[0,0,0],"army_value":1500})"));
require(townStopReview("main",origin,exposure,world,land,positions).isNull());
''')

    def test_same_day_arrival_and_waiting_keep_stop_but_never_claim_safety(self):
        self.proof(r'''
auto world=json(R"({"enemy_players":[1],"visible_objects":[]})");
auto empty=json("[]");auto origin=json("[0,0,0]");
auto nodes=json(R"([{"position":[1,0,0],"turn":0},{"position":[2,0,0],"turn":0}])");
auto arrival=scoutStopExposure(origin,nodes,true,world,{},empty);
require(arrival["stop_positions"]==json("[[2,0,0]]"));
require(arrival["visible_threats"].Vector().empty() && arrival["enemy_movement_unknown"].Bool());
require(arrival["status"].String()=="conditional_unchanged_route");
auto waiting=scoutStopExposure(origin,empty,true,world,{},empty);
require(waiting["stop_positions"]==json("[[0,0,0]]"));
auto special=scoutStopExposure(origin,nodes,false,world,{},empty);
require(special["status"].String()=="unknown" && special["stop_positions"].Vector().empty());
auto encounter=json(R"([{"position":[1,0,0],"turn":0,"interaction":true}])");
require(scoutStopExposure(origin,encounter,true,world,{},empty)["status"].String()=="unknown");
''')

    def test_visible_barrier_disconnection_and_bounded_enemy_selection(self):
        self.proof(r'''
auto world=json(R"({"enemy_players":[1],"visible_objects":[{"ref":"far","kind":"hero","owner":1,"position":[4,0,0]},{"ref":"barrier","kind":"hero","owner":1,"position":[2,0,0]},{"ref":"disconnected","kind":"hero","owner":1,"position":[1,1,0]},{"ref":"unknownland","kind":"hero","owner":1,"position":[3,0,0]},{"ref":"allied","kind":"hero","owner":0,"position":[0,0,0]},{"ref":"below","kind":"hero","owner":1,"position":[0,0,1]},{"ref":"monster","kind":"monster","owner":1,"position":[0,0,0]}],"remembered_objects":[{"ref":"hidden","kind":"hero","owner":1,"position":[0,0,0]}]})");
auto positions=json("[[0,0,0],[1,0,0],[2,0,0],[1,1,0]]");
std::vector<KnownLandTile> land(4);land[0].neighbors={1};land[1].neighbors={0,2};land[2].neighbors={1};
land[1].neutralGuards={"neutral"};
auto result=scoutStopExposure(json("[0,0,0]"),json("[]"),true,world,land,positions);
require(result["visible_enemy_count_in_coverage"].Integer()==4);
require(result["omitted_visible_enemy_count"].Integer()==1);
require(result["visible_threats"].Vector().size()==3);
require(result["visible_threats"][0]["enemy_ref"].String()=="disconnected");
require(result["visible_threats"][0]["known_land_approach"]["status"].String()=="no_complete_visible_land_connection");
require(result["visible_threats"][1]["enemy_ref"].String()=="barrier");
require(result["visible_threats"][1]["known_land_approach"]["status"].String()=="neutral_encounter_required_on_known_land_connections");
require(result["visible_threats"][2]["enemy_ref"].String()=="unknownland");
require(result["visible_threats"][2]["known_land_approach"]["status"].String()=="no_complete_visible_land_connection");
// A guard only on the final stop tile does not shield the own hero.
land[1].neutralGuards.clear();land[0].neutralGuards={"finalguard"};
auto final=scoutStopExposure(json("[0,0,0]"),json("[]"),true,world,land,positions);
require(final["visible_threats"][1]["known_land_approach"]["status"].String()=="no_visible_neutral_barrier_on_known_land_connection");
''')

    def test_compressed_native_waypoints_correspond_to_full_player_route(self):
        self.proof(r'''
auto player=json(R"([{"position":[0,0,0],"turn":0},{"position":[1,0,0],"turn":0},{"position":[2,0,0],"turn":0},{"position":[3,0,0],"turn":1},{"position":[4,0,0],"turn":1}])");
auto sparse=json(R"([{"position":[0,0,0],"turn":0},{"position":[4,0,0],"turn":1}])");
require(scoutRouteCorresponds(sparse,player));
auto waypoints=json(R"([{"position":[0,0,0],"turn":0},{"position":[2,0,0],"turn":0},{"position":[4,0,0],"turn":1}])");
require(scoutRouteCorresponds(waypoints,player));
waypoints[1]["turn"].Integer()=1;
require(!scoutRouteCorresponds(waypoints,player));
waypoints[1]["turn"].Integer()=0;waypoints[1]["position"]=json("[2,1,0]");
require(!scoutRouteCorresponds(waypoints,player));
auto reversed=json(R"([{"position":[4,0,0],"turn":1},{"position":[2,0,0],"turn":0}])");
require(!scoutRouteCorresponds(reversed,player));
require(!scoutRouteCorresponds(json("[]"),player));
''')


if __name__=='__main__': unittest.main()
