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
		return value.isString() && (value.String() == "build" || value.String() == "recruit" || value.String() == "transfer" || value.String() == "upgrade" || value.String() == "hire_hero");
	return value.isNull() && (kind == "unknown" || (!completion && kind == "always") || kind == "executor_at_target" || kind == "target_owned");
}

inline void initializePlanSchema(JsonNode & state)
{
	auto & memory = state["memory"];
	if(memory.isNull()) return;
	if(!memory.Struct().count("campaign")) memory["campaign"] = JsonNode();
	if(memory["schema"].Integer() != 2)
	{
		// Only incompatible intentions are reset: observations, outcomes, object
		// aliases, pending execution evidence and consumed decisions survive load.
		memory["plan"] = JsonNode();
		memory["campaign"] = JsonNode();
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

inline void reviewPlan(JsonNode & memory, const JsonNode & observation, const JsonNode & actions)
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
	auto & tracking = memory["plan_tracking"];
	const auto oldReady = static_cast<const JsonNode &>(tracking)["ready"].String();
	const bool initial = tracking["signature"] != signature || tracking["basis"].String() != "goal_progress_v1";
	if(initial)
	{
		tracking = JsonNode();
		tracking["signature"] = signature;
		tracking["basis"].String() = "goal_progress_v1";
	}
	bool progressed = initial;
	// Distances to different observed positions are not comparable.
	if(tracking["route_target_position"] != knownTarget["position"])
	{
		tracking.Struct().erase("best_route_steps");
		tracking["route_target_position"] = knownTarget["position"];
	}
	// Keep high-water marks: returning to a previously reached distance or army
	// size cannot refresh an unchanged objective. Missing routes remain unknown.
	for(const auto & action : actions.Vector())
		if(action["target_ref"] == plan["target_ref"] && plan["executor_ref"].isString()
			&& action["hero"].isNumber() && objectReference(action["hero"]) == plan["executor_ref"].String()
			&& action["route_steps"].isNumber())
		{
			const auto steps = action["route_steps"].Integer();
			if(!tracking["best_route_steps"].isNumber() || steps < tracking["best_route_steps"].Integer())
			{
				progressed |= !initial;
				tracking["best_route_steps"].Integer() = steps;
			}
		}
	const auto & strength = ownedExecutor["strength"]["army_ai_value"];
	if(strength.isNumber() && (!tracking["best_army_value"].isNumber() || strength.Float() > tracking["best_army_value"].Float()))
	{
		progressed |= !initial && tracking["best_army_value"].isNumber();
		tracking["best_army_value"] = strength;
	}
	if(!knownTarget.isNull() && !knownTarget["stale"].Bool())
	{
		JsonNode information;
		for(const auto * key : {"position", "owner", "not_seen_at_last_position"}) information[key] = knownTarget[key];
		if(knownTarget["owner"] != observation["player"]) information["army"] = knownTarget["army"];
		if(tracking["target_information"] != information)
		{
			progressed = true;
			tracking["target_information"] = information;
		}
	}
	for(const auto & town : observation["towns"].Vector())
		if(plan["target_ref"].isString() && objectReference(town["id"]) == plan["target_ref"].String())
		{
			if(town["strength"].isNumber() && (!tracking["best_town_army_value"].isNumber() || town["strength"].Float() > tracking["best_town_army_value"].Float()))
			{
				progressed |= !initial && tracking["best_town_army_value"].isNumber();
				tracking["best_town_army_value"] = town["strength"];
			}
			for(const auto & building : town["buildings"].Vector())
				if(std::find(tracking["buildings"].Vector().begin(), tracking["buildings"].Vector().end(), building) == tracking["buildings"].Vector().end())
				{
					progressed = true;
					tracking["buildings"].Vector().push_back(building);
				}
		}
	if(plan["executor_ref"].isNull())
	{
		auto & best = tracking["best_resources"].Vector();
		const auto & current = observation["resources"].Vector();
		if(best.size() < current.size()) best.resize(current.size());
		for(size_t index = 0; index < current.size(); ++index)
			if(current[index].isNumber() && (!best[index].isNumber() || current[index].Float() > best[index].Float()))
			{
				progressed |= !initial && best[index].isNumber();
				best[index] = current[index];
			}
	}
	if(progressed)
	{
		tracking["last_change_day"] = observation["day"];
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

// Campaign intentions share the existing player-local memory and update boundary.
inline bool campaignText(const JsonNode & value)
{
    return value.isString() && !value.String().empty() && value.String().size() <= 160;
}

inline bool campaignFields(const JsonNode & value, std::initializer_list<const char *> fields)
{
    if(!value.isStruct() || value.Struct().size() != fields.size()) return false;
    for(const auto * field : fields) if(!value.Struct().count(field)) return false;
    return true;
}

inline bool campaignInteger(const JsonNode & value, int minimum, int maximum)
{
    return value.getType() == JsonNode::JsonType::DATA_INTEGER && value.Integer() >= minimum && value.Integer() <= maximum;
}

inline bool campaignApproach(const JsonNode & value)
{
    if(!value.isString()) return false;
    for(const auto * approach : {"economy", "expansion", "breakthrough", "defense", "conquest"})
        if(value.String() == approach) return true;
    return false;
}

inline std::set<std::string> campaignEvidence(const JsonNode & memory, const JsonNode & observation, const JsonNode & actions)
{
    std::set<std::string> refs;
    for(const auto * key : {"day", "resources", "victory", "rules"})
        if(observation.Struct().count(key)) refs.insert(std::string("observation:") + key);
    for(const auto & hero : observation["heroes"].Vector()) refs.insert("hero:" + objectReference(hero["id"]));
    for(const auto & town : observation["towns"].Vector()) refs.insert("town:" + objectReference(town["id"]));
    for(const auto & ref : knownTargets(memory, actions)) refs.insert("target:" + ref);
    for(const auto & result : memory["recent_results"].Vector())
        if(result["sequence"].getType() == JsonNode::JsonType::DATA_INTEGER
            && (result["outcome"].String() == "completed" || result["outcome"].String() == "progress_observed"))
            refs.insert("result:" + std::to_string(result["sequence"].Integer()));
    return refs;
}

inline bool validCampaign(const JsonNode & update, const JsonNode & operational, const JsonNode & memory,
    const JsonNode & observation, const JsonNode & actions)
{
    if(update.isNull()) return true;
    if(!campaignFields(update, {"decision", "reason", "evidence_refs", "plan"})
        || update.toCompactString().size() > 4096 || !campaignText(update["reason"])) return false;
    const auto evidence = campaignEvidence(memory, observation, actions);
    if(!update["evidence_refs"].isVector() || update["evidence_refs"].Vector().empty() || update["evidence_refs"].Vector().size() > 4) return false;
    for(const auto & ref : update["evidence_refs"].Vector())
        if(!ref.isString() || !evidence.count(ref.String())) return false;
    if(!update["decision"].isString()) return false;
    const bool retain = update["decision"].String() == "retain";
    if(!retain && update["decision"].String() != "revise") return false;
    if(retain && (!update["plan"].isNull() || memory["campaign"].isNull())) return false;
    const auto & plan = retain ? memory["campaign"] : update["plan"];
    if(!campaignFields(plan, {"victory_method", "approach", "main_hero_ref", "horizon_day", "advantages", "milestones", "assignments", "reserves", "alternatives"})) return false;
    std::set<std::string> heroes;
    for(const auto & hero : observation["heroes"].Vector()) heroes.insert(objectReference(hero["id"]));
    const auto targets = knownTargets(memory, actions);
    auto validHero = [&](const JsonNode & ref) { return ref.isNull() || (ref.isString() && heroes.count(ref.String())); };
    auto validTarget = [&](const JsonNode & ref) { return ref.isNull() || (ref.isString() && targets.count(ref.String())); };
    if(!validHero(plan["main_hero_ref"])) return false;
    std::map<std::string, JsonNode> assignments;
    std::set<std::string> assignedTargets;
    int mainCount = 0;
    if(!plan["assignments"].isVector() || plan["assignments"].Vector().size() > 16) return false;
    for(const auto & assignment : plan["assignments"].Vector())
    {
        if(!campaignFields(assignment, {"hero_ref", "role", "target_ref", "task"})
            || !assignment["hero_ref"].isString() || !validHero(assignment["hero_ref"])
            || !validTarget(assignment["target_ref"]) || !campaignText(assignment["task"])) return false;
        if(!assignment["role"].isString()) return false;
        const auto role = assignment["role"].String();
        if(role != "main" && role != "defender" && role != "scout" && role != "collector" && role != "reinforcement") return false;
        if(!assignments.emplace(assignment["hero_ref"].String(), assignment).second) return false;
        if(assignment["target_ref"].isString() && !assignedTargets.insert(assignment["target_ref"].String()).second) return false;
        if(role == "main")
        {
            ++mainCount;
            if(assignment["hero_ref"] != plan["main_hero_ref"]) return false;
        }
    }
    for(const auto & object : memory["known_objects"].Vector())
        if(object["not_seen_at_last_position"].Bool() && assignedTargets.count(object["ref"].String())) return false;
    if(mainCount != (plan["main_hero_ref"].isNull() ? 0 : 1)) return false;
    const auto & next = operational.isNull() ? memory["plan"] : operational;
    if(next["executor_ref"].isString())
    {
        const auto found = assignments.find(next["executor_ref"].String());
        if(found == assignments.end() || found->second["target_ref"] != next["target_ref"]) return false;
    }
    std::map<std::pair<std::string, int>, std::string> promisedTargets;
    for(const auto & milestone : plan["milestones"].Vector())
        if(milestone["executor_ref"].isString())
        {
            const auto executor = milestone["executor_ref"].String();
            const auto found = assignments.find(executor);
            if(found == assignments.end()) return false;
            for(const auto & [hero, assignment] : assignments)
                if(hero != executor && milestone["target_ref"].isString() && assignment["target_ref"] == milestone["target_ref"]) return false;
            if(milestone["target_ref"].isString())
            {
                if(!milestone["due_day"].isNumber()) return false;
                const auto key = std::make_pair(milestone["target_ref"].String(), static_cast<int>(milestone["due_day"].Integer()));
                const auto prior = promisedTargets.find(key);
                if(prior != promisedTargets.end() && prior->second != executor) return false;
                promisedTargets[key] = executor;
            }
        }
    if(retain) return true;
    const int day = observation["day"].Integer();
    if(!campaignText(plan["victory_method"]) || !campaignApproach(plan["approach"])
        || !campaignInteger(plan["horizon_day"], day + 3, day + 7)) return false;
    if(!plan["advantages"].isVector() || plan["advantages"].Vector().size() < 2 || plan["advantages"].Vector().size() > 3) return false;
    for(const auto & advantage : plan["advantages"].Vector())
        if(!campaignFields(advantage, {"fact_ref", "benefit", "constraint"}) || !advantage["fact_ref"].isString()
            || !evidence.count(advantage["fact_ref"].String()) || !campaignText(advantage["benefit"]) || !campaignText(advantage["constraint"])) return false;
    if(!plan["milestones"].isVector() || plan["milestones"].Vector().empty() || plan["milestones"].Vector().size() > 6) return false;
    for(const auto & milestone : plan["milestones"].Vector())
        if(!campaignFields(milestone, {"target_ref", "executor_ref", "due_day", "expected"})
            || !validTarget(milestone["target_ref"]) || !validHero(milestone["executor_ref"])
            || !campaignInteger(milestone["due_day"], day, plan["horizon_day"].Integer()) || !campaignText(milestone["expected"])) return false;
    std::set<std::string> resources;
    if(!plan["reserves"].isVector() || plan["reserves"].Vector().size() > 7) return false;
    for(const auto & reserve : plan["reserves"].Vector())
    {
        if(!campaignFields(reserve, {"resource", "amount", "purpose", "release_if"}) || !reserve["resource"].isString()
            || !campaignInteger(reserve["amount"], 0, 2147483647) || !campaignText(reserve["purpose"]) || !campaignText(reserve["release_if"])) return false;
        const auto resource = reserve["resource"].String();
        const std::set<std::string> allowedResources{"wood", "mercury", "ore", "sulfur", "crystal", "gems", "gold"};
        if(!allowedResources.count(resource) || !resources.insert(resource).second) return false;
    }
    std::set<std::string> alternatives;
    if(!plan["alternatives"].isVector() || plan["alternatives"].Vector().size() < 2 || plan["alternatives"].Vector().size() > 3) return false;
    for(const auto & alternative : plan["alternatives"].Vector())
    {
        if(!campaignFields(alternative, {"approach", "benefit", "cost", "risk", "abandon_if"}) || !campaignApproach(alternative["approach"])) return false;
        for(const auto * key : {"benefit", "cost", "risk", "abandon_if"}) if(!campaignText(alternative[key])) return false;
        if(!alternatives.insert(alternative["approach"].String()).second) return false;
    }
    return alternatives.count(plan["approach"].String());
}

inline JsonNode campaignSnapshot(const JsonNode & observation)
{
    JsonNode snapshot;
    for(const auto & hero : observation["heroes"].Vector())
    {
        const auto ref = objectReference(hero["id"]);
        snapshot["heroes"][ref] = hero["strength"]["army_ai_value"];
        if(hero["army"].isVector())
        {
            snapshot["armies"][ref].Struct();
            for(const auto & stack : hero["army"].Vector())
                snapshot["armies"][ref][stack["creature"].String()].Integer() += stack["count"].Integer();
        }
    }
    for(const auto & town : observation["towns"].Vector()) snapshot["towns"].Vector().push_back(town["id"]);
    for(const auto & object : observation["visible_objects"].Vector())
        if(object["kind"].String() == "hero" || object["kind"].String() == "town")
            if(std::find(observation["enemy_players"].Vector().begin(), observation["enemy_players"].Vector().end(), object["owner"]) != observation["enemy_players"].Vector().end())
                snapshot["threats"][objectReference(object["id"])] = object;
    return snapshot;
}

inline void reviewCampaign(JsonNode & memory, const JsonNode & observation, const JsonNode & actions)
{
    if(!memory.Struct().count("campaign")) memory["campaign"] = JsonNode();
    const JsonNode campaign = static_cast<const JsonNode &>(memory)["campaign"];
    auto & review = memory["campaign_review"];
    auto addReason = [&](const std::string & reason) {
        auto & reasons = review["reasons"].Vector();
        if(std::find(reasons.begin(), reasons.end(), JsonNode(reason)) == reasons.end()) reasons.push_back(JsonNode(reason));
    };
    const int day = observation["day"].Integer();
    if(campaign.isNull()) addReason("initial_campaign");
    else
    {
        if(day != memory["campaign_checked_day"].Integer()) addReason("daily_check");
        if(day - memory["campaign_full_review_day"].Integer() >= 3) addReason("three_day_review");
        if(day % 7 == 0 && memory["campaign_full_review_day"].Integer() < day) addReason("before_weekly_growth");
        if(day > campaign["horizon_day"].Integer()) addReason("horizon_elapsed");
        const auto planStatus = memory["plan_review"]["status"].String();
        if(memory["campaign_plan_status"].String() != planStatus && (planStatus == "completed" || planStatus == "infeasible" || planStatus == "requires_revision"))
            addReason("operational_" + planStatus);
        memory["campaign_plan_status"].String() = planStatus;
    }
    const JsonNode fresh = campaignSnapshot(observation);
    const JsonNode previous = memory["campaign_observed"];
    std::string recruitedHero;
    // Only the next observation may acknowledge a confirmed purchase. Match
    // both the delivered creatures and strength; unrelated changes still review.
    const auto & results = static_cast<const JsonNode &>(memory)["recent_results"].Vector();
    if(!results.empty())
    {
        const auto & result = results.back();
        const auto & action = result["action"];
        if(result["sequence"].Integer() > memory["campaign_observed_result_sequence"].Integer()
            && result["day"].Integer() == day && result["outcome"].String() == "completed"
            && action["kind"].String() == "recruit" && action["destination"].isNumber()
            && action["creature"].isString() && action["amount"].Integer() > 0
            && action["army_value_gain"].isNumber() && action["army_value_gain"].Float() > 0)
        {
            const auto ref = objectReference(action["destination"]);
            if(previous["armies"][ref].isStruct() && fresh["armies"][ref].isStruct()
                && previous["heroes"][ref].isNumber() && fresh["heroes"][ref].isNumber())
            {
                auto expected = previous["armies"][ref];
                expected[action["creature"].String()].Integer() += action["amount"].Integer();
                if(expected == fresh["armies"][ref]
                    && fresh["heroes"][ref].Float() == previous["heroes"][ref].Float() + action["army_value_gain"].Float())
                    recruitedHero = ref;
            }
        }
    }
    memory["campaign_observed_result_sequence"] = memory["result_sequence"];
    if(!previous.isNull())
    {
        if(observation["heroes"].isVector() && fresh["heroes"].Struct() != previous["heroes"].Struct())
        {
            for(const auto & [ref, strength] : previous["heroes"].Struct())
                if(!fresh["heroes"].Struct().count(ref)) addReason("hero_no_longer_owned");
            for(const auto & [ref, strength] : fresh["heroes"].Struct())
                if(!previous["heroes"].Struct().count(ref)) addReason("new_owned_hero");
                else if(ref != recruitedHero && strength.isNumber() && previous["heroes"][ref].isNumber()
                    && std::abs(strength.Float() - previous["heroes"][ref].Float()) >= std::max(1.0, previous["heroes"][ref].Float() * .25))
                    addReason("army_strength_changed");
        }
        if(observation["towns"].isVector() && fresh["towns"] != previous["towns"]) addReason("owned_towns_changed");
        for(const auto & [ref, threat] : fresh["threats"].Struct())
            if(previous["threats"][ref] != threat) addReason("visible_threat_changed");
    }
    // Only changed facts raise an event. Repeated observations cannot consume it.
    memory["campaign_observed"] = fresh;
    review["assignments"].Vector().clear();
    for(const auto & assignment : campaign["assignments"].Vector())
    {
        JsonNode status;
        status["hero_ref"] = assignment["hero_ref"];
        status["target_ref"] = assignment["target_ref"];
        status["status"].String() = "active";
        if(observation["heroes"].isVector() && !fresh["heroes"].Struct().count(assignment["hero_ref"].String()))
            status["status"].String() = "infeasible_executor";
        for(const auto & object : memory["known_objects"].Vector())
            if(object["ref"] == assignment["target_ref"] && object["not_seen_at_last_position"].Bool())
                status["status"].String() = "target_absent_at_last_position";
        if(status["status"].String() != "active") addReason("assignment_infeasible");
        review["assignments"].Vector().push_back(status);
    }
    // High-water marks are tied to checkable milestone identities. Rewording
    // intentions, oscillating routes and recovering lost strength are not progress.
    auto & progress = memory["campaign_progress"];
    if(!progress["last_change_day"].isNumber()) progress["last_change_day"] = observation["day"];
    bool changed = false;
    review["milestones"].Vector().clear();
    for(const auto & milestone : campaign["milestones"].Vector())
    {
        const auto key = milestone["target_ref"].toCompactString() + ":" + milestone["executor_ref"].toCompactString();
        auto & tracking = progress["milestones"][key];
        const bool initial = tracking.isNull();
        JsonNode status;
        status["target_ref"] = milestone["target_ref"];
        status["executor_ref"] = milestone["executor_ref"];
        status["due_day"] = milestone["due_day"];
        status["due"].Bool() = day >= milestone["due_day"].Integer();
        status["target_owned"].String() = "unknown";
        for(const auto & object : memory["known_objects"].Vector())
            if(object["ref"] == milestone["target_ref"] && !object["stale"].Bool() && !object["not_seen_at_last_position"].Bool())
            {
                status["target_owned"].String() = object["owner"] == observation["player"] ? "yes" : "no";
                if(object["owner"] == observation["player"] && !tracking["owned_once"].Bool())
                {
                    tracking["owned_once"].Bool() = true;
                    changed |= !initial;
                }
            }
        for(const auto & action : actions.Vector())
            if(action["target_ref"] == milestone["target_ref"] && action["hero"].isNumber()
                && objectReference(action["hero"]) == milestone["executor_ref"].String() && action["route_steps"].isNumber())
                if(!tracking["best_route_steps"].isNumber() || action["route_steps"].Integer() < tracking["best_route_steps"].Integer())
                {
                    tracking["best_route_steps"] = action["route_steps"];
                    changed |= !initial;
                }
        for(const auto & hero : observation["heroes"].Vector())
            if(objectReference(hero["id"]) == milestone["executor_ref"].String() && hero["strength"]["army_ai_value"].isNumber())
                if(!tracking["best_army"].isNumber() || hero["strength"]["army_ai_value"].Float() > tracking["best_army"].Float())
                {
                    tracking["best_army"] = hero["strength"]["army_ai_value"];
                    changed |= !initial;
                }
        for(const auto & result : memory["recent_results"].Vector())
            if(result["action"]["target_ref"] == milestone["target_ref"] && result["outcome"].String() == "completed"
                && result["sequence"].Integer() > memory["campaign_result_cursor"].Integer())
                if(std::find(tracking["confirmed_commands"].Vector().begin(), tracking["confirmed_commands"].Vector().end(), result["action"]["kind"]) == tracking["confirmed_commands"].Vector().end())
                {
                    tracking["confirmed_commands"].Vector().push_back(result["action"]["kind"]);
                    changed = true;
                }
        tracking["initialized"].Bool() = true;
        review["milestones"].Vector().push_back(status);
        if(status["due"].Bool() && memory["campaign_checked_day"].Integer() < day) addReason("milestone_due");
    }
    if(changed) progress["last_change_day"] = observation["day"];
    review["last_observed_progress_day"] = progress["last_change_day"];
    if(!campaign.isNull() && day - progress["last_change_day"].Integer() >= 2
        && memory["campaign_checked_day"].Integer() < day) addReason("campaign_no_observed_progress");
    // A previously absent route to a current milestone can alter the campaign.
    JsonNode accessible;
    for(const auto & milestone : campaign["milestones"].Vector())
        for(const auto & action : actions.Vector())
            if(action["target_ref"] == milestone["target_ref"] && milestone["target_ref"].isString()
                && action["hero"].isNumber() && objectReference(action["hero"]) == milestone["executor_ref"].String())
                accessible[milestone["target_ref"].String()].Bool() = true;
    if(memory["campaign_accessible"].isStruct())
        for(const auto & [ref, value] : accessible.Struct())
            if(!memory["campaign_accessible"][ref].Bool()) addReason("milestone_route_opened");
    memory["campaign_accessible"] = accessible;
    review["required"].Bool() = !review["reasons"].Vector().empty();
    review["full"].Bool() = std::any_of(review["reasons"].Vector().begin(), review["reasons"].Vector().end(),
        [](const JsonNode & reason) { return reason.String() != "daily_check"; });
}

inline void acceptCampaign(JsonNode & memory, const JsonNode & update, int day)
{
    if(update.isNull()) return;
    if(update["decision"].String() == "revise")
    {
        std::set<std::string> retained;
        for(const auto & milestone : update["plan"]["milestones"].Vector())
            retained.insert(milestone["target_ref"].toCompactString() + ":" + milestone["executor_ref"].toCompactString());
        auto & tracking = memory["campaign_progress"]["milestones"].Struct();
        for(auto it = tracking.begin(); it != tracking.end(); )
            if(!retained.count(it->first)) it = tracking.erase(it); else ++it;
        memory["campaign"] = update["plan"];
        memory["campaign_result_cursor"] = memory["result_sequence"];
    }
    for(const auto * key : {"decision", "reason", "evidence_refs"}) memory["campaign_assessment"][key] = update[key];
    memory["campaign_checked_day"].Integer() = day;
    if(memory["campaign_review"]["full"].Bool() || update["decision"].String() == "revise")
        memory["campaign_full_review_day"].Integer() = day;
    memory["campaign_review"]["reasons"].Vector().clear();
    memory["campaign_review"]["required"].Bool() = false;
    memory["campaign_review"]["full"].Bool() = false;
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
    std::set<std::string> campaignTargets;
    const auto & campaign = static_cast<const JsonNode &>(memory)["campaign"];
    for(const auto * key : {"assignments", "milestones"})
        for(const auto & item : campaign[key].Vector())
            if(item["target_ref"].isString()) campaignTargets.insert(item["target_ref"].String());
	std::sort(ordered.begin(), ordered.end(), [&](const JsonNode & a, const JsonNode & b) {
		const bool ap = a["ref"].String() == target || campaignTargets.count(a["ref"].String()), bp = b["ref"].String() == target || campaignTargets.count(b["ref"].String());
		if(ap != bp) return ap;
		if(a["last_seen_day"].Integer() != b["last_seen_day"].Integer())
			return a["last_seen_day"].Integer() > b["last_seen_day"].Integer();
		return a["ref"].String() < b["ref"].String();
	});
	if(ordered.size() > 128) ordered.resize(128);
	memory["known_objects"].Vector() = std::move(ordered);
	reviewPlan(memory, observation, actions);
	reviewCampaign(memory, observation, actions);
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
