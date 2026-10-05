#pragma once
#include "CampaignState.h"

namespace nullkiller3
{
// Advice from offered own routes and physical pools, never a promised future battle.
inline JsonNode offensivePreparation(const CampaignState & campaign,const JsonNode & world)
{
    JsonNode result;result["targets"].Vector();result["reinforcement_sources"].Vector();
    result["frontiers"].Vector();
    result["ready_goal_ids"].Vector();result["blocked_goal_ids"].Vector();
    const JsonNode * strongest=nullptr;
    for(const auto & hero:world["heroes"].Vector())
        if(!strongest || hero["army_value"].Integer()>(*strongest)["army_value"].Integer()) strongest=&hero;
    if(!strongest) return result;
    const auto & actor=(*strongest)["ref"];
    const auto army=(*strongest)["army_value"].Integer();
    result["hero_ref"]=actor;result["army_value"]=(*strongest)["army_value"];result["movement"]=(*strongest)["movement"];
    for(const auto & goal:campaign.plan()["goals"].Vector()) if(goal["actor_ref"]==actor)
    {
        const auto & status=world["goal_statuses"][goal["id"].String()];
        if(status["state"].String()=="ready") result["ready_goal_ids"].Vector().push_back(goal["id"]);
        else if(status["state"].String()=="blocked" || status["state"].String()=="waiting") result["blocked_goal_ids"].Vector().push_back(goal["id"]);
    }
    result["needs_idle_explanation"].Bool()=(*strongest)["movement"].Integer()>100 && result["ready_goal_ids"].Vector().empty();
    // Use the same route constraints as execution, under the accepted policy.
    // These seven-day comparisons do not certify a future plan's own deadline,
    // army minimum or newly chosen reserves; that plan is checked afresh.
    if(!campaign.plan().isNull())
    for(const auto & frontier:world["frontier_options"].Vector())
    {
        JsonNode item;item["ref"]=frontier["ref"];item["route_feedback"].Vector();
        item["deadline_day"].Integer()=world["day"].Integer()+7;
        for(const auto & hero:world["heroes"].Vector())
        {
            JsonNode goal;goal["kind"].String()="scout_frontier";goal["actor_ref"]=hero["ref"];
            goal["target_ref"]=frontier["ref"];goal["min_army_value"].Integer()=0;
            goal["deadline_day"]=item["deadline_day"];
            const auto feedback=campaign.routeFeedback(goal,world);
            JsonNode actorFeedback;
            for(const auto * field:{"actor_ref","supported","reason","assigned_routes","earliest_safe_arrival_day"})
                if(!feedback[field].isNull()) actorFeedback[field]=feedback[field];
            item["route_feedback"].Vector().push_back(actorFeedback);
        }
        result["frontiers"].Vector().push_back(item);
    }
    // Readiness uses the accepted policy. Opening decisions still receive the
    // existing complete forecasts, before any policy has been chosen.
    if(!campaign.plan().isNull())
    for(const auto & object:world["visible_objects"].Vector())
    {
        if((object["kind"].String()!="town" && object["kind"].String()!="mine") || object["owner"]==world["player"]) continue;
        JsonNode goal;goal["id"].String()="preparation";goal["kind"].String()="capture_target";
        goal["actor_ref"]=actor;goal["target_ref"]=object["ref"];goal["min_army_value"].Integer()=0;
        goal["deadline_day"].Integer()=world["day"].Integer()+7;
        const auto feedback=campaign.routeFeedback(goal,world);
        JsonNode target;target["target_ref"]=object["ref"];target["current_routes"].Vector();target["reinforced_routes"].Vector();
        for(const auto & route:feedback["assigned_routes"].Vector())
        {
            if(!route["army_value"].isNumber()) continue;
            const bool reinforced=route["army_value"].Integer()>army;
            target[reinforced ? "reinforced_routes" : "current_routes"].Vector().push_back(route);
            if(route["issues"].Vector().empty() && !reinforced
                && (target["earliest_current_safe_day"].isNull() || route["day"].Integer()<target["earliest_current_safe_day"].Integer()))
                target["earliest_current_safe_day"]=route["day"];
        }
        target["after_separate_reinforcement"].String()="unknown: meeting time, stack packing and subsequent route must be recalculated";
        target["reinforced_route_assumptions"].String()="Offered native path army above the current army requires its native exchanges; separate source options do not prove this attack route.";
        result["targets"].Vector().push_back(target);
    }
    std::set<std::string> offeredPools;
    auto offerSource=[&](const JsonNode & town,bool isTown)
    {
        const auto poolRef=CampaignState::armyPool(town["ref"].String(),world);
        if((poolRef==actor.String() && !isTown) || !offeredPools.insert(poolRef).second) return;
        JsonNode source;source["source_ref"]=town["ref"];source["army_pool_ref"].String()=poolRef;
        source["kind"].String()=isTown ? "town" : "hero";source["meeting_routes"].Vector();
        for(const auto & pool:world["forecasts"]["army_pools"].Vector())
            if(pool["holder_ref"].String()==poolRef && poolRef!=actor.String()) source["unpledged_army_value"]=pool["unpledged_now"];
        for(const auto & alternative:world["forecasts"]["alternatives"].Vector())
            if(alternative["approach"].String()=="offense" && alternative["town_ref"]==town["ref"])
                source["fundable_recruitment_value"]=alternative["army_purchased_value"];
        for(const auto & entry:world["forecasts"]["routes"].Vector())
            for(const auto & route:entry["own_arrivals"].Vector())
                if((entry["target_ref"]==town["ref"] && route["hero_ref"]==actor)
                    || (!isTown && entry["target_ref"]==actor && route["hero_ref"]==town["ref"]))
                {
                    JsonNode meeting=route;meeting["destination_ref"]=entry["target_ref"];
                    source["meeting_routes"].Vector().push_back(meeting);
                }
        source["status"].String()=source["meeting_routes"].Vector().empty() ? "meeting_route_unknown" : "conditional_meeting";
        source["assumptions"].String()="Independent source alternative, not a joint allocation. Retained defense, losses, funds, stack packing and delivery remain native constraints; no post-meeting attack is promised.";
        if(source["unpledged_army_value"].Integer()>0 || source["fundable_recruitment_value"].Integer()>0)
            result["reinforcement_sources"].Vector().push_back(source);
    };
    for(const auto & town:world["towns"].Vector()) offerSource(town,true);
    for(const auto & hero:world["heroes"].Vector()) offerSource(hero,false);
    return result;
}

inline JsonNode offensiveCheckpoint(const JsonNode & preparation)
{
    JsonNode result;result["hero_ref"]=preparation["hero_ref"];result["army_value"]=preparation["army_value"];
    return result;
}
}
