#include "Global.h"
#include "StrategicContext.h"
#include "StrategicCandidates.h"
#include "StrategicDecision.h"
#include "StrategicIntent.h"

namespace nullkiller3
{
StrategicContext buildStrategicContext(const JsonNode & world, const CampaignState & campaign,
    const JsonNode & persisted, const StrategicContextOptions & options)
{
    StrategicContext result;
    const bool preparation = options.preparation;
    const bool detailed = options.detailed;
    const auto & intent = persisted["strategic_intent"];
    const auto & metadata = persisted["strategy_metadata"];
    auto & observation = result.observation;
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
    if(!preparation && options.includeIdle) observation["main_army_idle"] = mainArmyIdle(campaign, world);
    result.memory = strategicCandidateMemory(persisted["memory"], observation);
    if(!preparation) result.memory["experience_id"] = persisted["experience_id"];
    auto & evidence = result.evidenceRefs.Vector();
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
    return result;
}
}
