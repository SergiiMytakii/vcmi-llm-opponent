#pragma once
#include "json/JsonNode.h"
#include <deque>
#include <algorithm>
#include <cstdlib>
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
// Occupancy is a current physical constraint, not a predicted arrival.
// Neutral encounters stay closed: yielding never authorizes a battle.
inline bool knownLandConnection(const std::vector<KnownLandTile> & tiles,size_t source,size_t target,
    const std::set<size_t> & occupied)
{
    if(source>=tiles.size() || target>=tiles.size() || occupied.count(source) || occupied.count(target)) return false;
    std::set<size_t> visited{source};std::deque<size_t> pending{source};
    while(!pending.empty())
    {
        const auto at=pending.front();pending.pop_front();
        if(at==target) return true;
        for(const auto next:tiles[at].neighbors)
            if(next<tiles.size() && !occupied.count(next) && tiles[next].neutralGuards.empty() && visited.insert(next).second)
                pending.push_back(next);
    }
    return false;
}
inline bool yieldOpensKnownConnection(const std::vector<KnownLandTile> & tiles,size_t source,size_t target,
    std::set<size_t> occupied,size_t blocker,size_t destination)
{
    if(blocker==source || destination==source || destination>=tiles.size() || !occupied.count(blocker)
        || occupied.count(destination) || !tiles[destination].neutralGuards.empty()
        || knownLandConnection(tiles,source,target,occupied)) return false;
    occupied.erase(blocker);occupied.insert(destination);
    return knownLandConnection(tiles,source,target,occupied);
}

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
    const auto & parents=unguarded[target]>=0 ? unguarded : all;
    for(size_t at=target;at!=source;at=parents[at])
    { ++steps;guards.insert(tiles[at].neutralGuards.begin(),tiles[at].neutralGuards.end()); }
    result["known_land_steps"].Integer()=steps;
    // One example connection, not a claim that every listed guard is unavoidable.
    if(unguarded[target]<0) for(const auto & ref:guards) result["example_guard_refs"].Vector().emplace_back(ref);
    return result;
}
// Native pathfinding may retain only waypoints; player paths retain every tile.
inline bool scoutRouteCorresponds(const JsonNode & nativeWaypoints,const JsonNode & playerNodes)
{
    if(nativeWaypoints.Vector().empty()) return false;
    auto next=playerNodes.Vector().begin();
    for(const auto & waypoint:nativeWaypoints.Vector())
    {
        next=std::find_if(next,playerNodes.Vector().end(),[&](const auto & node) {
            return node["position"]==waypoint["position"] && node["turn"]==waypoint["turn"];
        });
        if(next==playerNodes.Vector().end()) return false;
        ++next;
    }
    return true;
}

// Own route nodes are in movement order. A stop is conditional on the same
// ordinary route executing without interruption; it is not an enemy ETA.
inline JsonNode scoutStopExposure(const JsonNode & origin,const JsonNode & nodes,bool ordinaryRoute,
    const JsonNode & world,const std::vector<KnownLandTile> & land,const JsonNode & landPositions)
{
    JsonNode result;result["stop_positions"].Vector();result["visible_threats"].Vector();
    result["status"].String()="unknown";
    result["enemy_movement_unknown"].Bool()=true;
    result["basis"].String()="Own current-turn stop only when the player-scoped ordinary route matches the native route; interruption, replanning and later orders can change it. Visible land connections ignore directional entrances and other armies; fog, water, spells and neutral battle outcomes remain unknown.";
    result["coverage"].String()="At most three closest currently visible enemy heroes on the stop's level; other enemies and unseen movement remain unknown. Distances are not movement bounds or attack probabilities.";
    if(!ordinaryRoute) return result;
    auto stop=origin;
    for(const auto & node:nodes.Vector())
    {
        if(node["turn"].Integer()>0) break;
        if(node["interaction"].Bool()) return result;
        stop=node["position"];
    }
    result["status"].String()="conditional_unchanged_route";
    result["stop_positions"].Vector().push_back(stop);
    auto cell=[&](const JsonNode & position) {
        const auto found=std::find(landPositions.Vector().begin(),landPositions.Vector().end(),position);
        return static_cast<size_t>(found-landPositions.Vector().begin());
    };
    std::vector<JsonNode> threats;
    for(const auto & enemy:world["visible_objects"].Vector())
    {
        if(enemy["kind"].String()!="hero" || std::find(world["enemy_players"].Vector().begin(),world["enemy_players"].Vector().end(),enemy["owner"])==world["enemy_players"].Vector().end()) continue;
        const auto & position=enemy["position"];
        if(position.Vector().size()!=3 || position[2]!=stop[2]) continue;
        JsonNode threat;threat["enemy_ref"]=enemy["ref"];threat["position"]=position;
        threat["tile_distance"].Integer()=std::max(std::abs(position[0].Integer()-stop[0].Integer()),std::abs(position[1].Integer()-stop[1].Integer()));
        threat["army_interval"]=enemy["army_interval"];
        threats.push_back(std::move(threat));
    }
    std::sort(threats.begin(),threats.end(),[](const auto & first,const auto & second) {
        if(first["tile_distance"]!=second["tile_distance"]) return first["tile_distance"].Integer()<second["tile_distance"].Integer();
        return first["enemy_ref"].String()<second["enemy_ref"].String();
    });
    result["visible_enemy_count_on_stop_level"].Integer()=threats.size();
    result["omitted_visible_enemy_count"].Integer()=threats.size()>3 ? threats.size()-3 : 0;
    if(threats.size()>3) threats.resize(3);
    for(auto & threat:threats)
    {
        const auto from=cell(threat["position"]),to=cell(stop);
        if(from<land.size() && to<land.size()) threat["known_land_approach"]=knownLandApproach(land,from,to);
        else threat["known_land_approach"]["status"].String()="no_complete_visible_land_connection";
    }
    result["visible_threats"].Vector()=std::move(threats);
    return result;
}

}
