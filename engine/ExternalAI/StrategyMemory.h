#pragma once

#include "json/JsonNode.h"
#include <boost/uuid/random_generator.hpp>
#include <boost/uuid/uuid_io.hpp>

// Value-only memory. The caller supplies an already player-visible projection.
// Never query the game state or accept facts from the model in this module.
namespace externalai
{
// Random identity independent of map contents. Stored in the AI namespace so
// retries, controller restarts and loading the same save retain the same owner.
inline std::string initializeExperience(JsonNode & state)
{
	if(!state["experience_id"].isString() || state["experience_id"].String().empty())
		state["experience_id"].String() = boost::uuids::to_string(boost::uuids::random_generator()());
	return state["experience_id"].String();
}

// Private engine-ID -> observed-object label map. Never include this map in a
// controller request: gaps in the engine's IDs reveal unobserved map objects.
inline int objectAlias(JsonNode & aliases, int engineID)
{
	const auto key = std::to_string(engineID);
	auto & entries = aliases.Struct();
	if(const auto found = entries.find(key); found != entries.end())
		return found->second.Integer();
	int next = 0;
	for(const auto & [id, value] : entries) next = std::max(next, static_cast<int>(value.Integer()) + 1);
	entries[key].Integer() = next;
	return next;
}

inline bool initializeObjectAliases(JsonNode & state)
{
	if(!state["object_ids"].isNull()) return false;
	// Do not migrate the old developer protocol's global object numbers back
	// into requests. Even free-form plan prose can contain those old numbers.
	// Only its AI memory/intent is incompatible; preserve the consumed budget.
	const bool discarded = !state["memory"].isNull() || !state["pending"].isNull();
	state.Struct().erase("memory");
	state.Struct().erase("pending");
	state["object_ids"].Struct();
	return discarded;
}

inline std::string objectReference(const JsonNode & id)
{
	return "object:" + std::to_string(id.Integer());
}

inline std::set<std::string> knownTargets(const JsonNode & memory, const JsonNode & actions)
{
	std::set<std::string> result;
	for(const auto & item : memory["known_objects"].Vector())
		result.insert(item["ref"].String());
	for(const auto & action : actions.Vector())
		if(action["target_ref"].isString()) result.insert(action["target_ref"].String());
	if(memory["plan"]["target_ref"].isString()) result.insert(memory["plan"]["target_ref"].String());
	return result;
}

inline bool validCondition(const JsonNode & condition, bool completion = false)
{
	if(!condition.isStruct() || condition.Struct().size() != 2 || !condition.Struct().count("value") || !condition["kind"].isString()) return false;
	const auto & kind = condition["kind"].String();
	const auto & value = condition["value"];
	if(kind == "day_at_least" || kind == "army_strength_at_least")
		return value.getType() == JsonNode::JsonType::DATA_INTEGER && value.Integer() >= 0 && value.Integer() <= 2147483647;
	if(kind == "confirmed_action")
		return value.isString() && (value.String() == "build" || value.String() == "recruit" || value.String() == "transfer" || value.String() == "upgrade");
	return value.isNull() && (kind == "unknown" || (!completion && kind == "always") || kind == "executor_at_target" || kind == "target_owned");
}

inline void initializePlanSchema(JsonNode & state)
{
	auto & memory = state["memory"];
	if(memory.isNull()) return;
	if(memory["schema"].Integer() != 2)
	{
		// Only incompatible intentions are reset: observations, outcomes, object
		// aliases, pending execution evidence and consumed decisions survive load.
		memory["plan"] = JsonNode();
		memory.Struct().erase("plan_tracking");
		memory["plan_review"]["status"].String() = "legacy_intent_reset";
		memory["schema"].Integer() = 2;
	}
}

inline bool validStrategy(const JsonNode & plan, const JsonNode & memory, const JsonNode & actions)
{
	if(plan.isNull()) return true;
	if(!plan.isStruct() || plan.Struct().size() != 11 || plan.toCompactString().size() > 4096) return false;
	for(const auto * key : {"goal", "rationale", "reserves", "progress", "change_reason"})
		if(!plan[key].isString() || plan[key].String().empty() || plan[key].String().size() > 240) return false;
	for(const auto * key : {"steps", "reconsider_if"})
	{
		if(!plan[key].isVector() || plan[key].Vector().empty() || plan[key].Vector().size() > 4) return false;
		for(const auto & item : plan[key].Vector())
			if(!item.isString() || item.String().empty() || item.String().size() > 160) return false;
	}
	if(!plan.Struct().count("executor_ref") || !validCondition(plan["ready_when"]) || !validCondition(plan["complete_when"], true)) return false;
	if(!plan["executor_ref"].isNull())
	{
		if(!plan["executor_ref"].isString()) return false;
		bool owned = false;
		for(const auto & hero : memory["own_heroes"].Vector())
			owned |= objectReference(hero["id"]) == plan["executor_ref"].String();
		if(!owned) return false;
	}
	for(const auto * key : {"ready_when", "complete_when"})
	{
		const auto & kind = plan[key]["kind"].String();
		if((kind == "army_strength_at_least" || kind == "executor_at_target") && plan["executor_ref"].isNull()) return false;
		if((kind == "target_owned" || kind == "executor_at_target" || kind == "confirmed_action") && plan["target_ref"].isNull()) return false;
	}
	if(!plan.Struct().count("target_ref")) return false;
	return plan["target_ref"].isNull() || (plan["target_ref"].isString()
		&& knownTargets(memory, actions).count(plan["target_ref"].String()));
}

inline void reviewPlan(JsonNode & memory, const JsonNode & observation)
{
	const auto & plan = static_cast<const JsonNode &>(memory)["plan"];
	if(plan.isNull()) return;
	JsonNode executor, target;
	for(const auto & hero : observation["heroes"].Vector())
		if(plan["executor_ref"].isString() && objectReference(hero["id"]) == plan["executor_ref"].String()) executor = hero;
	for(const auto & object : memory["known_objects"].Vector())
		if(plan["target_ref"].isString() && object["ref"].String() == plan["target_ref"].String()) target = object;
	const JsonNode ownedExecutor = executor, knownTarget = target;
	auto conditionStatus = [&](const JsonNode & condition) -> std::string {
		const auto & kind = condition["kind"].String();
		if(kind == "always") return "met";
		if(kind == "day_at_least") return observation["day"].Integer() >= condition["value"].Integer() ? "met" : "not_met";
		if(kind == "army_strength_at_least" && ownedExecutor["strength"]["army_ai_value"].isNumber())
			return ownedExecutor["strength"]["army_ai_value"].Float() >= condition["value"].Integer() ? "met" : "not_met";
		if(kind == "executor_at_target" && !ownedExecutor.isNull() && knownTarget["position"].isVector())
			return ownedExecutor["position"] == knownTarget["position"] ? "met" : "not_met";
		if(kind == "target_owned" && knownTarget["owner"].isNumber() && !knownTarget["stale"].Bool() && !knownTarget["not_seen_at_last_position"].Bool())
			return knownTarget["owner"] == observation["player"] ? "met" : "not_met";
		if(kind == "confirmed_action")
		{
			for(const auto & result : memory["recent_results"].Vector())
				if(result["outcome"].String() == "completed" && result["action"]["kind"] == condition["value"]
					&& result["action"]["target_ref"] == plan["target_ref"]
					&& (plan["executor_ref"].isNull() || objectReference(result["action"]["destination"]) == plan["executor_ref"].String())
					&& result["sequence"].Integer() > memory["plan_result_cursor"].Integer()) return "met";
			return "not_met";
		}
		return "unknown";
	};
	JsonNode signature;
	for(const auto * key : {"target_ref", "executor_ref", "ready_when", "complete_when"}) signature[key] = plan[key];
	JsonNode progress;
	progress["position"] = ownedExecutor["position"];
	progress["army"] = ownedExecutor["army"];
	progress["target_position"] = knownTarget["position"];
	progress["target_owner"] = knownTarget["owner"];
	for(const auto & town : observation["towns"].Vector())
		if(plan["target_ref"].isString() && objectReference(town["id"]) == plan["target_ref"].String())
		{
			progress["town"] = town;
			for(auto & stock : progress["town"]["stock"].Vector()) stock.Struct().erase("days_to_next_growth");
		}
	if(plan["executor_ref"].isNull()) progress["resources"] = observation["resources"];
	auto & tracking = memory["plan_tracking"];
	const auto oldReady = static_cast<const JsonNode &>(tracking)["ready"].String();
	if(tracking["signature"] != signature || tracking["snapshot"] != progress)
	{
		tracking["last_change_day"] = observation["day"];
		tracking["signature"] = signature;
		tracking["snapshot"] = progress;
	}
	const auto ready = conditionStatus(plan["ready_when"]);
	const auto complete = conditionStatus(plan["complete_when"]);
	auto & review = memory["plan_review"];
	review = JsonNode();
	review["ready"].String() = ready;
	review["complete"].String() = complete;
	review["last_observed_change_day"] = tracking["last_change_day"];
	const int unchanged = observation["day"].Integer() - tracking["last_change_day"].Integer();
	review["unchanged_days"].Integer() = unchanged;
	review["status"].String() = "active";
	if(plan["executor_ref"].isString() && observation["heroes"].isVector() && ownedExecutor.isNull())
	{
		review["status"].String() = "infeasible";
		review["reason"].String() = "executor_no_longer_owned";
	}
	else if(complete == "met") review["status"].String() = "completed";
	else if(oldReady == "met" && ready == "not_met")
	{
		review["status"].String() = "requires_revision";
		review["reason"].String() = "readiness_premise_changed";
	}
	else if(ready == "not_met" && plan["ready_when"]["kind"].String() == "day_at_least")
		review["status"].String() = "waiting_for_readiness";
	else if(unchanged >= 2)
	{
		review["status"].String() = "requires_revision";
		review["reason"].String() = "no_observed_progress_for_two_days";
	}
	tracking["ready"].String() = ready;
}

inline void observeMemory(JsonNode & memory, const JsonNode & observation, JsonNode & actions,
	const JsonNode & visiblePositions)
{
	if(memory.isNull())
	{
		memory["schema"].Integer() = 2;
		memory["plan"] = JsonNode();
		memory["recent_results"].Vector();
	}
	const int day = observation["day"].Integer();
	// Only the explicit complete own list can confirm loss of ownership.
	// Old observations without this field preserve unknown, never imply death.
	if(observation["heroes"].isVector())
	{
		std::set<int> current;
		for(const auto & hero : observation["heroes"].Vector()) current.insert(hero["id"].Integer());
		for(const auto & hero : memory["own_heroes"].Vector())
			if(!current.count(hero["id"].Integer()))
			{
				JsonNode loss;
				loss["day"].Integer() = day;
				loss["hero"] = hero["id"];
				loss["outcome"].String() = "no_longer_owned";
				memory["own_force_changes"].Vector().push_back(loss);
			}
		auto & changes = memory["own_force_changes"].Vector();
		if(changes.size() > 8) changes.erase(changes.begin(), changes.end() - 8);
		memory["own_heroes"] = observation["heroes"];
	}

	std::map<std::string, JsonNode> facts;
	std::set<std::string> visible;
	for(const auto & position : visiblePositions.Vector()) visible.insert(position.toCompactString());
	for(auto item : memory["known_objects"].Vector())
	{
		item["stale"].Bool() = true;
		if(item["kind"].String() != "frontier" && visible.count(item["position"].toCompactString()))
			item["not_seen_at_last_position"].Bool() = true;
		facts[item["ref"].String()] = item;
	}
	auto remember = [&](JsonNode item, const std::string & ref) {
		item["ref"].String() = ref;
		item["last_seen_day"].Integer() = day;
		item["stale"].Bool() = false;
		item["not_seen_at_last_position"].Bool() = false;
		facts[ref] = item;
	};
	for(const auto & item : observation["visible_objects"].Vector())
		remember(item, objectReference(item["id"]));
	for(auto & action : actions.Vector())
	{
		if(action["object_id"].isNumber())
			action["target_ref"].String() = objectReference(action["object_id"]);
		else if(action["town"].isNumber())
			action["target_ref"].String() = objectReference(action["town"]);
		else if(action["destination"].isNumber())
			action["target_ref"].String() = objectReference(action["destination"]);
		else if(action["target"].isVector())
		{
			const auto ref = "tile:" + action["target"].toCompactString();
			action["target_ref"].String() = ref;
			JsonNode item;
			item["position"] = action["target"];
			item["kind"].String() = "frontier";
			remember(item, ref);
		}
	}
	JsonVector ordered;
	for(const auto & [ref, item] : facts) ordered.push_back(item);
	const auto & plan = static_cast<const JsonNode &>(memory)["plan"];
	const auto target = plan["target_ref"].isString() ? plan["target_ref"].String() : std::string{};
	std::sort(ordered.begin(), ordered.end(), [&](const JsonNode & a, const JsonNode & b) {
		const bool ap = a["ref"].String() == target, bp = b["ref"].String() == target;
		if(ap != bp) return ap;
		if(a["last_seen_day"].Integer() != b["last_seen_day"].Integer())
			return a["last_seen_day"].Integer() > b["last_seen_day"].Integer();
		return a["ref"].String() < b["ref"].String();
	});
	if(ordered.size() > 128) ordered.resize(128);
	memory["known_objects"].Vector() = std::move(ordered);
	reviewPlan(memory, observation);
}

inline void recordResult(JsonNode & memory, int day, const JsonNode & action, bool confirmed)
{
	if(!action.isStruct() || action["kind"].String() == "end_turn") return;
	JsonNode result;
	result["day"].Integer() = day;
	result["sequence"].Integer() = memory["result_sequence"].Integer() + 1;
	memory["result_sequence"] = result["sequence"];
	result["action"] = action;
	const auto kind = action["kind"].String();
	const bool movement = kind == "attack" || kind == "visit" || kind == "explore";
	result["outcome"].String() = !confirmed ? "unconfirmed" : movement ? "progress_observed" : "completed";
	auto & history = memory["recent_results"].Vector();
	history.push_back(result);
	if(history.size() > 8) history.erase(history.begin(), history.end() - 8);
}
}
