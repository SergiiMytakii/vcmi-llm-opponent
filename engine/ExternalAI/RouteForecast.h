#pragma once
#include "json/JsonNode.h"
#include <set>

namespace externalai
{
// Called only for remembered objects absent from the current sightings. A
// currently visible old tile therefore refutes positional proximity immediately.
inline bool rememberedThreatStillPossible(const JsonNode & sighting, const JsonNode & visiblePositions)
{
	if(sighting["not_seen_at_last_position"].Bool()) return false;
	for(const auto & position : visiblePositions.Vector())
		if(position == sighting["position"]) return false;
	return true;
}

// A town's defense is separate from a hero's next stopping place. All inputs
// are player-visible DTOs or previously observed sightings; no hidden routes.
inline JsonNode townDefense(const JsonNode & town, const JsonNode & observation,
	const JsonNode & memory, const JsonNode & actions, const JsonNode & visiblePositions,
	const std::set<int> & enemyPlayers)
{
	JsonNode result;
	result["town_army_ai_value"] = town["strength"];
	result["fort_level"] = town["fort_level"];
	result["stationed_heroes"] = town["stationed_heroes"];
	result["strength_basis"].String() = "separate_forces_not_siege_prediction";
	result["threats"].Vector();
	result["unseen_threats"].String() = "unknown";
	result["return_options"].Vector();
	result["reinforcement_action_ids"].Vector();
	auto addThreat = [&](const JsonNode & sighting, bool stale) {
		if(sighting["kind"].String() != "hero" || !enemyPlayers.count(sighting["owner"].Integer())
			|| (stale && !rememberedThreatStillPossible(sighting, visiblePositions))) return;
		const auto & position = sighting["position"].Vector();
		const auto & townPosition = town["position"].Vector();
		if(position.size() != 3 || townPosition.size() != 3 || position[2] != townPosition[2]) return;
		JsonNode threat;
		threat["object_id"] = sighting["id"];
		threat["position"] = sighting["position"];
		threat["tile_distance"].Integer() = std::max(std::abs(position[0].Integer()-townPosition[0].Integer()), std::abs(position[1].Integer()-townPosition[1].Integer()));
		threat["distance_basis"].String() = "last_observed_position_not_enemy_route";
		threat["age_days"].Integer() = stale ? std::max<int>(0, observation["day"].Integer()-sighting["last_seen_day"].Integer()) : 0;
		threat["stale"].Bool() = stale;
		threat["army"] = sighting["army"];
		threat["arrival_turn_offset"] = JsonNode();
		result["threats"].Vector().push_back(threat);
	};
	std::set<int> current;
	for(const auto & sighting : observation["visible_objects"].Vector())
	{
		current.insert(sighting["id"].Integer());
		addThreat(sighting, false);
	}
	for(const auto & sighting : memory["known_objects"].Vector())
		if(!current.count(sighting["id"].Integer())) addThreat(sighting, true);
	for(const auto & action : actions.Vector())
	{
		if(action["kind"].String() == "visit" && action["object_id"] == town["id"])
		{
			JsonNode option;
			option["action_id"] = action["id"];
			for(const auto * key : {"hero", "travel_turns", "route_steps", "arrival_turn_offset", "turn_stop", "route_encounters"}) option[key] = action[key];
			option["availability"].String() = "offered_route_revalidate_before_move";
			result["return_options"].Vector().push_back(option);
		}
		if(action["kind"].String() == "recruit" && action["town"] == town["id"])
			result["reinforcement_action_ids"].Vector().push_back(action["id"]);
	}
	result["missing_return_route"].String() = "unknown_or_not_currently_offered";
	return result;
}

// Nodes are projected from the player-scoped pathfinder in movement order.
inline JsonNode routeForecast(const JsonNode & origin, const JsonNode & nodes)
{
	JsonNode forecast;
	forecast["position"] = origin;
	forecast["condition"].String() = "unchanged_route";
	forecast["encounters"].Vector();
	for(const auto & node : nodes.Vector())
	{
		if(node["turn"].Integer() > 0) break;
		if(!node["stops_before_tile"].Bool()) forecast["position"] = node["position"];
		if(node["interaction"].Bool())
		{
			forecast["interaction_position"] = node["position"];
			forecast["encounters"].Vector().push_back(node);
			forecast["condition"].String() = "interaction_outcome_unknown";
			break;
		}
	}
	forecast["possible_positions"].Vector().push_back(forecast["position"]);
	return forecast;
}
}
