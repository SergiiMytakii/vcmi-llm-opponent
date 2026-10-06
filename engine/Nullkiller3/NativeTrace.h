#pragma once

#include "../Nullkiller2/Goals/AbstractGoal.h"
#include "PlayerView.h"
#include "../../lib/callback/CCallback.h"
#include "../../lib/json/JsonNode.h"
#include "../../lib/mapObjects/CGHeroInstance.h"
#include "../../lib/mapObjects/CGTownInstance.h"

namespace nullkiller3
{
// Holding remains active, but spending movement on the same acknowledged visit
// is not progress. A new day or changed own facts permit another attempt.
inline bool unchangedHoldingAttempt(const JsonNode & memory,const std::string & goalID,int64_t revision,const JsonNode & current)
{
    auto usefulFacts=[](const JsonNode & snapshot) {
        auto facts=snapshot;
        if(facts["heroes"].isVector())
            for(auto & hero:facts["heroes"].Vector())
                if(hero.isStruct()) hero.Struct().erase("movement");
        return facts;
    };
    const auto & results=memory["recent_results"].Vector();
    for(auto it=results.rbegin();it!=results.rend();++it)
        if((*it)["action"]["goal_id"].String()==goalID)
        {
            const auto & action=(*it)["action"];
            const auto & outcome=(*it)["outcome"].String();
            return action["campaign_revision"].Integer()==revision
                && (outcome=="no_change_observed" || outcome=="effects_observed")
                && action["before"].isStruct() && action["after"].isStruct() && current.isStruct()
                && usefulFacts(action["before"])==usefulFacts(action["after"])
                && usefulFacts(action["after"])==usefulFacts(current);
        }
    return false;
}

inline JsonNode coordinate(const int3 & pos)
{
    JsonNode result;
    for(const auto value : {pos.x, pos.y, pos.z}) result.Vector().emplace_back(value);
    return result;
}

inline void traceNative(const CCallback & callback, const NK2AI::Goals::TTaskVec & tasks, int pass)
{
    JsonNode trace;
    trace["day"].Integer() = callback.getCalendar().getCurrentDay();
    trace["player"].Integer() = callback.getPlayerID()->getNum();
    trace["pass"].Integer() = pass;
    trace["resources"].String() = callback.getResourceAmount().toString();
    std::vector<const CGObjectInstance *> objects = callback.getAllVisitableObjs();
    std::ranges::sort(objects, [](const auto * a, const auto * b) {
        if(a->visitablePos() != b->visitablePos()) return a->visitablePos() < b->visitablePos();
        return a->ID < b->ID;
    });
    trace["visible_objects"].Vector();
    for(const auto * object : objects)
    {
        JsonNode item;
        item["type"].Integer() = object->ID.getNum();
        item["position"] = coordinate(object->visitablePos());
        item["owner"].Integer() = object->getOwner().getNum();
        item["army"].Integer() = observedArmyStrength(callback, object);
        item["army_interval"] = observedArmyInterval(callback,object);
        trace["visible_objects"].Vector().push_back(item);
    }
    for(const auto * hero : callback.getHeroesInfo())
    {
        JsonNode item;
        item["name"].String() = hero->getNameTextID();
        item["position"] = coordinate(hero->visitablePos());
        item["movement"].Integer() = hero->movementPointsRemaining();
        item["army"].Integer() = hero->estimateCombatValue();
        trace["heroes"].Vector().push_back(item);
    }
    trace["tasks"].Vector();
    for(const auto & task : tasks)
    {
        JsonNode item;
        const auto * goal = dynamic_cast<const NK2AI::Goals::AbstractGoal *>(task.get());
        if(!goal) continue;
        item["kind"].Integer() = goal->goalType;
        if(!goal->strategicGoalID.empty()) item["campaign_goal"].String() = goal->strategicGoalID;
        item["tile"] = coordinate(goal->tile);
        item["priority"].Float() = task->priority;
        if(goal->bid >= 0) item["building_id"].Integer() = goal->bid;
        if(const auto * hero = task->getHero()) item["hero_position"] = coordinate(hero->visitablePos());
        if(const auto * town = goal->town) item["town_position"] = coordinate(town->visitablePos());
        if(const auto * object = callback.getObj(ObjectInstanceID(goal->objid), false))
        {
            item["object_type"].Integer() = object->ID.getNum();
            item["object_position"] = coordinate(object->visitablePos());
            item["observed_army"].Integer() = observedArmyStrength(callback, object);
        }
        trace["tasks"].Vector().push_back(item);
    }
    logAi->info("NK3_NATIVE %s", trace.toCompactString());
}
}
