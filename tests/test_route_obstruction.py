"""Own route obstruction contract through the native known-land graph seam."""
import test_scout_stop_exposure as exposure

class RouteObstructionTest(exposure.ScoutStopExposureTest):
    def test_idle_helper_can_yield_into_side_pocket_but_not_shift_the_block(self):
        self.proof(r'''
std::vector<KnownLandTile> land(5);
land[0].neighbors={1};land[1].neighbors={0,2};land[2].neighbors={1,3,4};land[3].neighbors={2};land[4].neighbors={2};
require(!knownLandConnection(land,0,3,{1}));
require(yieldOpensKnownConnection(land,0,3,{1},1,4));
require(!yieldOpensKnownConnection(land,0,3,{1},1,2));
require(!yieldOpensKnownConnection(land,0,3,{1,4},1,4));
land[2].neutralGuards={"guard"};
require(!yieldOpensKnownConnection(land,0,3,{1},1,4));
''')

    def test_alternative_route_and_disconnected_land_do_not_trigger_a_yield(self):
        self.proof(r'''
std::vector<KnownLandTile> land(5);
land[0].neighbors={1,2};land[1].neighbors={0,3};land[2].neighbors={0,3};land[3].neighbors={1,2,4};land[4].neighbors={3};
require(knownLandConnection(land,0,3,{1}));
require(!yieldOpensKnownConnection(land,0,3,{1},1,4));
land[0].neighbors={1};land[1].neighbors={0};
require(!yieldOpensKnownConnection(land,0,3,{1},1,4));
require(!yieldOpensKnownConnection(land,0,3,{1},1,0));
require(!yieldOpensKnownConnection(land,0,3,{1},1,99));
''')
