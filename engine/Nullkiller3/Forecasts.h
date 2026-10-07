#pragma once
#include "json/JsonNode.h"
#include "CampaignState.h"
#include <algorithm>
#include <array>
#include <limits>
#include <functional>
#include <set>

namespace nullkiller3
{
// A value-only strategic boundary; native purchases remain separate commands.
std::string allocationCheckpointFacts(const CampaignState & campaign,const JsonNode & world);
inline bool supportedDeliveryWait(const JsonNode & forecasts,const JsonNode & goal,int64_t day)
{
    for(const auto & delivery:forecasts["deliveries"].Vector())
        if(delivery["goal_id"]==goal["id"] && delivery["status"].String()=="conditional"
            && delivery["arrival_day"].Integer()>day
            && delivery["arrival_day"].Integer()<=goal["deadline_day"].Integer()) return true;
    return false;
}
bool buildingSequence(const JsonNode & town, const JsonNode & target, std::vector<const JsonNode *> & sequence);

// Recurring income for a specific future day, from own post-handicap base
// income and loaded AI bonus rules. Building deltas change that base first.
JsonNode forecastDailyIncome(const JsonNode & world, int64_t date, const JsonNode & baseIncome);

// Public, value-only forecast seam. Inputs are complete own facts and visible
// route estimates; no game state, opponent pointer or hidden bonus is accepted.
JsonNode forecastBranches(const JsonNode & world, const JsonNode & reserves, const JsonNode & selectedGoal = JsonNode());

// Current physical army pools and own routes are sufficient to assess a
// handoff of existing troops. Recruitment, new roads, battles and slot packing
// are explicit conditions, never a factual future army or promised victory.
inline int64_t minimumRetainedArmyValue(const std::string & pool,const JsonNode & world)
{
    for(const auto & hero:world["heroes"].Vector())
        if(hero["ref"].String()==pool) return std::max<int64_t>(0,hero["minimum_retained_army_value"].Integer());
    return 0; // A town's physical garrison may be emptied; a hero may not.
}
inline const JsonNode * ownArmyUnits(const std::string & pool,const JsonNode & world)
{
    for(const auto & hero:world["heroes"].Vector())
        if(hero["ref"].String()==pool) return &hero["army_units"];
    for(const auto & town:world["towns"].Vector())
        if(CampaignState::armyPool(town["ref"].String(),world)==pool) return &town["army_units"];
    return nullptr;
}
// Pool surplus is a conservative whole-unit selection. A reserved delivery
// additionally follows native source-slot order and matching/free-slot packing;
// that branch cannot swap away the protected recipient's existing stacks.
int64_t wholeCreatureSourceFloor(const std::string & pool,int64_t power,
    int64_t required,const JsonNode & world,const JsonNode * recipientUnits=nullptr);
JsonNode forecastDeliveries(const JsonNode & world, const CampaignState & campaign,
    const std::map<std::string,std::string> & replacements = {});

// One bounded calendar for accepted construction and town-source recruitment.
// This is a conditional branch, not a simulator of unseen routes or battles.
JsonNode forecastCommitments(const JsonNode & world, const CampaignState & campaign,
    const std::map<std::string,std::string> & replacements = {});

JsonNode forecastThreats(const JsonNode & world);

// Allocate current owned pools once across simultaneous fronts. These are
// conditional troop capacities on established own routes, not battle odds or
// a factual enemy ETA. No recruitment or future delivery is counted here.
JsonNode forecastDefenses(const JsonNode & world, const CampaignState & campaign);

// Counterfactual capacities, not decisions or battle guarantees. Each choice
// uses the same current pools and budget independently, never cumulatively.
JsonNode forecastTownChoices(const JsonNode & world,const CampaignState & campaign,
    const std::map<std::string,std::string> & replacements = {});
}
