#pragma once
#include "json/JsonNode.h"
#include "ObservedPassages.h"
#include "constants/EntityIdentifiers.h"
#include "pathfinder/CGPathNode.h"
#include <deque>
#include <algorithm>
#include <cstdlib>
#include <cstddef>
#include <set>
#include <vector>
#include <string>
#include <queue>
#include <tuple>
#include <limits>

namespace nullkiller3
{
inline bool isNeutralMonsterGuard(Obj type,PlayerColor owner)
{
    // Monsters normally have UNFLAGGABLE ownership; neither neutral code is a player.
    return type==Obj::MONSTER && (owner==PlayerColor::NEUTRAL || owner==PlayerColor::UNFLAGGABLE);
}

struct KnownLandTile
{
    std::vector<size_t> neighbors;
    std::vector<std::string> neutralGuards;
    std::vector<int64_t> movementCosts; // Visible road/base terrain cost, parallel to neighbors.
    std::set<int64_t> blockedPlayers; // Exact key access at visible border gates/guards.
};
// Observed random exits are possible enemy approaches, never guaranteed own travel.
inline void addKnownPassageEdges(std::vector<KnownLandTile> & land,const JsonNode & positions,const JsonNode & links,int64_t movementCost)
{
    if(!validObservedPassages(links) || movementCost<0) return;
    for(const auto & link:links.Vector()) {
        auto cell=[&](const JsonNode & p) { return size_t(std::find(positions.Vector().begin(),positions.Vector().end(),p)-positions.Vector().begin()); };
        const auto from=cell(link["from"]),to=cell(link["to"]);
        if(from>=land.size() || to>=land.size()) continue;
        auto connect=[&](size_t a,size_t b) { land[a].neighbors.push_back(b);land[a].movementCosts.push_back(movementCost); };
        connect(from,to);
        if(passageLinkFrom(link,link["to"])) connect(to,from);
    }
}
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
inline JsonNode knownLandApproach(const std::vector<KnownLandTile> & tiles,size_t source,size_t target,int64_t dailyPoints=0,int64_t player=-1)
{
    auto walk=[&](bool avoidGuards) {
        std::vector<int64_t> parents(tiles.size(),-1);std::deque<size_t> queue;
        parents[source]=source;queue.push_back(source);
        while(!queue.empty())
        {
            const auto at=queue.front();queue.pop_front();
            for(const auto next:tiles[at].neighbors)
                if(next<tiles.size() && !tiles[next].blockedPlayers.count(player) && parents[next]<0 && (!avoidGuards || next==target || tiles[next].neutralGuards.empty()))
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
    if(unguarded[target]>=0 && dailyPoints>0)
    {
        // Pack visible step costs into full turns. No private hero movement is read.
        using Cost=std::pair<int64_t,int64_t>; // completed turns, points used this turn
        const Cost infinity{std::numeric_limits<int64_t>::max(),0};
        std::vector<Cost> costs(tiles.size(),infinity);
        using Entry=std::tuple<int64_t,int64_t,size_t>;
        std::priority_queue<Entry,std::vector<Entry>,std::greater<Entry>> pending;
        costs[source]={0,0};pending.emplace(0,0,source);
        while(!pending.empty())
        {
            const auto [turn,spent,at]=pending.top();pending.pop();
            if(costs[at]!=Cost{turn,spent}) continue;
            if(at==target) break;
            if(tiles[at].movementCosts.size()!=tiles[at].neighbors.size()) continue;
            for(size_t i=0;i<tiles[at].neighbors.size();++i)
            {
                const auto next=tiles[at].neighbors[i];const auto step=tiles[at].movementCosts[i];
                if(next>=tiles.size() || tiles[next].blockedPlayers.count(player) || step<0 || step>dailyPoints
                    || (next!=target && !tiles[next].neutralGuards.empty())) continue;
                Cost cost=spent+step<=dailyPoints ? Cost{turn,spent+step} : Cost{turn+1,step};
                if(cost<costs[next]) { costs[next]=cost;pending.emplace(cost.first,cost.second,next); }
            }
        }
        if(costs[target]!=infinity)
        {
            auto & scenario=result["movement_scenario"];
            scenario["turns"].Integer()=costs[target].first+1;
            scenario["daily_points"].Integer()=dailyPoints;
            scenario["status"].String()="conditional_direct_land_approach";
            scenario["assumptions"].String()="Full turns at the fastest configured standard land allowance, no terrain penalty, visible road and diagonal costs. Direct travel through known land and observed gate/portal connections without battles, other armies or detours. Random portal exits describe a possible approach, not a guaranteed arrival. Private remaining movement, bonuses, intent and unseen alternatives are unknown; actual arrival can be earlier or later. Not an ETA or safety bound.";
        }
    }
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

inline JsonNode ordinaryStopNode(const JsonNode & position,int64_t turn,EPathNodeAction action,bool land)
{
    JsonNode node;node["position"]=position;node["turn"].Integer()=turn;
    node["remains_on_previous_tile"].Bool()=action==EPathNodeAction::BLOCKING_VISIT;
    node["interaction"].Bool()=!land || (action!=EPathNodeAction::NORMAL && action!=EPathNodeAction::VISIT
        && action!=EPathNodeAction::BLOCKING_VISIT);
    return node;
}

// Own route nodes are in movement order. A stop is conditional on the same
// ordinary route executing without interruption; it is not an enemy ETA.
inline JsonNode scoutStopExposure(const JsonNode & origin,const JsonNode & nodes,bool ordinaryRoute,
    const JsonNode & world,const std::vector<KnownLandTile> & land,const JsonNode & landPositions,bool allThreats=false)
{
    JsonNode result;result["stop_positions"].Vector();result["visible_threats"].Vector();
    result["status"].String()="unknown";
    result["enemy_movement_unknown"].Bool()=true;
    result["basis"].String()="Own current-turn stop only when the player-scoped ordinary route matches the native route; interruption, replanning and later orders can change it. Visible land connections respect directional entrances but ignore other armies; fog, water, spells and neutral battle outcomes remain unknown.";
    result["coverage"].String()="At most three closest currently visible enemy heroes on the stop level or connected through observed passages; other enemies and unseen movement remain unknown. Distances are not movement bounds or attack probabilities.";
    if(!ordinaryRoute) return result;
    auto stop=origin;
    for(const auto & node:nodes.Vector())
    {
        if(node["turn"].Integer()>0) break;
        if(node["interaction"].Bool()) return result;
        if(node["remains_on_previous_tile"].Bool()) break;
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
        if(position.Vector().size()!=3) continue;
        if(position[2]!=stop[2]) {
            const auto from=cell(position),to=cell(stop);
            if(from>=land.size() || to>=land.size() || knownLandApproach(land,from,to,0,enemy["owner"].Integer())["status"].String()=="no_complete_visible_land_connection") continue;
        }
        JsonNode threat;threat["enemy_ref"]=enemy["ref"];threat["enemy_player"]=enemy["owner"];threat["position"]=position;
        threat["tile_distance"].Integer()=std::max(std::abs(position[0].Integer()-stop[0].Integer()),std::abs(position[1].Integer()-stop[1].Integer()));
        threat["army_interval"]=enemy["army_interval"];
        threats.push_back(std::move(threat));
    }
    std::sort(threats.begin(),threats.end(),[](const auto & first,const auto & second) {
        if(first["tile_distance"]!=second["tile_distance"]) return first["tile_distance"].Integer()<second["tile_distance"].Integer();
        return first["enemy_ref"].String()<second["enemy_ref"].String();
    });
    result["visible_enemy_count_in_coverage"].Integer()=threats.size();
    result["omitted_visible_enemy_count"].Integer()=!allThreats && threats.size()>3 ? threats.size()-3 : 0;
    if(!allThreats && threats.size()>3) threats.resize(3);
    if(allThreats) result["coverage"].String()="All currently visible enemy heroes on the stop level or connected through observed passages; unseen movement remains unknown.";
    for(auto & threat:threats)
    {
        const auto from=cell(threat["position"]),to=cell(stop);
        if(from<land.size() && to<land.size()) threat["known_land_approach"]=knownLandApproach(land,from,to,0,threat["enemy_player"].Integer());
        else threat["known_land_approach"]["status"].String()="no_complete_visible_land_connection";
    }
    result["visible_threats"].Vector()=std::move(threats);
    return result;
}

// This asks for a strategic choice; it is not enemy reachability or a battle forecast.
inline JsonNode helperStopReview(const JsonNode & origin,uint64_t ownStrength,const JsonNode & exposure,
    const std::vector<KnownLandTile> & land,const JsonNode & positions,int64_t dailyPoints=0)
{
    if(exposure["status"].String()!="conditional_unchanged_route"
        || exposure["stop_positions"].Vector().empty() || exposure["stop_positions"][0]==origin) return JsonNode();
    auto cell=[&](const JsonNode & pos) {
        return size_t(std::find(positions.Vector().begin(),positions.Vector().end(),pos)-positions.Vector().begin());
    };
    const auto start=cell(origin);
    if(start>=land.size()) return JsonNode();
    for(const auto & threat:exposure["visible_threats"].Vector())
    {
        const auto & lower=threat["army_interval"]["lower"];
        const auto & next=threat["known_land_approach"];
        if(!lower.isNumber() || lower.Integer()<=0 || uint64_t(lower.Integer())<=ownStrength
            || next["status"].String()!="no_visible_neutral_barrier_on_known_land_connection") continue;
        const auto enemy=cell(threat["position"]);
        if(enemy>=land.size()) continue;
        const auto previous=knownLandApproach(land,enemy,start,0,threat["enemy_player"].isNumber() ? threat["enemy_player"].Integer() : -1);
        if(previous["status"].String()!="no_visible_neutral_barrier_on_known_land_connection"
            || next["known_land_steps"].Integer()>=previous["known_land_steps"].Integer()) continue;
        auto review=exposure;
        review["origin"]=origin;review["own_strength"].Integer()=ownStrength;
        review["reason"].String()="automatic_helper_approaches_stronger_visible_enemy";
        if(dailyPoints>0)
            for(auto & visible:review["visible_threats"].Vector())
            {
                const auto source=cell(visible["position"]),stop=cell(review["stop_positions"][0]);
                if(source<land.size() && stop<land.size())
                    visible["known_land_approach"]=knownLandApproach(land,source,stop,dailyPoints,visible["enemy_player"].isNumber() ? visible["enemy_player"].Integer() : -1);
            }
        return review;
    }
    return JsonNode();
}

inline JsonNode townStopReview(const std::string & heroRef,const JsonNode & origin,const JsonNode & exposure,
    const JsonNode & world,const std::vector<KnownLandTile> & land,const JsonNode & positions)
{
    if(exposure["status"].String()!="conditional_unchanged_route" || exposure["stop_positions"].Vector().empty()) return JsonNode();
    auto cell=[&](const JsonNode & p) { return size_t(std::find(positions.Vector().begin(),positions.Vector().end(),p)-positions.Vector().begin()); };
    const auto start=cell(origin),stop=cell(exposure["stop_positions"][0]);
    if(start>=land.size() || stop>=land.size()) return JsonNode();
    auto local=[&](size_t from,size_t town) {
        if(from>=land.size()) return false;
        const auto path=knownLandApproach(land,from,town);
        return path["status"].String()=="no_visible_neutral_barrier_on_known_land_connection" && path["known_land_steps"].Integer()<=1;
    };
    for(const auto & town:world["towns"].Vector())
    {
        const auto target=cell(town["position"]);
        if(target>=land.size() || !local(start,target) || local(stop,target)) continue;
        int64_t retained=town["army_holder_ref"].String()==heroRef ? 0 : town["defense_value"].Integer();
        for(const auto & hero:world["heroes"].Vector())
            if(hero["ref"].String()!=heroRef && hero["ref"]!=town["army_holder_ref"] && local(cell(hero["position"]),target))
                retained+=hero["army_value"].Integer();
        for(const auto & enemy:world["visible_objects"].Vector())
        {
            const auto from=cell(enemy["position"]);
            if(enemy["kind"].String()!="hero" || from>=land.size()
                || std::find(world["enemy_players"].Vector().begin(),world["enemy_players"].Vector().end(),enemy["owner"])==world["enemy_players"].Vector().end()
                || !enemy["army_interval"]["lower"].isNumber() || enemy["army_interval"]["lower"].Integer()<=retained) continue;
            const auto path=knownLandApproach(land,from,target,0,enemy["owner"].Integer());
            if(path["status"].String()!="no_visible_neutral_barrier_on_known_land_connection") continue;
            JsonNode review;review["reason"].String()="automatic_departure_exposes_town";
            review["town_ref"]=town["ref"];review["enemy_ref"]=enemy["ref"];
            review["remaining_local_force"].Integer()=retained;review["enemy_army_interval"]=enemy["army_interval"];
            review["known_land_approach"]=path;review["end_turn_exposure"]=exposure;
            review["limits"].String()="A strategic comparison is needed, not a proven defeat. Local army estimates exclude fortification/combat bonuses; enemy arrival and intent remain conditional.";
            return review;
        }
    }
    return JsonNode();
}

}
