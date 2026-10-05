#pragma once
#include "json/JsonNode.h"
#include <deque>
#include <cstddef>
#include <set>
#include <vector>
#include <string>

namespace nullkiller3
{
struct KnownLandTile
{
    std::vector<size_t> neighbors;
    std::vector<std::string> neutralGuards;
};
// The final attack/interaction may use native blockingVisit(IGNORE_GUARDS).
// A neutral zone on the target asset alone does not shield that hero/town.
// Visible land connectivity is an overapproximation: no private enemy movement,
// no unseen tiles, no water/spells, no claim that a guard can or cannot be beaten.
inline JsonNode knownLandApproach(const std::vector<KnownLandTile> & tiles,size_t source,size_t target)
{
    auto walk=[&](bool avoidGuards) {
        std::vector<int64_t> parents(tiles.size(),-1);std::deque<size_t> queue;
        parents[source]=source;queue.push_back(source);
        while(!queue.empty())
        {
            const auto at=queue.front();queue.pop_front();
            for(const auto next:tiles[at].neighbors)
                if(parents[next]<0 && (!avoidGuards || next==target || tiles[next].neutralGuards.empty()))
                { parents[next]=at;queue.push_back(next); }
        }
        return parents;
    };
    JsonNode result;result["unknown_bypass"].Bool()=true;result["example_guard_refs"].Vector();
    const auto unguarded=walk(true),all=walk(false);
    if(all[target]<0) { result["status"].String()="no_complete_visible_land_connection";return result; }
    result["status"].String()=unguarded[target]>=0 ? "no_visible_neutral_barrier_on_known_land_connection"
        : "neutral_encounter_required_on_known_land_connections";
    int64_t steps=0;std::set<std::string> guards;
    for(size_t at=target;at!=source;at=all[at])
    { ++steps;guards.insert(tiles[at].neutralGuards.begin(),tiles[at].neutralGuards.end()); }
    result["known_land_steps"].Integer()=steps;
    // One example connection, not a claim that every listed guard is unavoidable.
    if(unguarded[target]<0) for(const auto & ref:guards) result["example_guard_refs"].Vector().emplace_back(ref);
    return result;
}
}
