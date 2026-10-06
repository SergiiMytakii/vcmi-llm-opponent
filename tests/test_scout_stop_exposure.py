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
            subprocess.run([str(binary)],check=True,capture_output=True,text=True)

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
require(result["visible_enemy_count_on_stop_level"].Integer()==4);
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
