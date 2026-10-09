#pragma once

#include "json/JsonNode.h"
#include "ObservedPassages.h"
#include "StrategicIntent.h"
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
inline bool validSavedArtifactEvent(const JsonNode & event)
{
    return validArtifactVisitEvidence(event) && event.toCompactString().size()<=32768
        && savedInteger(event["day"],1,2147483647) && savedInteger(event["target_id"],0,1000000000)
        && savedPosition(event["position"]) && event["goal"]["id"].isString() && !event["goal"]["id"].String().empty()
        && event["goal"]["id"].String().size()<=120 && event["goal"]["actor_ref"].isString()
        && event["goal"]["actor_ref"].String().size()<=160 && event["goal"]["target_ref"].isString()
        && !event["goal"]["target_ref"].String().empty() && event["goal"]["target_ref"].String().size()<=160;
}
inline bool validPendingTask(const JsonNode & task)
{
    if(task.isNull()) return true;
    if(!task.isStruct() || !savedInteger(task["version"],1,1) || !validExecutionSnapshot(task["before"]) || !task["action"].isStruct()) return false;
    const auto & action=task["action"];
    const auto & operative=action["goal"];
    if(!operative.isNull() && (!operative.isStruct() || operative.toCompactString().size()>8192
        || operative["id"]!=action["goal_id"] || !intentText(operative["kind"],120)
        || !intentText(operative["target_ref"],160) || (!operative["actor_ref"].isNull() && !intentText(operative["actor_ref"],160))
        || !savedInteger(operative["deadline_day"],1,2147483647) || !operative["complete_when"].isStruct())) return false;
    if(!action["campaign_revision"].isNull() && !savedInteger(action["campaign_revision"],operative.isNull() ? 0 : 1,2147483647)) return false;
    const auto & artifact=action["artifact_visit"];
    if(!artifact.isNull())
    {
        if(!validSavedArtifactEvent(artifact) || artifact["goal"]["id"]!=action["goal_id"] || (!operative.isNull() && artifact["goal"]!=operative)) return false;
        bool owned=false;
        for(const auto & hero:task["before"]["heroes"].Vector()) owned |= hero["ref"]==artifact["goal"]["actor_ref"];
        if(!owned) return false;
    }
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
inline bool validQuestionCoverage(const JsonNode & coverage,const JsonNode & campaign,const JsonNode & intent)
{
    if(!coverage.isVector() || coverage.Vector().size()>6) return false;
    std::set<std::string> questions;
    for(const auto & item:coverage.Vector())
    {
        if(!intentFields(item,{"question","facts","milestone_id","campaign_revision","goal_ids"})
            || !intentText(item["question"],240) || !item["facts"].isString() || item["facts"].String().size()>8192
            || !intentText(item["milestone_id"],120) || item["question"].String()!="strategy:no_progress:"+item["milestone_id"].String()
            || !questions.insert(item["question"].String()).second || !savedInteger(item["campaign_revision"],1,2147483647)
            || item["campaign_revision"]!=campaign["revision"] || intentMilestone(intent,item["milestone_id"]).isNull()
            || !item["goal_ids"].isVector() || item["goal_ids"].Vector().empty() || item["goal_ids"].Vector().size()>12) return false;
        std::set<std::string> ids;
        for(const auto & id:item["goal_ids"].Vector())
        {
            if(!intentText(id,120) || !ids.insert(id.String()).second) return false;
            bool found=false;
            for(const auto & goal:campaign["goals"].Vector()) found |= goal["id"]==id;
            if(!found) return false;
        }
    }
    return true;
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
    if(!validSavedStrategicIntent(saved["strategic_intent"]))
    {
        result.Struct().erase("strategic_intent");
        if(result["strategy_metadata"].isStruct()) { result["strategy_metadata"].Struct().erase("operation_focus");result["strategy_metadata"].Struct().erase("decision_basis"); }
    }
    // An invalid optional pickup proof cannot discard an otherwise valid
    // pending native command or rerun it. Drop only that untrusted proof.
    if(!saved["pending_native_task"]["action"]["artifact_visit"].isNull()
        && !validPendingTask(result["pending_native_task"]))
        result["pending_native_task"]["action"].Struct().erase("artifact_visit");
    if(saved["site_receipts"].isStruct())
        std::erase_if(result["site_receipts"].Struct(),[](const auto & entry) {
            const auto & receipt=entry.second;const auto & proof=receipt["artifact_visit"];
            return !proof.isNull() && (!validSavedArtifactEvent(proof) || !artifactVisitConfirmed(proof)
                || proof["goal"]!=receipt["goal"] || proof["day"]!=receipt["day"]);
        });
    const JsonNode & checkedResult=result;
    bool invalid=!validNativeAliases(saved["object_ids"]) || !validPendingTask(result["pending_native_task"])
        || !validObservedPassages(saved["observed_passages"]);
    const auto & checkpoint=saved["checkpoint_baseline"];
    if(!checkpoint.isNull())
        invalid |= !checkpoint.isStruct() || (checkpoint.Struct().size()!=2 && checkpoint.Struct().size()!=3)
            || !savedInteger(checkpoint["day"],1,2147483647) || !checkpoint["facts"].isString()
            || checkpoint["facts"].String().size()>8192;
    if(!checkpoint["offense"].isNull())
    {
        const auto & offense=checkpoint["offense"];
        invalid |= !offense.isStruct() || offense.Struct().size()!=2
            || (!offense["hero_ref"].isNull() && (!offense["hero_ref"].isString() || offense["hero_ref"].String().size()>240))
            || (!offense["army_value"].isNull() && !savedInteger(offense["army_value"],0,1000000000000LL));
    }
    for(const auto * field:{"confirmed_border_visits","confirmed_resource_pickups","frontier_positions","local_repairs","delivery_receipts","passage_receipts","site_receipts","helper_hire_receipts","goal_blockers"})
        invalid |= !saved[field].isNull() && !saved[field].isStruct();
    if(saved["confirmed_border_visits"].isStruct())
        for(const auto & [ref,day]:saved["confirmed_border_visits"].Struct()) invalid |= !savedInteger(day,1,2147483647);
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
            if(!item["support"].isNull())
            {
                const auto & support=item["support"];
                invalid |= !intentFields(support,{"owned","day","treasury","available","remaining_cost","base_income"})
                    || !support["owned"].isBool() || !savedInteger(support["day"],1,2147483647);
                for(const auto * field:{"treasury","available","remaining_cost","base_income"})
                {
                    invalid |= !support[field].isVector() || support[field].Vector().size()!=7;
                    for(const auto & value:support[field].Vector()) invalid |= !savedInteger(value,0,1000000000000LL);
                }
            }

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
    for(const auto * field:{"local_repairs","delivery_receipts","passage_receipts","site_receipts","helper_hire_receipts","goal_blockers"})
        if(checkedResult[field].isStruct()) for(const auto & [id,item]:checkedResult[field].Struct())
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
            if(std::string(field)=="site_receipts")
                invalid |= (item.Struct().size()!=2 && (item.Struct().size()!=3 || !item.Struct().count("artifact_visit"))) || !item["goal"].isStruct() || !savedInteger(item["day"],1,2147483647)
                    || (!item["artifact_visit"].isNull() && (!validSavedArtifactEvent(item["artifact_visit"])
                        || !artifactVisitConfirmed(item["artifact_visit"]) || item["artifact_visit"]["goal"]!=item["goal"]
                        || item["artifact_visit"]["day"]!=item["day"]));
            if(std::string(field)=="helper_hire_receipts")
                invalid |= item.Struct().size()!=4 || !item["goal"].isStruct() || item["goal"]["kind"].String()!="hire_helper"
                    || !savedInteger(item["day"],1,2147483647) || !item["hero_ref"].isString() || item["hero_ref"].String().empty()
                    || item["hero_ref"].String().size()>120 || !savedInteger(item["hero_type_id"],0,1000000)
                    || item["goal"]["candidate_ref"].String()!="tavern:"+std::to_string(item["hero_type_id"].Integer());
            if(std::string(field)=="passage_receipts")
                invalid |= !item["goal"].isStruct() || !savedInteger(item["day"],1,2147483647)
                    || !savedPosition(item["from"]) || !savedPosition(item["to"])
                    || (savedPosition(item["from"]) && savedPosition(item["to"]) && item["from"][2]==item["to"][2]);
        }
    const auto & metadata=saved["strategy_metadata"];
    if(!metadata.isNull())
    {
        invalid |= !metadata.isStruct();
        invalid |= !metadata["decision_basis"].isNull() && !validDecisionBasis(metadata["decision_basis"]);
        if(metadata.isStruct())
        {
            invalid |= !metadata["assignments"].isVector();
            if(metadata["assignments"].isVector()) for(const auto & assignment:metadata["assignments"].Vector())
            {
                invalid |= !assignment.isStruct();
                if(!assignment.isStruct()) continue;
                invalid |= !assignment["hero_ref"].isString() || !assignment["role"].isString();
                // Older saves carry redundant goal IDs; validate before discarding.
                invalid |= !assignment["goal_ids"].isNull() && !assignment["goal_ids"].isVector();
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
        for(const auto * field:{"object_ids","memory","native_campaign","strategic_intent","strategy_metadata","local_repairs",
                               "delivery_receipts","passage_receipts","site_receipts","helper_hire_receipts","observed_passages","goal_blockers","frontier_positions","confirmed_border_visits","confirmed_resource_pickups","pending_native_task","building_progress","operation_progress","checkpoint_baseline"})
            result.Struct().erase(field);
    // A discarded installed course is a new native fact. Reopen just its
    // initialization question; consumed budget and every other baseline survive.
    // A null course after timeout/rejection keeps its addressed baseline.
    if(!saved["strategic_intent"].isNull() && static_cast<const JsonNode &>(result)["strategic_intent"].isNull()
        && saved["request_arbiter"]["addressed"].isStruct())
        result["request_arbiter"]["addressed"].Struct().erase("initial_strategy");
    if(result["strategy_metadata"].isStruct())
    {
        const std::set<std::string> kept{"decision","reason","victory_method","assignments","reconsider_when","defense_exit","operation_focus","decision_basis","question_coverage"};
        std::erase_if(result["strategy_metadata"].Struct(),[&](const auto & item) { return !kept.count(item.first); });
        if(result["strategic_intent"].isNull()) { result["strategy_metadata"].Struct().erase("operation_focus");result["strategy_metadata"].Struct().erase("decision_basis"); }
    }
    if(result["strategy_metadata"].isStruct())
    {
        const auto & coverage=static_cast<const JsonNode &>(result)["strategy_metadata"]["question_coverage"];
        if(!coverage.isNull() && !validQuestionCoverage(coverage,result["native_campaign"]["plan"],result["strategic_intent"]))
            result["strategy_metadata"].Struct().erase("question_coverage");
    }
    if(result["strategy_metadata"].isStruct())
        for(auto & assignment:result["strategy_metadata"]["assignments"].Vector())
            assignment.Struct().erase("goal_ids");
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
