#pragma once
#include "CampaignState.h"
#include "StrategicIntent.h"
#include "RequestArbiter.h"
#include "Forecasts.h"
#include "OffensivePreparation.h"
#include <cmath>

namespace nullkiller3
{
inline StrategicSignal automaticSafetySignal(const JsonNode & review,int64_t day,bool actionable)
{
    auto facts=review;
    bool comparable=review["reason"].String()=="automatic_helper_approaches_stronger_visible_enemy"
        && review["origin"].Vector().size()==3 && review["stop_positions"].Vector().size()==1
        && review["stop_positions"][0].Vector().size()==3;
    for(const auto & threat:review["visible_threats"].Vector())
    {
        const auto & scenario=threat["known_land_approach"]["movement_scenario"];
        comparable &= scenario["status"].String()=="conditional_direct_land_approach"
            && scenario["turns"].isNumber() && scenario["turns"].Integer()>0;
    }
    if(review["reason"].String()=="automatic_helper_approaches_stronger_visible_enemy")
    {
        facts.Struct().erase("basis");facts.Struct().erase("coverage");
        for(auto & threat:facts["visible_threats"].Vector())
        {
            const auto & scenario=static_cast<const JsonNode &>(threat)["known_land_approach"]["movement_scenario"];
            // Static prose stays in the observation, outside saved fact identity.
            if(scenario.isStruct())
            {
                auto identity=scenario;identity.Struct().erase("assumptions");
                // Store the three native scenario values without repeating keys
                // per enemy; this identity also fits the saved arbiter limit.
                if(identity.Struct().size()==3 && identity["status"].String()=="conditional_direct_land_approach"
                    && identity["turns"].isNumber() && identity["daily_points"].isNumber())
                {
                    JsonNode values;
                    for(const auto * key:{"status","turns","daily_points"}) values.Vector().push_back(identity[key]);
                    identity=std::move(values);
                }
                threat["known_land_approach"]["movement_scenario"]=std::move(identity);
            }
            if(static_cast<const JsonNode &>(threat)["army_interval"].isStruct())
                threat["army_interval"].Struct().erase("basis");
        }
    }
    if(comparable)
    {
        // Compare the reviewed threat, not each ordinary route waypoint.
        // Conditional approach turns are a review boundary, never a safety grant.
        facts["review_day"].Integer()=day;
        facts["origin_level"]=review["origin"][2];
        facts["stop_level"]=review["stop_positions"][0][2];
        facts.Struct().erase("origin");facts.Struct().erase("stop_positions");
        for(auto & threat:facts["visible_threats"].Vector())
        {
            threat.Struct().erase("tile_distance");
            threat["known_land_approach"].Struct().erase("known_land_steps");
        }
        auto & threats=facts["visible_threats"].Vector();
        std::sort(threats.begin(),threats.end(),[](const auto & a,const auto & b) {
            return a["enemy_ref"].String()<b["enemy_ref"].String();
        });
    }
    return {"automatic_safety:"+review["hero_ref"].String(),facts.toCompactString(),true,true,actionable,
        review["reason"].String()=="passage_crossing_requires_fresh_decision"};
}
inline JsonNode controllerFailureFeedback(const JsonNode & reply,const JsonNode & request)
{
    auto shape=[](const JsonNode & value,std::initializer_list<const char *> keys) {
        if(!value.isStruct() || value.Struct().size()!=keys.size()) return false;
        for(const auto * key:keys) if(!value.Struct().count(key)) return false;
        return true;
    };
    auto integer=[](const JsonNode & value) { return value.getType()==JsonNode::JsonType::DATA_INTEGER && value.Integer()>=0; };
    if(!shape(reply,{"protocol","request_id","identity","failure","usage"}) || !integer(reply["protocol"])
        || reply["protocol"].Integer()!=2 || !reply["request_id"].isString() || reply["request_id"]!=request["request_id"]
        || reply["identity"]!=request["identity"] || !reply["identity"].isStruct()) return JsonNode();
    for(const auto & [key,value]:request["identity"].Struct())
        if(reply["identity"][key].getType()!=value.getType()) return JsonNode();
    const auto & failure=reply["failure"], &usage=reply["usage"];
    if(!shape(failure,{"code","required","available"}) || !failure["code"].isString()
        || failure["code"].String()!="resource_commitments_exceed_available_funds"
        || !shape(usage,{"known","input_tokens","output_tokens"}) || !usage["known"].isBool()
        || !integer(usage["input_tokens"]) || !integer(usage["output_tokens"])) return JsonNode();
    if(!failure["required"].isVector() || !failure["available"].isVector()
        || failure["required"].Vector().size()!=7 || failure["available"].Vector().size()!=7
        || failure["available"]!=request["observation"]["resources"]) return JsonNode();
    bool exceeded=false;
    for(int i=0;i<7;++i)
    {
        if(!integer(failure["required"][i]) || !integer(failure["available"][i])) return JsonNode();
        exceeded |= failure["required"][i].Integer()>failure["available"][i].Integer();
    }
    return exceeded ? failure : JsonNode();
}
// Policy changes alone do not create new enemy evidence. Both callers use
// this same identity; new enemy refs, strength or approach turns trigger review.
inline StrategicSignal defenseSignal(const JsonNode & defense,bool actionable)
{
    std::string facts=defense["status"].String()+":";
    for(const auto & threat:defense["threats"].Vector())
    {
        facts+=threat["source_ref"].String()+":"+threat["army_interval"].toCompactString()+";";
        facts+=threat["movement_scenario"]["turns"].toCompactString()+";";
        if(!threat["neutral_screen"].isNull())
            facts+=threat["neutral_screen"]["status"].String()+":"+threat["neutral_screen"]["example_guard_refs"].toCompactString()+";";
    }
    return {"defense:"+defense["town_ref"].String(),facts,true,true,actionable,true};
}
inline std::vector<StrategicSignal> allocationCheckpointSignals(const CampaignState & campaign,
    const JsonNode & world,const JsonNode & baseline,bool actionable)
{
    if(campaign.plan().isNull() || baseline.isNull()) return {};
    const auto day=world["day"].Integer();
    const auto week=std::max<int64_t>(1,world["days_in_week"].Integer());
    if(day<baseline["day"].Integer()+3 && day%week!=0) return {};
    const auto facts=allocationCheckpointFacts(campaign,world);
    if(facts.empty() || facts==baseline["facts"].String()) return {};
    return {{"checkpoint:allocation",facts,true,true,actionable,false}};
}
inline std::vector<StrategicSignal> offensiveCheckpointSignals(const JsonNode & world,const JsonNode & baseline,bool actionable)
{
    const auto & previous=baseline["offense"];
    const auto now=offensiveCheckpoint(world["offensive_preparation"]);
    if(!previous.isNull() && previous["hero_ref"]==now["hero_ref"] && previous["army_value"].Integer()>0
        && now["army_value"].Integer()>=previous["army_value"].Integer()*1.25)
        if(!world["offensive_preparation"]["targets"].Vector().empty())
            return {{"checkpoint:offense",now.toCompactString(),true,true,actionable,false}};
    return {};
}
std::vector<StrategicSignal> helperHiredSignals(const CampaignState & campaign,const JsonNode & world,bool actionable);
inline JsonNode operationIdentity(const JsonNode & goal)
{
    JsonNode result;
    for(const auto * field:{"kind","actor_ref","target_ref","min_army_value","required_capabilities","complete_when"}) result[field]=goal[field];
    if(goal["kind"].String()=="hire_helper")
        for(const auto * field:{"candidate_ref","helper_role","job_ref"}) result[field]=goal[field];
    return result;
}
// Native admission owns this refusal. A geometric route alone cannot clear it;
// generate() must admit a fresh task, or a new plan must replace the operation.
void retainDefenseExecutionBlockers(CampaignState & campaign, JsonNode & world, const JsonNode & blockers);
JsonNode mainArmyIdle(const CampaignState & campaign,const JsonNode & world);
inline bool idleArmyNeedsReview(const JsonNode & idle)
{
    const auto & reason=idle["reason"].String();
    return reason=="no_task" || reason=="no_safe_route" || reason=="execution_blocked";
}
std::vector<StrategicSignal> idleArmySignals(const CampaignState & campaign,const JsonNode & world,bool actionable);
// Only the operation's own participants, not routine treasury changes or
// unrelated construction, establish whether an acknowledged task progressed.
JsonNode operationOwnFacts(const JsonNode & goal,const JsonNode & own,const std::string & source);
inline bool operationStalled(const JsonNode & progress,const JsonNode & forecasts,const std::string & id,int64_t day)
{
    if(progress.isNull() || day<progress["last_progress_day"].Integer()+2
        || progress["last_no_change_day"].isNull()
        || progress["last_no_change_day"].Integer()<progress["last_progress_day"].Integer()+1) return false;
    for(const auto & delivery:forecasts["deliveries"].Vector())
        if(delivery["goal_id"].String()==id && delivery["status"].String()=="conditional")
            for(const auto & purchase:delivery["recruitment_schedule"].Vector())
                if(purchase["day"].Integer()>=day) return false;
    return true;
}
JsonNode operationProgress(const JsonNode & previous,const JsonNode & objective,const JsonNode & facts,int64_t day);
std::vector<StrategicSignal> criticalTownLossSignals(const JsonNode & plan,const JsonNode & world,bool actionable);
// A battle's acknowledged own casualties can disprove the accepted risk
// estimate even if no preservation goal names that hero. Net army changes,
// transfers and unknown saved commands are not combat evidence.
std::vector<StrategicSignal> battleLossSignals(const JsonNode & plan, const JsonNode & memory, bool actionable);
// A newly numbered plan is not a newly observed problem. Aggregate semantic
// blockers independently of goal IDs, deadlines, prose and revision numbers.
std::vector<StrategicSignal> operationTransferSignals(const CampaignState & campaign,const JsonNode & world,const JsonNode & memory,bool actionable);
std::string repairQuestionFacts(const JsonNode & plan, const JsonNode & blockers, const JsonNode & statuses);
// Only this value contract can install model policy. The caller supplies a
// fresh world and matching identity after reacquiring the game-state lock.
bool validateStrategicDecision(const JsonNode & reply, const JsonNode & request,
    const JsonNode & freshWorld, const CampaignState & current, CampaignState & candidate, std::string & reason,
    JsonNode * nextIntentOut=nullptr, const JsonNode * currentIntent=nullptr);
}
