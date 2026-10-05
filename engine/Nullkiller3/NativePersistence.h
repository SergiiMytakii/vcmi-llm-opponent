#pragma once

#include "json/JsonNode.h"
#include <charconv>
#include <set>

namespace nullkiller3
{
inline bool savedInteger(const JsonNode & value, int64_t low, int64_t high)
{
    return value.getType()==JsonNode::JsonType::DATA_INTEGER && value.Integer()>=low && value.Integer()<=high;
}
inline bool validNativeAliases(const JsonNode & aliases)
{
    if(!aliases.isStruct()) return false;
    std::set<int64_t> labels;
    for(const auto & [key,value]:aliases.Struct())
    {
        int id=0;
        const auto parsed=std::from_chars(key.data(),key.data()+key.size(),id);
        if(parsed.ec!=std::errc{} || parsed.ptr!=key.data()+key.size() || id<0
            || key!=std::to_string(id) || !savedInteger(value,0,1000000000)
            || !labels.insert(value.Integer()).second) return false;
    }
    return true;
}
inline bool savedPosition(const JsonNode & value)
{
    if(!value.isVector() || value.Vector().size()!=3) return false;
    for(const auto & axis:value.Vector()) if(!savedInteger(axis,0,100000)) return false;
    return true;
}
inline bool validExecutionSnapshot(const JsonNode & snapshot)
{
    if(!snapshot.isStruct() || !savedInteger(snapshot["day"],1,2147483647) || !savedInteger(snapshot["player"],0,7)
        || !snapshot["resources"].isVector() || snapshot["resources"].Vector().size()!=7) return false;
    for(const auto & resource:snapshot["resources"].Vector()) if(!savedInteger(resource,0,1000000000000LL)) return false;
    for(const auto * list:{"heroes","towns"})
    {
        if(!snapshot[list].isVector() || snapshot[list].Vector().size()>512) return false;
        std::set<std::string> refs;
        for(const auto & item:snapshot[list].Vector())
        {
            if(!item.isStruct() || !item["ref"].isString() || item["ref"].String().empty() || item["ref"].String().size()>240
                || !refs.insert(item["ref"].String()).second || !savedInteger(item["army_value"],0,1000000000000LL)) return false;
            if(std::string(list)=="heroes" && (!savedPosition(item["position"])
                || (!item["in_boat"].isNull() && !item["in_boat"].isBool()))) return false;
            if(std::string(list)=="towns")
            {
                if(!item["army_holder_ref"].isString() || item["army_holder_ref"].String().empty()
                    || item["army_holder_ref"].String().size()>240 || !item["buildings"].isVector() || item["buildings"].Vector().size()>512) return false;
                for(const auto & building:item["buildings"].Vector()) if(!savedInteger(building,0,100000)) return false;
            }
        }
    }
    return true;
}
inline bool validPendingTask(const JsonNode & task)
{
    if(task.isNull()) return true;
    if(!task.isStruct() || !savedInteger(task["version"],1,1) || !validExecutionSnapshot(task["before"]) || !task["action"].isStruct()) return false;
    const auto & action=task["action"];
    const auto & emergency=action["emergency"];
    if(!emergency.isNull())
    {
        if(!emergency.isStruct() || !emergency["town_ref"].isString() || !emergency["reason"].isString()
            || emergency["reason"].String().size()>512) return false;
        bool owned=false;
        for(const auto & town:task["before"]["towns"].Vector()) owned |= town["ref"]==emergency["town_ref"];
        if(!owned) return false;
        for(const auto * field:{"planned_cost","reserved_before","legacy_locks_before"})
        {
            if(!emergency[field].isVector() || emergency[field].Vector().size()!=7) return false;
            for(const auto & amount:emergency[field].Vector()) if(!savedInteger(amount,0,1000000000000LL)) return false;
        }
    }
    const std::set<std::string> kinds{"build","recruit","hire_hero","visit","native_task"};
    return action["kind"].isString() && kinds.count(action["kind"].String()) && action["goal_id"].isString()
        && action["goal_id"].String().size()<=120 && savedInteger(action["native_goal_type"],-1,100000);
}
// Restore only a coherent object-label namespace. Resetting labels while
// retaining their old intentions would silently redirect commands to new objects.
// The request budget is independent and survives every intent reset.
inline JsonNode restoreNativeNamespace(const JsonNode & saved)
{
    if(saved.isNull()) return {};
    if(!saved.isStruct())
    {
        JsonNode result;
        result["request_arbiter"].String()="invalid_saved_namespace";
        return result; // Unknown consumed budget cannot become fresh allowance.
    }
    JsonNode result=saved;
    bool invalid=!validNativeAliases(saved["object_ids"]) || !validPendingTask(saved["pending_native_task"]);
    const auto & checkpoint=saved["checkpoint_baseline"];
    if(!checkpoint.isNull())
        invalid |= !checkpoint.isStruct() || checkpoint.Struct().size()!=2
            || !savedInteger(checkpoint["day"],1,2147483647) || !checkpoint["facts"].isString()
            || checkpoint["facts"].String().size()>8192;
    for(const auto * field:{"confirmed_resource_pickups","frontier_positions","local_repairs","delivery_receipts","goal_blockers"})
        invalid |= !saved[field].isNull() && !saved[field].isStruct();
    if(saved["confirmed_resource_pickups"].isStruct())
        for(const auto & [ref,day]:saved["confirmed_resource_pickups"].Struct()) invalid |= !savedInteger(day,1,2147483647);
    if(saved["frontier_positions"].isStruct())
        for(const auto & [ref,position]:saved["frontier_positions"].Struct()) invalid |= !savedPosition(position);
    if(!saved["building_progress"].isNull())
    {
        invalid |= !saved["building_progress"].isStruct();
        if(saved["building_progress"].isStruct()) for(const auto & [key,item]:saved["building_progress"].Struct())
        {
            invalid |= key.empty() || key.size()>240 || !item.isStruct();
            if(!item.isStruct()) continue;
            invalid |= !savedInteger(item["last_progress_day"],1,2147483647) || !item["remaining"].isVector();
            if(item["remaining"].isVector())
            {
                invalid |= item["remaining"].Vector().size()>512;
                for(const auto & building:item["remaining"].Vector()) invalid |= !savedInteger(building,0,100000);
            }
        }
    }
    if(!saved["operation_progress"].isNull())
    {
        invalid |= !saved["operation_progress"].isStruct();
        if(saved["operation_progress"].isStruct()) for(const auto & [id,item]:saved["operation_progress"].Struct())
        {
            invalid |= id.empty() || id.size()>120 || !item.isStruct();
            if(!item.isStruct()) continue;
            invalid |= !item["objective"].isStruct() || !item["facts"].isStruct()
                || item["objective"].toCompactString().size()>2048 || item["facts"].toCompactString().size()>2048
                || !savedInteger(item["last_progress_day"],1,2147483647)
                || (!item["best_route_cost"].isNull() && !savedInteger(item["best_route_cost"],0,2147483647))
                || (!item["last_no_change_day"].isNull() && !savedInteger(item["last_no_change_day"],1,2147483647));
        }
    }
    for(const auto * field:{"local_repairs","delivery_receipts","goal_blockers"})
        if(saved[field].isStruct()) for(const auto & [id,item]:saved[field].Struct())
        {
            invalid |= !item.isStruct();
            if(!item.isStruct()) continue;
            if(std::string(field)=="local_repairs")
                invalid |= !item["kind"].isString() || !item["from"].isString() || !item["to"].isString()
                    || !savedInteger(item["revision"],1,2147483647);
            if(std::string(field)=="goal_blockers")
                invalid |= !item["reason"].isString() || !savedInteger(item["revision"],1,2147483647)
                    || (!item["route_turns"].isNull() && !savedInteger(item["route_turns"],0,2147483647));
            if(std::string(field)=="delivery_receipts") invalid |= !item["goal"].isStruct();
        }
    const auto & metadata=saved["strategy_metadata"];
    if(!metadata.isNull())
    {
        invalid |= !metadata.isStruct();
        if(metadata.isStruct())
        {
            invalid |= !metadata["assignments"].isVector();
            if(metadata["assignments"].isVector()) for(const auto & assignment:metadata["assignments"].Vector())
            {
                invalid |= !assignment.isStruct();
                if(!assignment.isStruct()) continue;
                invalid |= !assignment["hero_ref"].isString() || !assignment["role"].isString() || !assignment["goal_ids"].isVector();
                if(assignment["goal_ids"].isVector()) for(const auto & id:assignment["goal_ids"].Vector()) invalid |= !id.isString();
            }
        }
    }
    const auto & memory=saved["memory"];
    if(!memory.isNull())
    {
        invalid |= !memory.isStruct();
        if(memory.isStruct())
        {
            invalid |= !savedInteger(memory["schema"],2,2);
            for(const auto * field:{"known_objects","own_heroes","recent_results","own_force_changes"})
            {
                invalid |= !memory[field].isNull() && !memory[field].isVector();
                if(memory[field].isVector()) for(const auto & item:memory[field].Vector())
                {
                    invalid |= !item.isStruct();
                    if(!item.isStruct()) continue;
                    if(std::string(field)=="known_objects")
                        invalid |= !item["ref"].isString() || !item["kind"].isString()
                            || !savedInteger(item["last_seen_day"],1,2147483647) || !savedPosition(item["position"])
                            || (!item["stale"].isNull() && !item["stale"].isBool())
                            || (!item["not_seen_at_last_position"].isNull() && !item["not_seen_at_last_position"].isBool());
                    if(std::string(field)=="own_heroes") invalid |= !savedInteger(item["id"],0,1000000000);
                    if(std::string(field)=="recent_results")
                        invalid |= !savedInteger(item["sequence"],0,2147483647) || !savedInteger(item["day"],1,2147483647)
                            || !item["outcome"].isString() || !item["action"].isStruct();
                }
            }
            // ExternalAI's executable plan is not the NK3 campaign. Native
            // intentions are restored exclusively through CampaignState.
            invalid |= !memory["plan"].isNull() || !memory["campaign"].isNull();
        }
    }
    if(invalid)
        for(const auto * field:{"object_ids","memory","native_campaign","strategy_metadata","local_repairs",
                               "delivery_receipts","goal_blockers","frontier_positions","confirmed_resource_pickups","pending_native_task","building_progress","operation_progress","checkpoint_baseline"})
            result.Struct().erase(field);
    // Derived ExternalAI review snapshots are rebuilt from the next complete
    // own list. Facts, history, aliases and spent budget remain durable.
    if(result["memory"].isStruct())
        for(const auto * field:{"plan_tracking","plan_review","campaign_review","campaign_observed"})
            result["memory"].Struct().erase(field);
    if(!result["request_sequence"].isNull() && !savedInteger(result["request_sequence"],0,2147483646))
    {
        result["request_sequence"].Integer()=0;
        result["request_arbiter"].String()="invalid_saved_request_sequence";
    }
    return result;
}
}
