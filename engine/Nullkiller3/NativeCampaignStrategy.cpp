#include "../Nullkiller2/StdInc.h"
#include "NativeCampaign.h"
#include "StrategicDecision.h"
#include "StrategicIntent.h"
#include "Forecasts.h"
#include "OffensivePreparation.h"
#include "StrategicCandidates.h"
#include "BackgroundPlanning.h"
#include "../ExternalAI/ProcessExchange.h"
#include "../TransportJSON/TransportJSON.h"
#include "../ExternalAI/StrategyMemory.h"
#include "../Nullkiller2/Engine/Nullkiller.h"
#include "../Nullkiller2/AIGateway.h"
#include "../../lib/gameState/CGameState.h"
#include "../../lib/UnlockGuard.h"
#include <chrono>
#include <cstdlib>

namespace nullkiller3
{
namespace
{
constexpr int64_t strategicRequestTokens = 120000;

bool boundedInteger(const JsonNode & value, int64_t low, int64_t high)
{
    return value.getType() == JsonNode::JsonType::DATA_INTEGER && value.Integer() >= low && value.Integer() <= high;
}
const char * environment(const char * name)
{
    const auto * value = std::getenv(name);
    return value ? value : "";
}
JsonNode identity(const JsonNode & persisted, const std::string & generation, const JsonNode & world, int64_t revision)
{
    JsonNode result;
    result["instance"] = persisted["experience_id"];
    result["generation"].String() = generation;
    result["player"] = world["player"];
    result["day"] = world["day"];
    result["revision"].Integer() = revision;
    return result;
}
}
void NativeCampaign::restoreArbiter()
{
    generation = boost::uuids::to_string(boost::uuids::random_generator()());
    const auto & saved = static_cast<const JsonNode &>(persisted)["request_arbiter"];
    if(saved.isNull()) return;
    if(!saved.isStruct() || !boundedInteger(saved["version"],1,1) || !boundedInteger(saved["day"],-1,2147483647)
        || !boundedInteger(saved["requests"],0,2147483647)
        || !saved["addressed"].isStruct())
    { invalidBudget = true; logAi->warn("NK3 invalid saved request budget; native continuation only"); return; }
    ArbiterState restored;
    restored.day = saved["day"].Integer();
    restored.requests = saved["requests"].Integer();
    restored.remaining = {0,0,0};
    if(boundedInteger(saved["wait_ms"],0,3600000)) restored.remaining.waitMs=saved["wait_ms"].Integer();
    if(boundedInteger(saved["tokens"],0,10000000)) restored.remaining.tokens=saved["tokens"].Integer();
    for(const auto & [question, facts] : saved["addressed"].Struct())
    {
        if(question.empty() || question.size()>240 || !facts.isString() || facts.String().size()>8192)
        { invalidBudget = true; return; }
        restored.addressed[question] = facts.String();
    }
    arbiter = RequestArbiter(restored);
    if(saved.Struct().count("prepared_execution_day"))
    {
        if(boundedInteger(saved["prepared_execution_day"],1,2147483647)) preparedExecutionDay=saved["prepared_execution_day"].Integer();
        else invalidPreparationMarker=true;
    }
}
void NativeCampaign::saveArbiter()
{
    if(invalidBudget) return; // Never replace an unknown spent budget with fresh limits.
    const auto snapshot = arbiter.save();
    JsonNode saved;
    saved["version"].Integer() = snapshot.version;
    saved["day"].Integer() = snapshot.day;
    saved["requests"].Integer() = snapshot.requests;
    saved["wait_ms"].Integer() = snapshot.remaining.waitMs;
    saved["tokens"].Integer() = snapshot.remaining.tokens;
    saved["critical_reserve_ms"].Integer() = snapshot.remaining.criticalReserveMs;
    saved["addressed"].Struct();
    for(const auto & [question,facts] : snapshot.addressed) saved["addressed"][question].String() = facts;
    if(preparedExecutionDay>0) saved["prepared_execution_day"].Integer()=preparedExecutionDay;
    else if(invalidPreparationMarker) saved["prepared_execution_day"]=persisted["request_arbiter"]["prepared_execution_day"];
    persisted["request_arbiter"] = saved;
}
void NativeCampaign::observeBuildingProgress()
{
    JsonNode current;
    current.Struct();
    for(const auto & goal:campaign.plan()["goals"].Vector())
    {
        if(goal["kind"].String()!="develop_town"
            || world["goal_statuses"][goal["id"].String()]["state"].String()!="ready") continue;
        for(const auto & town:world["towns"].Vector()) if(town["ref"]==goal["target_ref"])
            for(const auto & option:town["building_options"].Vector()) if(option["id"]==goal["building_id"])
            {
                std::vector<const JsonNode *> sequence;
                if(!buildingSequence(town,option,sequence)) continue;
                JsonNode remaining;remaining.Vector();
                for(const auto * step:sequence) remaining.Vector().push_back((*step)["id"]);
                // Remaining prerequisites exclude unrelated native construction,
                // routine income and per-turn build availability. The identity
                // survives a model renumbering the same unfinished objective.
                const auto key=goal["target_ref"].String()+":"+std::to_string(goal["building_id"].Integer());
                const auto & previous=static_cast<const JsonNode &>(persisted)["building_progress"][key];
                auto & progress=current[key];
                progress["remaining"]=remaining;
                progress["last_progress_day"] = previous["remaining"]==remaining
                    ? previous["last_progress_day"] : world["day"];
            }
    }
    persisted["building_progress"]=current;
}
void NativeCampaign::observeOperationProgress()
{
    JsonNode current;current.Struct();
    for(const auto & goal:campaign.plan()["goals"].Vector())
    {
        const auto & kind=goal["kind"].String();
        if(kind=="develop_town" || kind=="preserve_force" || kind=="defend_area"
            || world["goal_statuses"][goal["id"].String()]["state"].String()!="ready") continue;
        auto objective=operationIdentity(goal);
        objective["risk"]=goal["risk"];
        for(const auto * field:{"max_loss_ratio","allow_route_repair","allow_helper_replacement"}) objective["policy"][field]=campaign.plan()["policy"][field];
        auto facts=operationOwnFacts(goal,world,campaign.deliverySource(goal,helperSources()));
        if(kind=="reinforce_hero")
            for(const auto & delivery:world["forecasts"]["deliveries"].Vector()) if(delivery["goal_id"]==goal["id"])
                facts["source_floor"]=delivery["source_floor"];
        auto & progress=current[goal["id"].String()];
        for(const auto & [id,previous]:persisted["operation_progress"].Struct())
            if(previous["objective"]==objective) { progress=previous;break; }
        progress=operationProgress(progress,objective,facts,world["day"].Integer());
    }
    persisted["operation_progress"]=current;
}
void NativeCampaign::recordCheckpointBaseline()
{
    JsonNode baseline;baseline["day"]=world["day"];
    baseline["facts"].String()=allocationCheckpointFacts(campaign,world);
    baseline["offense"]=offensiveCheckpoint(world["offensive_preparation"]);
    persisted["checkpoint_baseline"]=baseline;
}
std::vector<StrategicSignal> NativeCampaign::strategicSignals(NK2AI::Nullkiller & ai,bool includeIdle)
{
    std::vector<StrategicSignal> result;
    bool actionable = !world["towns"].Vector().empty();
    for(const auto & hero : world["heroes"].Vector()) actionable |= hero["movement"].Integer() > 100;
    for(const auto * hero:ai.cc->getHeroesInfo())
        if(static_cast<const JsonNode &>(persisted)["passage_reviews"][std::to_string(hero->id.getNum())].isStruct()) {
            const auto review=automaticMoveReview(ai,hero,hero->visitablePos());
            automaticSafetyReviews[review["hero_ref"].String()]=review;
        }
    world["automatic_safety_reviews"].Vector();
    for(const auto & [ref,review]:automaticSafetyReviews.Struct())
    {
        const CGHeroInstance * actor=nullptr;
        for(const auto * hero:ai.cc->getHeroesInfo())
            if(resolve(ai,JsonNode(ref))==hero) actor=hero;
        const auto & target=review["target_position"];
        const auto fresh=actor ? automaticMoveReview(ai,actor,int3(target[0].Integer(),target[1].Integer(),target[2].Integer())) : JsonNode();
        if(fresh.isNull()) continue;
        world["automatic_safety_reviews"].Vector().push_back(fresh);
        result.push_back(automaticSafetySignal(fresh,world["day"].Integer(),actionable));
    }
    const auto intentSignals=strategicIntentSignals(persisted["strategic_intent"],world,actionable);
    result.insert(result.end(),intentSignals.begin(),intentSignals.end());
    const auto checkpoint=allocationCheckpointSignals(campaign,world,persisted["checkpoint_baseline"],actionable);
    result.insert(result.end(),checkpoint.begin(),checkpoint.end());
    const auto offense=offensiveCheckpointSignals(world,persisted["checkpoint_baseline"],actionable);
    result.insert(result.end(),offense.begin(),offense.end());
    if(includeIdle)
    {
        const auto idle=idleArmySignals(campaign,world,actionable);
        result.insert(result.end(),idle.begin(),idle.end());
    }
    const auto hired=helperHiredSignals(campaign,world,actionable);
    result.insert(result.end(),hired.begin(),hired.end());
    const auto transfers=operationTransferSignals(campaign,world,persisted["memory"],actionable);
    result.insert(result.end(),transfers.begin(),transfers.end());
    auto losses=battleLossSignals(campaign.plan(),persisted["memory"],actionable);
    std::erase_if(losses,[&](const auto & signal) {
        if(!locallyRepairedCourierLoss(ai,signal.question.substr(std::string("battle_loss:").size()))) return false;
        arbiter.resolved(signal);
        return true;
    });
    result.insert(result.end(),losses.begin(),losses.end());
    const auto towns=criticalTownLossSignals(campaign.plan(),world,actionable);
    result.insert(result.end(),towns.begin(),towns.end());
    if(campaign.plan().isNull()) result.push_back({"opening","no_campaign",true,true,actionable,false});
    for(const auto & goal : campaign.plan()["goals"].Vector())
    {
        const auto & status = world["goal_statuses"][goal["id"].String()];
        const auto & why = status["reason"].String();
        if(why == "no_supported_route" || why == "executor_no_longer_owned" || why == "deadline_missed" || why=="target_no_longer_owned" || why=="dependency_failed" || why=="force_floor_breached" || why=="force_continuity_unconfirmed")
        {
            auto facts=why;
            if(why=="no_supported_route")
                facts=operationIdentity(goal).toCompactString()+campaign.routeFeedbackFacts(goal,world);
            // A renamed route goal for this executor is the same question.
            // Independent live route obligations cannot share an executor.
            const auto subject=why=="no_supported_route" ? goal["actor_ref"].String() : goal["id"].String();
            result.push_back({"commitment:"+subject,facts,true,true,actionable,true});
        }
    }
    bool exhausted=!campaign.plan().isNull();
    int64_t completedDay=0;
    for(const auto & goal:campaign.plan()["goals"].Vector())
    {
        const auto & status=world["goal_statuses"][goal["id"].String()];
        exhausted &= status["state"].String()=="completed";
        completedDay=std::max(completedDay,status["completed_day"].Integer());
    }
    if(!campaign.plan().isNull() && !exhausted)
    {
        const auto saved = campaign.save();
        if(world["day"].Integer() >= saved["accepted_day"].Integer()+campaign.plan()["horizon_days"].Integer())
            result.push_back({"horizon",std::to_string(campaign.plan()["revision"].Integer()),true,true,actionable,false});
    }
    // Reconsider a stationed commander before an unassigned native task can
    // leave the town. Other completed operations retain next-turn batching.
    bool stationedCommander=false;
    if(exhausted) for(const auto & assignment:persisted["strategy_metadata"]["assignments"].Vector())
        if(assignment["role"].String()=="main" || assignment["role"].String()=="defender")
            for(const auto & hero:world["heroes"].Vector())
                if(hero["ref"]==assignment["hero_ref"] && hero["movement"].Integer()>100
                    && hero["position"].isVector())
                    for(const auto & town:world["towns"].Vector())
                        stationedCommander |= hero["position"]==town["position"];
    if(exhausted && (completedDay<world["day"].Integer() || stationedCommander))
        result.push_back({"campaign_exhausted",std::to_string(campaign.plan()["revision"].Integer())+":"+std::to_string(world["day"].Integer()),true,true,actionable,false});
    const auto repairFacts=repairQuestionFacts(campaign.plan(),persisted["goal_blockers"],world["goal_statuses"]);
    if(!repairFacts.empty()) result.push_back({"repair_exhausted",repairFacts,true,true,actionable,false});
    for(const auto & goal:campaign.plan()["goals"].Vector())
    {
        if(goal["kind"].String()!="develop_town"
            || world["goal_statuses"][goal["id"].String()]["state"].String()!="ready") continue;
        const auto key=goal["target_ref"].String()+":"+std::to_string(goal["building_id"].Integer());
        const auto & progress=persisted["building_progress"][key];
        if(progress.isNull() || world["day"].Integer()<progress["last_progress_day"].Integer()+2) continue;
        bool supportedContinuation=false;
        for(const auto & estimate:world["forecasts"]["commitments"].Vector()) if(estimate["goal_id"]==goal["id"])
            supportedContinuation=estimate["status"].String()=="conditional";
        // A supported purchase today is ordinary execution too. Give the
        // native owner that opportunity rather than reviewing just before it
        // builds. Repeated command failures already have their repair signal.
        if(!supportedContinuation) result.push_back({"stagnation:"+key,progress.toCompactString(),true,true,actionable,false});
    }
    std::set<std::string> stalledOperations;
    for(const auto & [id,progress]:persisted["operation_progress"].Struct())
    {
        if(!operationStalled(progress,world["forecasts"],id,world["day"].Integer())) continue;
        JsonNode facts;facts["objective"]=progress["objective"];facts["own_participants"]=progress["facts"];
        stalledOperations.insert(facts.toCompactString());
    }
    if(!stalledOperations.empty())
    {
        std::string facts;
        for(const auto & operation:stalledOperations) { facts+=operation;facts+='\n'; }
        result.push_back({"stagnation:operations",facts,true,true,actionable,false});
    }
    // Sightings alone are not decisions. Aggregate fronts that can change an
    // insufficient town defense; routine changes to movement/route IDs do not
    // enter the signature. Private enemy speed and intention stay unknown.
    for(const auto & defense:world["forecasts"]["defenses"].Vector())
    {
        const auto & status=defense["status"].String();
        if(!defense["critical"].Bool()
            || (status!="insufficient_current_force" && status!="unbounded_opposition" && status!="observed_threat_timing_unknown")) continue;
        result.push_back(defenseSignal(defense,actionable));
    }
    for(const auto & object:world["visible_objects"].Vector())
    {
        if(object["kind"].String()!="town" || std::find(world["enemy_players"].Vector().begin(),world["enemy_players"].Vector().end(),object["owner"])==world["enemy_players"].Vector().end()) continue;
        bool assigned=false;
        for(const auto & goal:campaign.plan()["goals"].Vector()) assigned |= goal["target_ref"]==object["ref"];
        if(assigned) continue;
        bool reachable=false;
        for(const auto & route:world["forecasts"]["routes"].Vector()) if(route["target_ref"]==object["ref"])
            for(const auto & arrival:route["own_arrivals"].Vector())
                reachable |= arrival["day"].Integer()<=world["day"].Integer()+3
                    && arrival["army_loss_estimate"].Integer()<arrival["army_value"].Integer()/5;
        if(reachable) result.push_back({"victory_target:"+object["ref"].String(),"supported_reachable_enemy_town",true,true,actionable,false});
    }
    return result;
}
bool NativeCampaign::reviewIdleArmy(NK2AI::Nullkiller & ai)
{
    ai.updateState();
    world["main_army_idle"]=mainArmyIdle(campaign,world);
    logAi->info("NK3_IDLE %s",world["main_army_idle"].toCompactString());
    if((!automaticSafetyReviews.isNull() && !automaticSafetyReviews.Struct().empty())
        || (!persisted["passage_reviews"].isNull() && !persisted["passage_reviews"].Struct().empty())) return reviewStrategy(ai,true);
    if(!idleArmyNeedsReview(world["main_army_idle"])) return false;
    if(repairOwnHeroObstruction(ai)) return true;
    return reviewStrategy(ai,true);
}
void NativeCampaign::logBackgroundStart(const std::string & requestID) const
{
    // Callback reads no planner-owned JSON. Request details are in the staged trace.
    logAi->info("NK3_BACKGROUND start request_id=%s",requestID);
}
void NativeCampaign::captureTurnQuestions(NK2AI::Nullkiller & ai)
{
    if(unresolvedQuestionDay!=world["day"].Integer())
    { unresolvedTurnQuestions.clear();unresolvedQuestionDay=world["day"].Integer(); }
    arbiter.beginTurn(world["day"].Integer(),{0,strategicRequestTokens,0});
    const auto decision=arbiter.consider(strategicSignals(ai,false));
    for(const auto & signal:decision.signals) unresolvedTurnQuestions.insert_or_assign(signal.question,signal);
    if(std::any_of(unresolvedTurnQuestions.begin(),unresolvedTurnQuestions.end(),[](const auto & entry){return entry.second.critical;}))
    {
        // Critical facts invalidate admission, but never abort a running call
        // just because the own turn began. Fresh foreground review remains open.
        if(!backgroundRequest.isNull() && !backgroundInvalidated)
        {
            backgroundInvalidated=true;
            JsonNode trace;trace["phase"].String()="invalidate";trace["reason"].String()="critical_question";
            trace["request_id"]=backgroundRequest["request_id"];trace["observed_day"]=backgroundRequest["identity"]["day"];
            trace["execution_day"]=world["day"];
            for(const auto & [question,signal]:unresolvedTurnQuestions) if(signal.critical)
                trace["questions"].Vector().emplace_back(question);
            logAi->info("NK3_BACKGROUND %s",trace.toCompactString());
        }
    }
}
void NativeCampaign::prepareNextTurn(NK2AI::Nullkiller & ai)
{
    ai.aiGw->checkStrategicTurn();
    const std::string mode=environment("VCMI_NK3_MODE");
    if((!mode.empty() && mode!="model") || stopping || invalidBudget || invalidPreparationMarker
        || !backgroundRequest.isNull() || !background.available() || campaign.plan().isNull() || persisted["strategic_intent"].isNull()
        || !*environment("VCMI_EXTERNAL_AI_EXECUTABLE") || !*environment("VCMI_EXTERNAL_AI_SCRIPT")) return;
    // Serialized own-turn work only. Read the last already-built observation;
    // callbacks never observe, generate, persist or touch the arbiter.
    const auto nextDay=world["day"].Integer()+1;
    if(preparedExecutionDay>=nextDay) return;
    auto scope=preparationScope(world,campaign);
    auto prospective=arbiter;
    prospective.beginTurn(nextDay,{0,strategicRequestTokens,0});
    auto signals=strategicSignals(ai,true);
    bool futureActionable=!world["towns"].Vector().empty();
    for(const auto & hero:world["heroes"].Vector()) futureActionable |= hero["movement_per_day"].Integer()>100;
    for(auto & signal:signals)
    {
        signal.actionable=futureActionable;
        if(signal.question=="campaign_exhausted") signal.facts=std::to_string(campaign.plan()["revision"].Integer())+":"+std::to_string(nextDay);
    }
    bool exhausted=!campaign.plan().isNull();
    for(const auto & goal:campaign.plan()["goals"].Vector()) exhausted &= campaign.statuses()[goal["id"].String()]["state"].String()=="completed";
    if(exhausted) signals.push_back({"campaign_exhausted",std::to_string(campaign.plan()["revision"].Integer())+":"+std::to_string(nextDay),true,true,futureActionable,false});
    auto decision=prospective.consider(signals);
    const bool strategicReview=std::any_of(decision.signals.begin(),decision.signals.end(),[](const auto & signal){return signal.question!="campaign_exhausted";});
    if(!strategicReview)
    {
        // Routine preparation cannot rewrite dependencies on completed goals;
        // own-turn review must resolve them before another model request.
        if(scope["requires_review"].Bool()) return;
        std::set<std::string> assigned;
        for(const auto & assignment:persisted["strategy_metadata"]["assignments"].Vector()) assigned.insert(assignment["hero_ref"].String());
        std::erase_if(scope["actors"].Vector(),[&](const auto & actor){return !assigned.count(actor.String());});
        std::erase_if(scope["needs"].Vector(),[&](const auto & need){return need["kind"].String()=="hero" && !assigned.count(need["ref"].String());});
    }
    for(const auto & need:scope["needs"].Vector())
        decision.signals.push_back({"routine:"+need["ref"].String(),std::to_string(nextDay)+":"+std::to_string(campaign.plan()["revision"].Integer()),true,true,true,false});
    if(decision.signals.empty() || (scope["targets"].Vector().empty() && !strategicReview)) return;
    JsonNode request;
    request["protocol"].Integer()=2;request["mode"].String()="prepare_next_turn";
    request["identity"]=identity(persisted,generation,world,campaign.plan()["revision"].Integer());
    request["execution_day"].Integer()=nextDay;request["intent_revision"]=persisted["strategic_intent"]["revision"];
    request["strategic_review"].Bool()=strategicReview;
    request["allowed_actor_refs"]=scope["actors"];request["allowed_target_refs"]=scope["targets"];
    request["routine_needs"]=scope["needs"];
    const auto sequence=persisted["request_sequence"].Integer()+1;
    request["request_id"].String()=persisted["experience_id"].String()+":"+generation+":"+std::to_string(world["player"].Integer())
        +":"+std::to_string(world["day"].Integer())+":"+std::to_string(campaign.plan()["revision"].Integer())+":"+std::to_string(sequence);
    request["strategic_intent"]=persisted["strategic_intent"];request["campaign"]=campaign.plan();
    request["observation"]=strategicCandidateView(world,campaign.plan(),request["strategic_intent"],strategicReview);
    request["observation"]["strategy_assignments"]=persisted["strategy_metadata"]["assignments"];
    if(!request["observation"]["strategy_assignments"].isVector()) request["observation"]["strategy_assignments"].Vector();
    if(strategicReview)
    {
        request["observation"]["map_overview"]=strategicMapOverview(world,request["strategic_intent"],true);
        request["observation"]["strategy_stalls"]=strategicStalls(request["strategic_intent"],world);
    }
    request["memory"]=strategicCandidateMemory(persisted["memory"],request["observation"]);
    for(const auto & signal:decision.signals)
    {
        JsonNode item;item["question"].String()=signal.question;item["facts"].String()=signal.facts;item["critical"].Bool()=signal.critical;
        request["signals"].Vector().push_back(item);
    }
    for(const auto * field:{"day","resources","victory","rules","goal_feedback","offensive_preparation","main_army_idle","scouting_options","map_overview","strategy_stalls","automatic_safety_reviews","decision_feedback"})
        request["evidence_refs"].Vector().emplace_back("observation:"+std::string(field));
    if(strategicReview) for(const auto * field:{"map_overview","strategy_stalls"}) request["evidence_refs"].Vector().emplace_back("observation:"+std::string(field));
    for(const auto & hero:request["observation"]["heroes"].Vector()) request["evidence_refs"].Vector().emplace_back("hero:"+hero["ref"].String());
    for(const auto & town:request["observation"]["towns"].Vector()) request["evidence_refs"].Vector().emplace_back("town:"+town["ref"].String());
    for(const auto & object:request["observation"]["objects"].Vector()) request["evidence_refs"].Vector().emplace_back("target:"+object["ref"].String());
    request["budget"]["wait_ms"].Integer()=80000;request["budget"]["tokens"].Integer()=strategicRequestTokens;
    boundStrategicRequest(request);
    std::set<std::string> exposed;
    for(const auto * list:{"heroes","towns","objects","visible_objects"})
        for(const auto & item:request["observation"][list].Vector()) exposed.insert(item["ref"].String());
    for(const auto & ref:request["observation"]["frontiers"].Vector()) exposed.insert(ref.String());
    std::erase_if(request["allowed_target_refs"].Vector(),[&](const auto & ref){return !exposed.count(ref.String());});
    const auto input=ai_transport::transportJSON(request.toCompactString());
    if(input.size()>512*1024) return;
    // Persist the marker before publication, even with learning disabled.
    preparedExecutionDay=nextDay;persisted["request_sequence"].Integer()=sequence;
    persist(ai);
    backgroundRequest=request;backgroundObservation=world;backgroundInvalidated=false;
    background.publish(input,environment("VCMI_EXTERNAL_AI_EXECUTABLE"),environment("VCMI_EXTERNAL_AI_SCRIPT"),request["request_id"].String());
    JsonNode trace;trace["phase"].String()="staged";trace["identity"]=request["identity"];trace["request_id"]=request["request_id"];
    trace["observed_day"]=world["day"];trace["execution_day"]=request["execution_day"];trace["signals"]=request["signals"];trace["budget"]=request["budget"];
    logAi->info("NK3_BACKGROUND %s",trace.toCompactString());
}
void NativeCampaign::admitBackground(NK2AI::Nullkiller & ai)
{
    if(backgroundRequest.isNull()) return;
    const bool firstInspection=backgroundAdmissionDay!=world["day"].Integer();
    backgroundAdmissionDay=world["day"].Integer();
    // Missing/error/late background leaves every original need open, including
    // an idle secondary hero whose need a surviving campaign can otherwise hide.
    if(firstInspection && backgroundRequest["execution_day"]==world["day"])
        for(const auto & item:backgroundRequest["signals"].Vector())
        {
            StrategicSignal signal{item["question"].String(),item["facts"].String(),true,true,true,item["critical"].Bool()};
            if(arbiter.consider({signal}).request) unresolvedTurnQuestions.try_emplace(signal.question,signal);
        }
    const auto response=background.take(); // Poll again at subsequent safe own-turn passes.
    JsonNode trace;trace["phase"].String()="ready";trace["request_id"]=backgroundRequest["request_id"];
    trace["observed_day"]=backgroundRequest["identity"]["day"];trace["execution_day"]=world["day"];
    if(!response)
    {
        if(firstInspection && !backgroundRequest.isNull())
        {
            trace["phase"].String()="pending";trace["reason"].String()="not_ready";
            logAi->info("NK3_BACKGROUND %s",trace.toCompactString());
        }
        return;
    }
    trace["elapsed_ms"].Integer()=response->elapsedMs;
    logAi->info("NK3_BACKGROUND %s",trace.toCompactString());
    std::string reason=backgroundInvalidated ? "critical_question" : response->reply.error;
    CampaignState candidate;JsonNode intent,derived,groups,reply;
    bool accepted=false;
    try
    {
        if(reason.empty() && response->request==ai_transport::transportJSON(backgroundRequest.toCompactString()))
        {
            JsonParsingSettings parser;parser.strict=true;parser.mode=JsonParsingSettings::JsonFormatMode::JSON;
            reply=JsonNode(response->reply.output.data(),response->reply.output.size(),parser,"NK3 background reply");
            accepted=admitPreparation(reply,backgroundRequest,backgroundObservation,world,campaign,persisted["strategic_intent"],
                persisted["pending_native_task"],candidate,intent,derived,groups,reason);
        }
        else if(reason.empty()) reason="stale_background_epoch";
    }
    catch(const std::exception & error) { reason=error.what(); }
    if(accepted)
    {
        observeIntentProgress();
        bindStrategicOperation(intent,derived["operation_focus"],candidate.plan(),persisted["pending_native_task"]);
        campaign=candidate;persisted["strategic_intent"]=intent;
        for(const auto * field:{"decision","reason","victory_method","assignments","reconsider_when","defense_exit","operation_focus"})
            persisted["strategy_metadata"][field]=derived[field];
        acceptedRevision=campaign.plan()["revision"].Integer();acceptedLossRatio=campaign.plan()["policy"]["max_loss_ratio"].Float();
        const bool strategyCovered=backgroundRequest["strategic_review"].Bool() && preparationStrategyFresh(backgroundObservation,world);
        bool allGroups=true;for(const auto & group:groups.Vector()) allGroups &= group["accepted"].Bool();
        std::set<std::string> coveredNeeds;
        for(const auto & need:backgroundRequest["routine_needs"].Vector())
            for(const auto & goal:campaign.plan()["goals"].Vector()) if(campaign.holdsCommitment(goal["id"].String()))
                if(goal["actor_ref"]==need["ref"] || goal["target_ref"]==need["ref"])
                    coveredNeeds.insert(need["ref"].String());
        for(const auto & item:backgroundRequest["signals"].Vector())
        {
            const auto question=item["question"].String();bool covered=strategyCovered;
            // Each routine question belongs to one participant. Rejection of
            // an independent group must not reopen already covered questions.
            if(question.starts_with("routine:")) covered=coveredNeeds.count(question.substr(8));
            else if(question=="campaign_exhausted")
                covered=allGroups && coveredNeeds.size()==backgroundRequest["routine_needs"].Vector().size();
            const auto liveQuestion=unresolvedTurnQuestions.find(question);
            if(liveQuestion!=unresolvedTurnQuestions.end() && liveQuestion->second.facts!=item["facts"].String()) covered=false;
            if(covered)
            {
                StrategicSignal signal{question,item["facts"].String(),true,true,true,item["critical"].Bool()};
                arbiter.resolved(signal);unresolvedTurnQuestions.erase(question);
            }
            else { StrategicSignal unresolved{question,item["facts"].String(),true,true,true,item["critical"].Bool()};unresolvedTurnQuestions.try_emplace(question,unresolved); }
        }
        recordCheckpointBaseline();ai.invalidatePathfinderData();ai.updateState();
    }
    trace["phase"].String()=accepted ? "admit" : "discard";trace["reason"].String()=reason;trace["groups"]=groups;
    trace["raw_reply"]=reply;trace["candidate"]=accepted ? derived : JsonNode();
    const auto & usage=reply["usage"];
    trace["usage"]=usage;
    // Background does not dispatch foreground or mark failed questions resolved.
    logAi->info("NK3_BACKGROUND %s",trace.toCompactString());
    persist(ai);
    backgroundRequest=JsonNode();backgroundObservation=JsonNode();
}
bool NativeCampaign::reviewStrategy(NK2AI::Nullkiller & ai,bool includeIdle)
{
    ai.aiGw->checkStrategicTurn();
    const std::string mode = environment("VCMI_NK3_MODE");
    if(mode == "native" || invalidBudget || stopping) return false;
    if(!mode.empty() && mode != "model") { logAi->warn("NK3 unknown mode; native continuation"); return false; }
    // Rebuild local candidates before deciding whether an earlier blocker
    // still exists. These value-backed tasks expire here; none crosses a wait.
    generate(ai,false);
    generate(ai,true);
    if(persisted["checkpoint_baseline"].isNull()
        || persisted["checkpoint_baseline"]["day"].Integer()>world["day"].Integer()) recordCheckpointBaseline();
    if(persisted["checkpoint_baseline"]["offense"].isNull())
        persisted["checkpoint_baseline"]["offense"]=offensiveCheckpoint(world["offensive_preparation"]);
    arbiter.beginTurn(world["day"].Integer(), {0,strategicRequestTokens,0});
    auto signals=strategicSignals(ai,includeIdle);
    // A stabilization or newly installed routine reserve cannot erase a question
    // captured before it. The current view and original question are both sent.
    for(const auto & [question,signal]:unresolvedTurnQuestions) signals.push_back(signal);
    auto decision = arbiter.consider(signals);
    JsonNode trace;
    trace["day"] = world["day"];
    trace["player"] = world["player"];
    trace["requested"].Bool() = decision.request;
    trace["arbiter_reason"].Integer() = static_cast<int>(decision.reason);
    for(const auto & signal : decision.signals)
    {
        JsonNode item;
        item["question"].String() = signal.question;
        item["facts"].String() = signal.facts;
        item["critical"].Bool() = signal.critical;
        trace["signals"].Vector().push_back(item);
    }
    if(!decision.request)
    {
        persisted["pending_strategic_questions"] = trace["signals"];
        if(!decision.signals.empty()) logAi->info("NK3_STRATEGY %s",trace.toCompactString());
        return false;
    }
    JsonNode request;
    request["protocol"].Integer() = 2;
    const auto revision = campaign.plan()["revision"].Integer();
    request["identity"] = identity(persisted,generation,world,revision);
    const int64_t sequence = persisted["request_sequence"].Integer()+1;
    request["request_id"].String() = persisted["experience_id"].String()+":"+generation+":"
        +std::to_string(ai.playerID.getNum())+":"+std::to_string(world["day"].Integer())+":"
        +std::to_string(revision)+":"+std::to_string(sequence);
    // Freshness compares full native facts; proposal screening is model-only.
    const auto observationBeforeExchange = world;
    request["strategic_intent"]=persisted["strategic_intent"];
    bool detailedOverview=request["strategic_intent"].isNull();
    for(const auto & signal:decision.signals)
        detailedOverview |= signal.question.starts_with("strategy:") || signal.question.starts_with("battle_loss:")
            || signal.question.starts_with("critical_town:") || signal.question.starts_with("defense:")
            || signal.question.starts_with("checkpoint:") || signal.question.starts_with("stagnation:");
    request["observation"] = strategicCandidateView(world,campaign.plan(),request["strategic_intent"],detailedOverview);
    request["observation"]["strategy_stalls"]=strategicStalls(request["strategic_intent"],world);
    request["observation"]["map_overview"]=strategicMapOverview(world,request["strategic_intent"],detailedOverview);
    // Retain must echo the exact accepted roles, including order. Expose the
    // same saved owner used by admission; rejected proposals never replace it.
    const auto & metadata=static_cast<const JsonNode &>(persisted)["strategy_metadata"];
    request["observation"]["strategy_assignments"]=metadata["assignments"];
    if(!request["observation"]["strategy_assignments"].isVector())
        request["observation"]["strategy_assignments"].Vector();
    if(includeIdle) request["observation"]["main_army_idle"]=mainArmyIdle(campaign,world);
    request["memory"] = strategicCandidateMemory(persisted["memory"],request["observation"]);
    request["memory"]["experience_id"] = persisted["experience_id"];
    request["campaign"] = campaign.plan();
    request["signals"] = trace["signals"];
    request["budget"]["wait_ms"].Integer() = decision.deadlineMs;
    // Every request gets fresh transport/token limits; saved usage is diagnostic.
    request["budget"]["tokens"].Integer() = strategicRequestTokens;
    for(const auto * key : {"day","resources","victory","rules","goal_feedback","offensive_preparation","main_army_idle","scouting_options","map_overview","strategy_stalls","automatic_safety_reviews","decision_feedback"})
        request["evidence_refs"].Vector().emplace_back("observation:"+std::string(key));
    for(const auto & hero : world["heroes"].Vector()) request["evidence_refs"].Vector().emplace_back("hero:"+hero["ref"].String());
    for(const auto & town : world["towns"].Vector()) request["evidence_refs"].Vector().emplace_back("town:"+town["ref"].String());
    for(const auto & object : request["observation"]["objects"].Vector()) request["evidence_refs"].Vector().emplace_back("target:"+object["ref"].String());
    for(const auto & object:request["observation"]["map_overview"]["objects"].Vector())
    {
        const JsonNode ref("target:"+object["ref"].String());
        if(std::find(request["evidence_refs"].Vector().begin(),request["evidence_refs"].Vector().end(),ref)==request["evidence_refs"].Vector().end())
            request["evidence_refs"].Vector().push_back(ref);
    }
    boundStrategicRequest(request);
    const auto input = ai_transport::transportJSON(request.toCompactString());
    exchangeCancelled = false; // Reset only inside the serialized current-turn worker under GS lock.
    arbiter.dispatched(decision);
    for(const auto & signal:decision.signals) unresolvedTurnQuestions.erase(signal.question);
    recordCheckpointBaseline(); // A timeout/invalid reply cannot repeat this same choice.
    persisted["request_sequence"].Integer() = sequence;
    persisted["pending_strategic_questions"] = request["signals"];
    ai.invalidatePathfinderData();
    persist(ai); // Charge before waiting so a save cannot erase unknown costs.
    const auto started = std::chrono::steady_clock::now();
    externalai::Reply response;
    int64_t consumed = request["budget"]["tokens"].Integer(); // Unknown usage remains charged.
    try
    {
    if(input.size()>512*1024) response.error = "context_overflow";
    else if(!*environment("VCMI_EXTERNAL_AI_EXECUTABLE") || !*environment("VCMI_EXTERNAL_AI_SCRIPT")) response.error = "controller_unavailable";
    else
    {
        auto unlock = vstd::makeUnlockSharedGuard(CGameState::mutex);
        response = externalai::exchange(environment("VCMI_EXTERNAL_AI_EXECUTABLE"), {environment("VCMI_EXTERNAL_AI_SCRIPT")},
            // 32 KiB selected-course reply plus bounded usage/framing overhead.
            input,std::chrono::milliseconds(decision.deadlineMs),exchangeCancelled,32*1024+1024);
    }
    const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-started).count();
    if(stopping || exchangeCancelled || !ai.cc->isPlayerMakingTurn(ai.playerID)
        || ai.cc->getCalendar().getCurrentDay() != request["identity"]["day"].Integer())
    {
        trace["accepted"].Bool() = false;
        trace["fallback_reason"].String() = "strategic_exchange_cancelled";
        trace["elapsed_ms"].Integer() = elapsed;
        trace["charged_tokens"].Integer() = consumed;
        logAi->info("NK3_STRATEGY %s",trace.toCompactString());
        // The saved pre-dispatch reservation stays conservative. This live
        // instance must still release in-flight state before another turn.
        throw InterruptionRequestedException();
    }
    ai.makingTurnInterruption.interruptionPoint();
    ai.updateState(); // Every native task is built from this fresh post-wait view.
    bool accepted = false;
    JsonNode attemptedReply;
    std::string reason = response.error;
    bool factsUnchanged = true;
    for(const auto * key : {"heroes","towns","resources","visible_objects","shipyards","frontiers","victory"})
        factsUnchanged &= world[key] == observationBeforeExchange[key];
    if(!stopping && factsUnchanged && ai.cc->isPlayerMakingTurn(ai.playerID)
        && request["identity"] == identity(persisted,generation,world,campaign.plan()["revision"].Integer())
        && response.error.empty())
    {
        JsonParsingSettings parser; parser.strict = true; parser.mode = JsonParsingSettings::JsonFormatMode::JSON;
        const JsonNode reply(response.output.data(),response.output.size(),parser,"NK3 strategic reply");
        attemptedReply=reply;
        const auto & usage = static_cast<const JsonNode &>(reply)["usage"];
        if(usage["known"].isBool() && usage["known"].Bool() && boundedInteger(usage["input_tokens"],0,1000000000)
            && boundedInteger(usage["output_tokens"],0,1000000000))
            consumed = usage["input_tokens"].Integer()+usage["output_tokens"].Integer();
        CampaignState candidate;
        JsonNode candidateIntent;
        const auto failure=controllerFailureFeedback(reply,request);
        if(!reply["failure"].isNull())
            reason=failure.isNull() ? "invalid_controller_failure" : failure["code"].String();
        else accepted = validateStrategicDecision(reply,request,world,campaign,candidate,reason,
            &candidateIntent,&persisted["strategic_intent"]);
        if(accepted && reply["decision"].String() == "retain" && persisted["strategy_metadata"].isStruct()
            && reply["assignments"] != persisted["strategy_metadata"]["assignments"])
        { accepted = false; reason = "retained_plan_changed_roles_without_revision"; }
        if(accepted)
        {
            // Drain old operation receipts before replacing either value owner.
            observeIntentProgress();
            bindStrategicOperation(candidateIntent,reply["operation_focus"],candidate.plan(),persisted["pending_native_task"]);
            campaign = candidate;
            persisted["strategic_intent"]=candidateIntent;
            acceptedLossRatio=campaign.plan()["policy"]["max_loss_ratio"].Float();
            acceptedRevision=campaign.plan()["revision"].Integer();
            persisted["strategy_metadata"]=JsonNode();
            for(const auto * field:{"decision","reason","victory_method","assignments","reconsider_when","defense_exit","operation_focus"})
                persisted["strategy_metadata"][field]=reply[field];
            persisted["pending_strategic_questions"] = JsonNode();
            world["goal_statuses"] = campaign.review(world);
            // Model roles/reserves change path and hero analysis as well as
            // the goal list. Rebuild those owners before creating any command.
            ai.invalidatePathfinderData();
            ai.updateState();
            // The accepted decision saw every supplied defense forecast, even
            // towns it only now marks critical. Do not ask it the same enemy
            // question again merely because its own policy changed.
            for(const auto & defense:request["observation"]["forecasts"]["defenses"].Vector())
                if(defense["status"].String()=="unbounded_opposition"
                    || defense["status"].String()=="insufficient_current_force")
                    arbiter.resolved(defenseSignal(defense,true));
            // Only a successfully admitted response releases the crossing barrier.
            persisted["passage_reviews"]=JsonNode();
            automaticSafetyReviews=JsonNode();
            recordCheckpointBaseline(); // New goals/reserves own the next review's comparison.
        }
    }
    else if(reason.empty()) reason = "stale_or_cancelled_strategic_reply";
    arbiter.finished(elapsed,consumed);
    // Use the same bounded, saved own-result history as native actions. A
    // controller-valid policy can still be refused by the engine; the next
    // permitted request must not mistake that proposal for installed intent.
    const auto & proposal=static_cast<const JsonNode &>(attemptedReply);
    JsonNode action;
    action["kind"].String()="strategic_decision";
    action["request_id"]=request["request_id"];
    action["decision"]=proposal["decision"];
    action["reason"].String()=reason.substr(0,256);
    action["failure"]=controllerFailureFeedback(proposal,request);
    action["installed_revision"]=campaign.plan()["revision"];
    action["strategy_update"]=proposal["strategy_update"]["decision"];
    action["strategy_change_reason"]=proposal["strategy_update"]["change_reason"];
    const auto & installedIntent=static_cast<const JsonNode &>(persisted)["strategic_intent"];
    action["strategy_revision"]=installedIntent["revision"];
    action["strategy_objective"]=installedIntent["objective"];
    action["operation_focus"]=accepted ? proposal["operation_focus"] : JsonNode();
    action["proposed_goals"].Vector();
    if(proposal["plan"]["goals"].isVector())
        for(const auto & goal:proposal["plan"]["goals"].Vector())
        {
            if(!goal.isStruct() || action["proposed_goals"].Vector().size()>=12) continue;
            JsonNode summary;
            for(const auto * field:{"id","kind","actor_ref","target_ref","depends_on"}) summary[field]=goal[field];
            action["proposed_goals"].Vector().push_back(summary);
        }
    // Keep one bounded own refusal until the next accepted decision; native
    // actions can evict the general eight-result history before that review.
    auto & feedback=persisted["memory"]["decision_feedback"];
    feedback=JsonNode();
    if(!accepted) { feedback["reason"]=action["reason"];feedback["failure"]=action["failure"]; }
    externalai::recordResult(persisted["memory"],request["identity"]["day"].Integer(),action,false);
    persisted["memory"]["recent_results"].Vector().back()["outcome"].String()=accepted ? "strategy_accepted" : "strategy_rejected";
    trace["accepted"].Bool() = accepted;
    trace["fallback_reason"].String() = reason;
    trace["elapsed_ms"].Integer() = elapsed;
    trace["charged_tokens"].Integer() = consumed;
    trace["requests_this_turn"].Integer() = arbiter.requestsThisTurn();
    trace["remaining_wait_ms"].Integer() = arbiter.remainingBudget().waitMs;
    trace["remaining_tokens"].Integer() = arbiter.remainingBudget().tokens;
    trace["revision"] = campaign.plan()["revision"];
    trace["strategic_intent"]=persisted["strategic_intent"];
    trace["strategy_update"]=proposal["strategy_update"];
    trace["strategy_status"].String()=accepted ? "installed" : "proposed_rejected";
    logAi->info("NK3_STRATEGY %s",trace.toCompactString());
    recordLearningTurn(ai,"decision");
    persist(ai);
    return true;
    }
    catch(...)
    {
        const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-started).count();
        arbiter.finished(elapsed,consumed);
        saveArbiter();
        throw;
    }
}
}
