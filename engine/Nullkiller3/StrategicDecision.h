#pragma once
#include "CampaignState.h"
#include "RequestArbiter.h"
#include "Forecasts.h"
#include "OffensivePreparation.h"
#include <cmath>

namespace nullkiller3
{
// Policy changes alone do not create new enemy evidence. Both callers use
// this same identity; new enemy refs or strength intervals still trigger review.
inline StrategicSignal defenseSignal(const JsonNode & defense,bool actionable)
{
    std::string facts=defense["status"].String()+":";
    for(const auto & threat:defense["threats"].Vector())
    {
        facts+=threat["source_ref"].String()+":"+threat["army_interval"].toCompactString()+";";
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
    const JsonNode & freshWorld, const CampaignState & current, CampaignState & candidate, std::string & reason);
}
