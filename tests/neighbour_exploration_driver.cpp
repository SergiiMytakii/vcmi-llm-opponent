#include "Global.h"
#include "AI/Nullkiller2/Goals/ExploreNeighbourTile.h"
#include <stdexcept>
int main() {
 NK2AI::NeighbourExplorationCandidate c;c.sameDay=true;c.accessible=true;c.safe=true;c.movementCost=.0666667f;c.strategicProgress=.25f;c.requireDiscovery=true;
 if(NK2AI::evaluateNeighbourExplorationCandidate(c).accepted) throw std::runtime_error("zero-discovery step accepted in strategic mode");
 c.strategicProgress=6;
 if(NK2AI::evaluateNeighbourExplorationCandidate(c).accepted) throw std::runtime_error("target score impersonates discovery");
 c.tilesDiscovered=3;
 if(!NK2AI::evaluateNeighbourExplorationCandidate(c).accepted) throw std::runtime_error("useful discovery rejected");
 c.safe=false;
 if(NK2AI::evaluateNeighbourExplorationCandidate(c).accepted) throw std::runtime_error("unsafe discovery accepted");
 c.safe=true;c.requireDiscovery=false;c.tilesDiscovered=0;
 if(!NK2AI::evaluateNeighbourExplorationCandidate(c).accepted) throw std::runtime_error("native NK2 objective stepping changed");
}
