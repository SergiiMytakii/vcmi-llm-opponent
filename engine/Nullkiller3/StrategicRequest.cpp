#include "Global.h"
#include "StrategicRequest.h"
#include "StrategicCandidates.h"
#include "StrategicDecision.h"
#include "StrategicIntent.h"
#include "../TransportJSON/TransportJSON.h"

namespace nullkiller3
{
StrategicRequest buildStrategicRequest(const JsonNode & world, const CampaignState & campaign,
    const JsonNode & persisted, const StrategicRequestParameters & parameters)
{
    StrategicRequest result;
    auto & request = result.request;
    const auto & preparation = parameters.preparation;
    const auto & intent = persisted["strategic_intent"];
    const auto & metadata = persisted["strategy_metadata"];
    request["protocol"].Integer() = 2;
    request["identity"] = parameters.identity;
    request["request_id"].String() = parameters.requestID;
    request["strategic_intent"] = intent;
    request["campaign"] = campaign.plan();
    bool detailed = intent.isNull();
    if(preparation)
    {
        detailed = preparation->strategicReview;
        request["mode"].String() = "prepare_next_turn";
        request["execution_day"].Integer() = preparation->executionDay;
        request["intent_revision"] = intent["revision"];
        request["strategic_review"].Bool() = detailed;
        request["allowed_actor_refs"] = preparation->scope["actors"];
        request["allowed_target_refs"] = preparation->scope["targets"];
        request["routine_needs"] = preparation->scope["needs"];
    }
    else
        for(const auto & signal : parameters.signals)
            detailed |= signal.question.starts_with("strategy:") || signal.question.starts_with("battle_loss:")
                || signal.question.starts_with("critical_town:") || signal.question.starts_with("defense:")
                || signal.question.starts_with("checkpoint:") || signal.question.starts_with("stagnation:");

    auto & observation = request["observation"];
    observation = strategicCandidateView(world, campaign.plan(), intent, detailed);
    observation["accepted_decision_basis"] = metadata["decision_basis"];
    observation["operation_progress"] = persisted["operation_progress"];
    observation["strategy_assignments"] = metadata["assignments"];
    if(!observation["strategy_assignments"].isVector()) observation["strategy_assignments"].Vector();
    if(!preparation || detailed)
    {
        observation["map_overview"] = strategicMapOverview(world, intent, detailed);
        observation["strategy_stalls"] = strategicStalls(intent, world);
    }
    if(!preparation && parameters.includeIdle) observation["main_army_idle"] = mainArmyIdle(campaign, world);
    request["memory"] = strategicCandidateMemory(persisted["memory"], observation);
    if(!preparation) request["memory"]["experience_id"] = persisted["experience_id"];
    for(const auto & signal : parameters.signals)
    {
        JsonNode item;
        item["question"].String() = signal.question;
        item["facts"].String() = signal.facts;
        item["critical"].Bool() = signal.critical;
        request["signals"].Vector().push_back(item);
    }
    request["budget"]["wait_ms"].Integer() = parameters.waitMs;
    request["budget"]["tokens"].Integer() = parameters.tokens;
    auto & evidence = request["evidence_refs"].Vector();
    for(const auto * field : {"day", "resources", "victory", "rules", "goal_feedback", "offensive_preparation",
        "main_army_idle", "scouting_options", "map_overview", "strategy_stalls", "automatic_safety_reviews", "decision_feedback"})
        evidence.emplace_back("observation:" + std::string(field));
    // Preserve the existing background evidence order, including repeated labels.
    if(preparation && detailed)
        for(const auto * field : {"map_overview", "strategy_stalls"})
            evidence.emplace_back("observation:" + std::string(field));
    for(const auto & hero : observation["heroes"].Vector()) evidence.emplace_back("hero:" + hero["ref"].String());
    for(const auto & town : observation["towns"].Vector()) evidence.emplace_back("town:" + town["ref"].String());
    for(const auto & object : observation["objects"].Vector()) evidence.emplace_back("target:" + object["ref"].String());
    if(!preparation)
        for(const auto & object : observation["map_overview"]["objects"].Vector())
        {
            const JsonNode ref("target:" + object["ref"].String());
            if(std::find(evidence.begin(), evidence.end(), ref) == evidence.end()) evidence.push_back(ref);
        }
    boundStrategicRequest(request);
    if(preparation)
    {
        std::set<std::string> exposed;
        for(const auto * list : {"heroes", "towns", "objects", "visible_objects"})
            for(const auto & item : observation[list].Vector()) exposed.insert(item["ref"].String());
        for(const auto & ref : observation["frontiers"].Vector()) exposed.insert(ref.String());
        std::erase_if(request["allowed_target_refs"].Vector(), [&](const auto & ref) { return !exposed.count(ref.String()); });
    }
    result.wire = ai_transport::transportJSON(request.toCompactString());
    return result;
}
}
