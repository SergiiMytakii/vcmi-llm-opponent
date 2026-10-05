#include "../Nullkiller2/StdInc.h"
#include "NativeCampaign.h"
#include "StrategicDecision.h"
#include "Forecasts.h"
#include "../ExternalAI/ProcessExchange.h"
#include "../ExternalAI/TransportJSON.h"
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
        || !boundedInteger(saved["requests"],0,2147483647) || !boundedInteger(saved["wait_ms"],0,3600000)
        || !boundedInteger(saved["tokens"],0,10000000) || !boundedInteger(saved["critical_reserve_ms"],0,3600000)
        || !saved["addressed"].isStruct())
    { invalidBudget = true; logAi->warn("NK3 invalid saved request budget; native continuation only"); return; }
    ArbiterState restored;
    restored.day = saved["day"].Integer();
    restored.requests = saved["requests"].Integer();
    restored.remaining = {saved["wait_ms"].Integer(),saved["tokens"].Integer(),saved["critical_reserve_ms"].Integer()};
    for(const auto & [question, facts] : saved["addressed"].Struct())
    {
        if(question.empty() || question.size()>240 || !facts.isString() || facts.String().size()>8192)
        { invalidBudget = true; return; }
        restored.addressed[question] = facts.String();
    }
    arbiter = RequestArbiter(restored);
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
    persisted["checkpoint_baseline"]=baseline;
}
std::vector<StrategicSignal> NativeCampaign::strategicSignals(NK2AI::Nullkiller & ai)
{
    std::vector<StrategicSignal> result;
    bool actionable = !world["towns"].Vector().empty();
    for(const auto & hero : world["heroes"].Vector()) actionable |= hero["movement"].Integer() > 100;
    const auto checkpoint=allocationCheckpointSignals(campaign,world,persisted["checkpoint_baseline"],actionable);
    result.insert(result.end(),checkpoint.begin(),checkpoint.end());
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
        if(why == "executor_no_longer_owned" || why == "deadline_missed" || why=="target_no_longer_owned" || why=="dependency_failed" || why=="force_floor_breached" || why=="force_continuity_unconfirmed")
            result.push_back({"commitment:"+goal["id"].String(),why,true,true,actionable,true});
    }
    if(!campaign.plan().isNull())
    {
        const auto saved = campaign.save();
        if(world["day"].Integer() >= saved["accepted_day"].Integer()+campaign.plan()["horizon_days"].Integer())
            result.push_back({"horizon",std::to_string(campaign.plan()["revision"].Integer()),true,true,actionable,false});
    }
    bool exhausted=!campaign.plan().isNull();
    for(const auto & goal:campaign.plan()["goals"].Vector())
        exhausted &= world["goal_statuses"][goal["id"].String()]["state"].String()=="completed";
    if(exhausted) result.push_back({"campaign_exhausted",std::to_string(campaign.plan()["revision"].Integer()),true,true,actionable,false});
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
        if(!defense["critical"].Bool() || defense["scenario_deadline_day"].Integer()>world["day"].Integer()+1
            || (status!="insufficient_current_force" && status!="unbounded_opposition")) continue;
        std::string facts=status+":";
        for(const auto & threat:defense["threats"].Vector())
            facts+=threat["source_ref"].String()+":"+threat["army_interval"].toCompactString()+";";
        result.push_back({"defense:"+defense["town_ref"].String(),facts,true,true,actionable,true});
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
bool NativeCampaign::reviewStrategy(NK2AI::Nullkiller & ai)
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
    arbiter.beginTurn(world["day"].Integer(), {140000,120000,20000});
    auto decision = arbiter.consider(strategicSignals(ai));
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
    decision.deadlineMs = std::min<int64_t>(decision.deadlineMs,70000);
    JsonNode request;
    request["protocol"].Integer() = 2;
    const auto revision = campaign.plan()["revision"].Integer();
    request["identity"] = identity(persisted,generation,world,revision);
    const int64_t sequence = persisted["request_sequence"].Integer()+1;
    request["request_id"].String() = persisted["experience_id"].String()+":"+generation+":"
        +std::to_string(ai.playerID.getNum())+":"+std::to_string(world["day"].Integer())+":"
        +std::to_string(revision)+":"+std::to_string(sequence);
    request["observation"] = world;
    request["memory"] = persisted["memory"];
    request["memory"]["experience_id"] = persisted["experience_id"];
    request["campaign"] = campaign.plan();
    request["signals"] = trace["signals"];
    request["budget"]["wait_ms"].Integer() = decision.deadlineMs;
    request["budget"]["tokens"].Integer() = arbiter.remainingBudget().tokens;
    for(const auto * key : {"day","resources","victory","rules"})
        request["evidence_refs"].Vector().emplace_back("observation:"+std::string(key));
    for(const auto & hero : world["heroes"].Vector()) request["evidence_refs"].Vector().emplace_back("hero:"+hero["ref"].String());
    for(const auto & town : world["towns"].Vector()) request["evidence_refs"].Vector().emplace_back("town:"+town["ref"].String());
    for(const auto & object : world["objects"].Vector()) request["evidence_refs"].Vector().emplace_back("target:"+object["ref"].String());
    const auto input = externalai::transportJSON(request.toCompactString());
    exchangeCancelled = false; // Reset only inside the serialized current-turn worker under GS lock.
    arbiter.dispatched(decision);
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
            input,std::chrono::milliseconds(decision.deadlineMs),exchangeCancelled);
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
    std::string reason = response.error;
    bool factsUnchanged = true;
    for(const auto * key : {"heroes","towns","resources","visible_objects","shipyards","frontiers","victory"})
        factsUnchanged &= world[key] == request["observation"][key];
    if(!stopping && factsUnchanged && ai.cc->isPlayerMakingTurn(ai.playerID)
        && request["identity"] == identity(persisted,generation,world,campaign.plan()["revision"].Integer())
        && response.error.empty())
    {
        JsonParsingSettings parser; parser.strict = true; parser.mode = JsonParsingSettings::JsonFormatMode::JSON;
        JsonNode reply(response.output.data(),response.output.size(),parser,"NK3 strategic reply");
        const auto & usage = static_cast<const JsonNode &>(reply)["usage"];
        if(usage["known"].isBool() && usage["known"].Bool() && boundedInteger(usage["input_tokens"],0,1000000000)
            && boundedInteger(usage["output_tokens"],0,1000000000))
            consumed = usage["input_tokens"].Integer()+usage["output_tokens"].Integer();
        CampaignState candidate;
        accepted = validateStrategicDecision(reply,request,world,campaign,candidate,reason);
        if(accepted && reply["decision"].String() == "retain" && persisted["strategy_metadata"].isStruct()
            && reply["assignments"] != persisted["strategy_metadata"]["assignments"])
        { accepted = false; reason = "retained_plan_changed_roles_without_revision"; }
        if(accepted)
        {
            campaign = candidate;
            acceptedLossRatio=campaign.plan()["policy"]["max_loss_ratio"].Float();
            acceptedRevision=campaign.plan()["revision"].Integer();
            persisted["strategy_metadata"] = reply;
            persisted["pending_strategic_questions"] = JsonNode();
            world["goal_statuses"] = campaign.review(world);
            // Model roles/reserves change path and hero analysis as well as
            // the goal list. Rebuild those owners before creating any command.
            ai.invalidatePathfinderData();
            ai.updateState();
            recordCheckpointBaseline(); // New goals/reserves own the next review's comparison.
        }
    }
    else if(reason.empty()) reason = "stale_or_cancelled_strategic_reply";
    arbiter.finished(elapsed,consumed);
    trace["accepted"].Bool() = accepted;
    trace["fallback_reason"].String() = reason;
    trace["elapsed_ms"].Integer() = elapsed;
    trace["charged_tokens"].Integer() = consumed;
    trace["requests_this_turn"].Integer() = arbiter.requestsThisTurn();
    trace["remaining_wait_ms"].Integer() = arbiter.remainingBudget().waitMs;
    trace["remaining_tokens"].Integer() = arbiter.remainingBudget().tokens;
    trace["revision"] = campaign.plan()["revision"];
    logAi->info("NK3_STRATEGY %s",trace.toCompactString());
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
