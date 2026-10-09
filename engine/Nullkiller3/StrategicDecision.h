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
// Match existing native source quotes; do not duplicate stack packing or
// minimum-retained force forecasts in the controller's role contract.
inline bool supportedMainDelivery(const JsonNode & goal,const CampaignState & campaign,
    const JsonNode & world,const JsonNode & previous)
{
    const auto & actor=goal["actor_ref"], &source=goal["target_ref"];
    int64_t recipient=0;for(const auto & hero:world["heroes"].Vector()) if(hero["ref"]==actor) recipient=hero["army_value"].Integer();
    if(recipient>=goal["complete_when"]["value"].Integer()) return false;
    const auto pool=CampaignState::armyPool(source.String(),world);
    if(pool==actor.String()) return false;
    std::set<std::string> aliases{pool,source.String()};bool townSource=false;
    for(const auto & town:world["towns"].Vector())
    {
        townSource |= town["ref"]==source;
        if(CampaignState::armyPool(town["ref"].String(),world)==pool) aliases.insert(town["ref"].String());
    }
    for(const auto & other:campaign.plan()["goals"].Vector())
    {
        if(other["id"]==goal["id"] || (!aliases.count(other["actor_ref"].String()) && !aliases.count(other["target_ref"].String()))) continue;
        bool unchanged=false;
        for(const auto & old:previous["goals"].Vector()) unchanged |= CampaignState::sameGoal(other,old);
        if(!unchanged) return false;
        JsonNode before,after;before.Vector();after.Vector();
        for(const auto & reserve:previous["reserves"].Vector()) if(reserve["goal_id"]==other["id"]) before.Vector().push_back(reserve);
        for(const auto & reserve:campaign.plan()["reserves"].Vector()) if(reserve["goal_id"]==other["id"]) after.Vector().push_back(reserve);
        if(before!=after) return false;
    }
    for(const auto & commander:world["offensive_preparation"]["commander_options"].Vector())
    {
        if(commander["ref"]!=actor) continue;
        for(const auto & quote:commander["reinforcement_sources"].Vector())
        {
            if(quote["source_ref"]!=source || quote["status"].String()!="conditional_meeting") continue;
            const auto traveler=townSource ? actor.String() : pool, destination=townSource ? source.String() : actor.String();
            const JsonNode * best=nullptr;
            for(const auto & route:quote["meeting_routes"].Vector())
                if(route["hero_ref"].String()==traveler && route["destination_ref"].String()==destination
                    && (!best || route["day"].Integer()<(*best)["day"].Integer()
                        || (route["day"]==(*best)["day"] && route["army_loss_estimate"].Integer()<(*best)["army_loss_estimate"].Integer()))) best=&route;
            if(!best || !(*best)["day"].isNumber() || !(*best)["army_loss_estimate"].isNumber() || !quote["unpledged_army_value"].isNumber()) continue;
            const auto arrival=(*best)["day"].Integer(),loss=(*best)["army_loss_estimate"].Integer();
            int64_t force=0;for(const auto & hero:world["heroes"].Vector()) if(hero["ref"].String()==traveler) force=hero["army_value"].Integer();
            if(arrival>=world["day"].Integer() && arrival<=goal["deadline_day"].Integer() && loss>=0
                && loss<=force*campaign.plan()["policy"]["max_loss_ratio"].Float()
                && recipient+quote["unpledged_army_value"].Integer()-loss>=goal["complete_when"]["value"].Integer()) return true;
        }
    }
    return false;
}
// Coverage is derived from a freshly admitted operation, never from dispatch.
inline JsonNode acceptedQuestionCoverage(const JsonNode & signals,const JsonNode & metadata,
    const CampaignState & campaign,const JsonNode & intent)
{
    JsonNode result;result.Vector();
    if(metadata["operation_focus"]["revision"]!=intent["revision"]) return result;
    for(const auto & signal:signals.Vector())
    {
        const auto & question=signal["question"].String();
        const std::string prefix="strategy:no_progress:";
        if(!question.starts_with(prefix) || result.Vector().size()>=6) continue;
        const auto milestoneID=question.substr(prefix.size());
        if(intentMilestone(intent,JsonNode(milestoneID)).isNull()
            || intent["progress"][milestoneID]["state"].String()=="completed") continue;
        JsonNode ids;ids.Vector();
        for(const auto & binding:metadata["operation_focus"]["bindings"].Vector())
        {
            if(binding["milestone_id"].String()!=milestoneID) continue;
            for(const auto & goal:campaign.plan()["goals"].Vector())
            {
                if(goal["id"]!=binding["goal_id"] || !campaign.holdsCommitment(goal["id"].String())) continue;
                const auto & status=campaign.statuses()[goal["id"].String()]["state"].String();
                if(status!="ready" && status!="waiting") continue;
                const bool hold=goal["kind"].String()=="preserve_force" || goal["kind"].String()=="defend_area";
                bool hasBasis=!hold;
                for(const auto & wait:metadata["decision_basis"]["waits"].Vector())
                    if(wait["goal_id"]==goal["id"]) hasBasis=true;
                if(hasBasis) ids.Vector().push_back(goal["id"]);
            }
        }
        if(ids.Vector().empty()) continue;
        JsonNode item;item["question"]=signal["question"];item["facts"]=signal["facts"];
        item["milestone_id"].String()=milestoneID;item["campaign_revision"]=campaign.plan()["revision"];
        item["goal_ids"]=ids;result.Vector().push_back(item);
    }
    return result;
}
inline JsonNode reconcileQuestionCoverage(JsonNode & coverage,RequestArbiter & arbiter,
    const CampaignState & campaign,const JsonNode & intent,const JsonNode & metadata)
{
    JsonNode reopened;reopened.Vector();
    std::erase_if(coverage.Vector(),[&](const auto & item) {
        const auto & milestone=item["milestone_id"].String();
        // Native-confirmed progress closes this question independently of goals.
        if(!intentMilestone(intent,JsonNode(milestone)).isNull()
            && intent["progress"][milestone]["state"].String()=="completed") return true;
        JsonNode signal;signal["question"]=item["question"];signal["facts"]=item["facts"];
        JsonNode signals;signals.Vector().push_back(signal);
        const auto live=acceptedQuestionCoverage(signals,metadata,campaign,intent);
        const bool valid=item["campaign_revision"]==campaign.plan()["revision"] && !live.Vector().empty()
            && item["goal_ids"]==live[0]["goal_ids"];
        if(valid) return false;
        arbiter.reopen(item["question"].String());reopened.Vector().push_back(item["question"]);
        return true;
    });
    return reopened;
}
inline bool admittedQuestionCovered(const StrategicSignal & signal,const JsonNode & metadata,
    const CampaignState & campaign,const JsonNode & intent,const JsonNode & world=JsonNode())
{
    const auto & question=signal.question;
    if(question.starts_with("strategy:no_progress:"))
    {
        JsonNode item;item["question"].String()=question;item["facts"].String()=signal.facts;
        JsonNode signals;signals.Vector().push_back(item);
        return !acceptedQuestionCoverage(signals,metadata,campaign,intent).Vector().empty();
    }
    if(question=="initial_strategy") return !intent.isNull();
    if(question=="opening" || question=="horizon" || question=="campaign_exhausted"
        || question.starts_with("checkpoint:")) return !campaign.plan().isNull();
    if(question.starts_with("strategy:"))
    {
        const auto milestone=question.substr(question.find(':',9)+1);
        for(const auto & binding:metadata["operation_focus"]["bindings"].Vector())
            if(binding["milestone_id"].String()==milestone && campaign.holdsCommitment(binding["goal_id"].String())) return true;
        return false;
    }
    if(question=="townless_survival")
    {
        if(!world["towns"].Vector().empty()) return true;
        std::string reason;
        return CampaignState::townlessCaptureDeadline(world).has_value() && campaign.validateTownlessRecovery(world,reason);
    }
    if(question.starts_with("decision_basis:"))
    {
        try
        {
            JsonParsingSettings parser;parser.strict=true;parser.mode=JsonParsingSettings::JsonFormatMode::JSON;
            const JsonNode facts(signal.facts.data(),signal.facts.size(),parser,"ended decision basis");
            if(!facts["actor_ref"].isString()) return false;
            bool owned=false;for(const auto & hero:world["heroes"].Vector()) owned |= hero["ref"]==facts["actor_ref"];
            if(world.isStruct() && !owned && facts["ended_reason"].String()=="executor_no_longer_owned") return true;
            for(const auto & goal:campaign.plan()["goals"].Vector())
                if(goal["actor_ref"]==facts["actor_ref"] && campaign.holdsCommitment(goal["id"].String())) return true;
        }
        catch(const std::exception &) { return false; }
        return false;
    }
    const auto colon=question.find(':');
    const auto subject=colon==std::string::npos ? question : question.substr(colon+1);
    for(const auto & goal:campaign.plan()["goals"].Vector())
        if(campaign.holdsCommitment(goal["id"].String())
            && (goal["id"].String()==subject || goal["actor_ref"].String()==subject || goal["target_ref"].String()==subject)) return true;
    for(const auto & choice:metadata["decision_basis"]["town_choices"].Vector())
        if(question=="defense:"+choice["town_ref"].String()) return true;
    return false;
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
    if(!failure["code"].isString()
        || !shape(usage,{"known","input_tokens","output_tokens"}) || !usage["known"].isBool()
        || !integer(usage["input_tokens"]) || !integer(usage["output_tokens"])
        || usage["input_tokens"].Integer()>1000000000 || usage["output_tokens"].Integer()>1000000000) return JsonNode();
    const std::set<std::string> semanticCodes{"weaker_main_without_supported_offense","invalid_strategic_operation_focus",
        "unsupported_wait_purpose","unsupported_strategic_ownership_target","unsupported_strategic_action_target"};
    if(semanticCodes.count(failure["code"].String())) return shape(failure,{"code"}) ? failure : JsonNode();
    if(!shape(failure,{"code","required","available"})
        || failure["code"].String()!="resource_commitments_exceed_available_funds") return JsonNode();
    if(!failure["required"].isVector() || !failure["available"].isVector()
        || failure["required"].Vector().size()!=7 || failure["available"].Vector().size()!=7
        || failure["available"]!=request["observation"]["resources"]) return JsonNode();
    bool exceeded=false;
    for(int i=0;i<7;++i)
    {
        if(!integer(failure["required"][i]) || !integer(failure["available"][i])) return JsonNode();
        if(failure["required"][i].Integer()>1000000000000LL || failure["available"][i].Integer()>1000000000000LL) return JsonNode();
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
