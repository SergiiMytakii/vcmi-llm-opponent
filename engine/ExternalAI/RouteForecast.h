#pragma once
#include "json/JsonNode.h"

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
