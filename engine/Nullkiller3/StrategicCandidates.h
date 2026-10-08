#pragma once
#include "json/JsonNode.h"
#include "KeymasterAccess.h"
#include "StrategicMapOverview.h"
#include <algorithm>
#include <cmath>
#include <functional>
#include <limits>
#include <map>
#include <set>
#include <string>
#include <tuple>

namespace nullkiller3
{
// Screening is deterministic advice, not pathfinding or command admission.
// Coverage contains only coordinates hidden from this player, never their contents.
using ScoutCoverage = std::function<std::set<std::string>(const JsonNode &, int)>;
using CandidateRoutes = std::function<JsonNode(const JsonNode &, bool, bool)>;
constexpr size_t SCOUT_CHOICES_PER_HERO=6, SCOUT_PROBES_PER_HERO=18;
constexpr size_t TARGET_CHOICES_PER_GROUP=4, TARGET_PROBES_PER_GROUP=12;

inline int64_t candidateDistance(const JsonNode & a,const JsonNode & b)
{
    if(!a.isVector() || !b.isVector() || a.Vector().size()!=3 || b.Vector().size()!=3)
        return 1000000;
    const auto level=a[2]==b[2] ? 0 : 100000;
    return level+std::max(std::abs(a[0].Integer()-b[0].Integer()),std::abs(a[1].Integer()-b[1].Integer()));
}
inline std::set<std::string> requiredCandidateRefs(const JsonNode & world,const JsonNode & plan,const JsonNode & intent=JsonNode())
{
    std::set<std::string> result;
    for(const auto & goal:plan["goals"].Vector())
    {
        for(const auto * key:{"actor_ref","target_ref","job_ref"}) if(goal[key].isString()) result.insert(goal[key].String());
    }
    for(const auto * key:{"towns","heroes"}) for(const auto & item:world[key].Vector()) result.insert(item["ref"].String());
    for(const auto & ref:plan["policy"]["critical_towns"].Vector()) result.insert(ref.String());
    const auto milestoneRefs=strategicIntentCandidateRefs(intent);
    result.insert(milestoneRefs.begin(),milestoneRefs.end());
    return result;
}
// At most three distinct operational extremes per hero: fastest, least loss,
// greatest remaining army. Required goals bypass this optional-choice limit.
inline JsonNode representativeCandidateRoutes(const JsonNode & routes)
{
    JsonNode result;result.Vector();
    std::map<std::string,std::vector<JsonNode>> actors;
    for(const auto & route:routes.Vector()) actors[route["hero_ref"].String()].push_back(route);
    for(auto & [actor,options]:actors)
    {
        auto add=[&](const auto & less) {
            const auto best=std::min_element(options.begin(),options.end(),less);
            if(best!=options.end() && std::find(result.Vector().begin(),result.Vector().end(),*best)==result.Vector().end())
                result.Vector().push_back(*best);
        };
        auto timing=[](const JsonNode & a) {return std::tuple{a["day"].Integer(),a["movement_cost"].Float(),a.toCompactString()};};
        add([&](const auto & a,const auto & b){return timing(a)<timing(b);});
        add([&](const auto & a,const auto & b){return std::tuple{a["army_loss_estimate"].Integer(),timing(a)}<std::tuple{b["army_loss_estimate"].Integer(),timing(b)};});
        add([&](const auto & a,const auto & b){return std::tuple{a["army_loss_estimate"].Integer()-a["army_value"].Integer(),timing(a)}<std::tuple{b["army_loss_estimate"].Integer()-b["army_value"].Integer(),timing(b)};});
    }
    return result;
}

inline JsonNode generateScoutCandidates(const JsonNode & world,const JsonNode & plan,
    const ScoutCoverage & coverage,const CandidateRoutes & quote,const JsonNode & intent=JsonNode())
{
    JsonNode result;result["frontiers"].Vector();result["scouting"].Vector();
    std::map<std::string,JsonNode> selected;
    int64_t probes=0;
    for(const auto & hero:world["heroes"].Vector())
    {
        const auto radius=hero["sight_radius"].Integer();
        if(radius<1 || radius>64) continue;
        std::set<std::string> revealed,attempted;
        std::set<std::tuple<int64_t,int64_t,int64_t>> sectors;
        std::set<int64_t> levels;std::map<int64_t,size_t> failedLevels;
        size_t accepted=0,tries=0;
        // Nearby centers share coverage; each successful choice is ranked by
        // additional information, not by its original unseen count.
        std::map<std::string,std::set<std::string>> footprints;
        for(const auto & frontier:world["frontier_options"].Vector())
            footprints[frontier["ref"].String()]=coverage(frontier["position"],radius);
        while(accepted<SCOUT_CHOICES_PER_HERO && tries<SCOUT_PROBES_PER_HERO)
        {
            const JsonNode * best=nullptr;double bestScore=-1;bool bestNewLevel=false;
            for(const auto & frontier:world["frontier_options"].Vector())
            {
                const auto & ref=frontier["ref"].String();
                if(attempted.count(ref)) continue;
                size_t gain=0;for(const auto & tile:footprints[ref]) gain+=!revealed.count(tile);
                if(!gain) continue;
                const auto & pos=frontier["position"];
                const auto sector=std::tuple{pos[0].Integer()/(2*radius+1),pos[1].Integer()/(2*radius+1),pos[2].Integer()};
                // Screen distance is only a ranking hint; the native quote
                // below determines actual arrival and route feasibility.
                const double score=double(gain)/(1+candidateDistance(pos,hero["position"]))/(sectors.count(sector) ? 2 : 1);
                const bool newLevel=!levels.count(pos[2].Integer()) && failedLevels[pos[2].Integer()]<3;
                if(!best || newLevel>bestNewLevel || (newLevel==bestNewLevel && (score>bestScore
                    || (score==bestScore && ref<(*best)["ref"].String()))))
                {best=&frontier;bestScore=score;bestNewLevel=newLevel;}
            }
            if(!best) break;
            const auto ref=(*best)["ref"].String();attempted.insert(ref);++tries;++probes;
            const auto routes=quote((*best)["position"],true,true);
            JsonNode arrivals;arrivals.Vector();
            for(auto route:routes.Vector())
            {
                const auto army=route["army_value"].Integer(),loss=route["army_loss_estimate"].Integer();
                const auto maxLoss=plan["policy"]["max_loss_ratio"].isNumber() ? plan["policy"]["max_loss_ratio"].Float() : .25;
                if(route["hero_ref"]!=hero["ref"] || route["day"].Integer()>world["day"].Integer()+7
                    || army<=0 || loss>army*maxLoss || army-loss<hero["minimum_retained_army_value"].Integer()) continue;
                route["sight_radius"].Integer()=radius;
                route["expected_new_tiles"].Integer()=footprints[ref].size();
                arrivals.Vector().push_back(route);
            }
            if(arrivals.Vector().empty()) {++failedLevels[(*best)["position"][2].Integer()];continue;}
            // Failed screening probes do not prove the whole level unreachable.
            arrivals=representativeCandidateRoutes(arrivals);
            auto & option=selected[ref];option["ref"]=(*best)["ref"];option["position"]=(*best)["position"];
            for(const auto & arrival:arrivals.Vector())
                if(std::find(option["own_arrivals"].Vector().begin(),option["own_arrivals"].Vector().end(),arrival)==option["own_arrivals"].Vector().end())
                    option["own_arrivals"].Vector().push_back(arrival);
            revealed.insert(footprints[ref].begin(),footprints[ref].end());
            const auto & pos=(*best)["position"];
            sectors.insert({pos[0].Integer()/(2*radius+1),pos[1].Integer()/(2*radius+1),pos[2].Integer()});
            levels.insert(pos[2].Integer());
            ++accepted;
        }
    }
    // Accepted scout goals survive quotas, changed fog and inaccessible centers.
    // Their real completion is still computed against the full native world.
    for(const auto & goal:plan["goals"].Vector())
    {
        if(goal["kind"].String()!="scout_area" && goal["kind"].String()!="scout_frontier") continue;
        for(const auto & frontier:world["frontier_options"].Vector()) if(frontier["ref"]==goal["target_ref"])
        {
            auto & option=selected[frontier["ref"].String()];option=frontier;
            option["own_arrivals"]=quote(frontier["position"],true,goal["kind"].String()=="scout_area");
            for(auto & route:option["own_arrivals"].Vector()) for(const auto & hero:world["heroes"].Vector())
                if(route["hero_ref"]==hero["ref"])
                {
                    route["sight_radius"]=hero["sight_radius"];
                    route["expected_new_tiles"].Integer()=coverage(frontier["position"],hero["sight_radius"].Integer()).size();
                }
        }
    }
    for(auto & [ref,option]:selected)
    {
        JsonNode frontier=option;frontier["own_arrivals"]=quote(option["position"],true,false);
        if(!requiredCandidateRefs(world,plan,intent).count(ref)) frontier["own_arrivals"]=representativeCandidateRoutes(frontier["own_arrivals"]);
        result["frontiers"].Vector().push_back(frontier);
        if(!option["own_arrivals"].Vector().empty()) result["scouting"].Vector().push_back(option);
    }
    result["probes"].Integer()=probes;
    result["considered_centers"].Integer()=world["frontier_options"].Vector().size();
    return result;
}

inline JsonNode generateTargetCandidates(const JsonNode & world,const JsonNode & plan,const CandidateRoutes & quote,const JsonNode & intent=JsonNode())
{
    const auto required=requiredCandidateRefs(world,plan,intent);
    std::map<std::string,std::vector<JsonNode>> groups;
    std::map<std::string,JsonNode> chosen;
    auto kindGroup=[&](const JsonNode & object) {
        const auto & kind=object["kind"].String();
        if(kind=="town") return std::string("towns");
        if(kind=="hero" && object["owner"]!=world["player"]
            && (world["enemy_players"].Vector().empty() || std::find(world["enemy_players"].Vector().begin(),world["enemy_players"].Vector().end(),object["owner"])!=world["enemy_players"].Vector().end())) return std::string("interception");
        if(kind=="mine") return std::string("income");
        if(kind=="resource") return std::string("supplies");
        if(kind=="subterranean_gate" || kind=="portal") return std::string("passages");
        if(keymasterObject(object) && strategicSiteAvailable(object)) return std::string(kind=="keymaster_tent" ? "key_tents" : "key_borders");
        if(strategicSiteAvailable(object)) return std::string("sites");
        return std::string();
    };
    auto add=[&](const JsonNode & object,bool mandatory) {
        const auto ref=object["ref"].String();if(chosen.count(ref)) return false;
        const auto group=kindGroup(object);
        const auto routes=quote(object["position"],group=="passages",false);
        // The best blocked target per group remains a conditional alternative.
        JsonNode route;route["target_ref"]=object["ref"];
        route["own_arrivals"]=mandatory ? routes : representativeCandidateRoutes(routes);
        chosen.emplace(ref,route);
        for(const auto & arrival:routes.Vector())
        {
            const auto army=arrival["army_value"].Integer(),loss=arrival["army_loss_estimate"].Integer();
            const auto maxLoss=plan["policy"]["max_loss_ratio"].isNumber() ? plan["policy"]["max_loss_ratio"].Float() : .25;
            if(army>0 && loss<=army*maxLoss && arrival["day"].Integer()<=world["day"].Integer()+7) return true;
        }
        return false; // Preserve one blocked/risky alternative, then seek a usable replacement.
    };
    for(const auto & object:world["visible_objects"].Vector())
    {
        if(required.count(object["ref"].String())) {add(object,true);continue;}
        const auto group=kindGroup(object);
        if(group.empty() || (object["owner"]==world["player"] && (group=="towns" || group=="income"))) continue;
        groups[group].push_back(object);
    }
    // Garrisoned heroes and retained last-seen targets may not be visitable.
    for(const auto * key:{"heroes","towns","objects"}) for(const auto & object:world[key].Vector())
        if(required.count(object["ref"].String())) add(object,true);
    auto distance=[&](const JsonNode & object) {
        int64_t best=1000000;
        for(const auto & hero:world["heroes"].Vector()) best=std::min(best,candidateDistance(object["position"],hero["position"]));
        return best;
    };
    int64_t probes=0;
    for(auto & [group,objects]:groups)
    {
        std::sort(objects.begin(),objects.end(),[&](const auto & a,const auto & b) {
            return std::tuple{distance(a),a["ref"].String()}<std::tuple{distance(b),b["ref"].String()};
        });
        size_t accepted=0,tries=0;bool blockedOffered=false;
        for(const auto & object:objects)
        {
            if(accepted>=TARGET_CHOICES_PER_GROUP || tries>=TARGET_PROBES_PER_GROUP) break;
            ++tries;++probes;
            if(add(object,false)) ++accepted;
            else if(blockedOffered) chosen.erase(object["ref"].String());
            else blockedOffered=true;
        }
    }
    JsonNode result;result["routes"].Vector();
    for(const auto & [ref,route]:chosen) result["routes"].Vector().push_back(route);
    result["probes"].Integer()=probes;return result;
}
// The engine retains its complete observation. Only the model-facing copy is
// bounded; candidates are not a statement that unlisted objects do not exist.
inline JsonNode strategicCandidateView(const JsonNode & world,const JsonNode & plan,const JsonNode & intent=JsonNode())
{
    auto selected=requiredCandidateRefs(world,plan,intent);
    for(const auto & route:world["forecasts"]["routes"].Vector()) selected.insert(route["target_ref"].String());
    JsonNode view=world;
    view["objects"].Vector().clear();
    for(const auto & object:world["objects"].Vector())
        if(selected.count(object["ref"].String())) view["objects"].Vector().push_back(object);
    view["visible_objects"].Vector().clear();
    for(const auto & object:world["visible_objects"].Vector())
    {
        const auto & kind=object["kind"].String();
        if(selected.count(object["ref"].String()) || kind=="hero" || kind=="town" || kind=="monster"
            || kind=="garrison" || kind=="boat" || kind=="shipyard" || kind=="other" || keymasterObject(object))
            view["visible_objects"].Vector().push_back(object);
    }
    view["frontiers"].Vector().clear();
    for(const auto & option:world["frontier_options"].Vector())
        if(std::find(world["frontiers"].Vector().begin(),world["frontiers"].Vector().end(),option["ref"])!=world["frontiers"].Vector().end())
            view["frontiers"].Vector().push_back(option["ref"]);
    view["observed_frontiers"].Vector().clear();
    for(const auto & ref:world["observed_frontiers"].Vector())
        if(selected.count(ref.String())) view["observed_frontiers"].Vector().push_back(ref);
    view["candidate_generation"]["known_object_count"].Integer()=world["objects"].Vector().size();
    view["candidate_generation"]["observed_frontier_count"].Integer()=world["observed_frontiers"].Vector().size();
    view["candidate_generation"]["visible_object_count"].Integer()=world["visible_objects"].Vector().size();
    return view;
}
inline JsonNode strategicCandidateMemory(const JsonNode & memory,const JsonNode & view)
{
    std::set<std::string> selected;
    for(const auto & object:view["objects"].Vector()) selected.insert(object["ref"].String());
    auto result=memory;result["known_objects"].Vector().clear();
    for(const auto & object:memory["known_objects"].Vector())
    {
        const auto & kind=object["kind"].String();
        if(selected.count(object["ref"].String()) || kind=="hero" || kind=="town")
            result["known_objects"].Vector().push_back(object);
    }
    return result;
}

}
