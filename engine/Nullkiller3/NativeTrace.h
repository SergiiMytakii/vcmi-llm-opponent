#pragma once

#include "../Nullkiller2/Goals/AbstractGoal.h"
#include "PlayerView.h"
#include "../../lib/callback/CCallback.h"
#include "../../lib/json/JsonNode.h"
#include "../../lib/mapObjects/CGHeroInstance.h"
#include "../../lib/mapObjects/CGTownInstance.h"

namespace nullkiller3
{
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
