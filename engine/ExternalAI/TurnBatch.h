#pragma once
#include "json/JsonNode.h"
#include <algorithm>
#include <set>
#include <stdexcept>

namespace externalai
{
constexpr int TURN_ACTION_LIMIT = 256; // Runaway guard, not a model-call budget.
constexpr int BATCH_ACTION_LIMIT = 32;

// IDs belong to one observation. Store the chosen commands, then resolve them
// against freshly offered actions; never carry an ID into another observation.
inline std::vector<JsonNode> batchChoices(const JsonNode & reply, const JsonNode & actions)
{
	std::vector<JsonNode> result;
	std::vector<JsonNode> ids{reply["action_id"]};
	if(reply.Struct().count("follow_up_action_ids"))
	{
		if(!reply["follow_up_action_ids"].isVector()) throw std::runtime_error("invalid action batch");
		for(const auto & id : reply["follow_up_action_ids"].Vector()) ids.push_back(id);
	}
	if(ids.size() > BATCH_ACTION_LIMIT) throw std::runtime_error("action batch too large");
	std::set<std::string> seen;
	for(const auto & id : ids)
	{
		if(!id.isString() || !seen.insert(id.String()).second) throw std::runtime_error("invalid or duplicate batch ID");
		const JsonNode * offered = nullptr;
		for(const auto & action : actions.Vector()) if(action["id"] == id) offered = &action;
		if(!offered) throw std::runtime_error("unoffered batch action");
		if(offered->operator[]("kind").String() == "end_turn" && result.size()+1 != ids.size())
			throw std::runtime_error("end_turn must finish batch");
		result.push_back(*offered);
	}
	return result;
}

inline bool sameCommand(const JsonNode & first, const JsonNode & second)
{
	for(const auto * key : {"kind", "town", "hero", "target", "object_id", "destination", "building",
		"creature", "from_creature", "amount", "slot", "hero_type", "cost"})
		if(first[key] != second[key]) return false;
	// A changed route encounter or visible interception risk needs a new choice.
	for(const auto * key : {"route_encounters", "stop_threats"})
		if(first[key] != second[key]) return false;
	return true;
}

inline JsonNode externalSightings(const JsonNode & observation)
{
	JsonNode result;
	result.Vector();
	for(const auto & object : observation["visible_objects"].Vector())
		if(!((object["kind"].String() == "hero" || object["kind"].String() == "town")
			&& object["owner"] == observation["player"])) result.Vector().push_back(object);
	return result;
}

inline bool collectedBatchTarget(const JsonNode & before, const JsonNode & after, const JsonNode & executed)
{
    if(executed["kind"].String() != "visit" || !executed["object_id"].isNumber()) return false;
    for(const auto & object : after["visible_objects"].Vector())
        if(object["id"] == executed["object_id"]) return false;
    for(const auto & object : before["visible_objects"].Vector())
        if(object["id"] == executed["object_id"] && object["position"] == executed["target"])
        {
            const auto kind = object["kind"].String();
            if(kind != "resource" && kind != "artifact" && kind != "treasure_chest") return false;
            for(const auto & hero : after["heroes"].Vector())
                if(hero["id"] == executed["hero"] && hero["position"] == executed["target"]) return true;
        }
    return false;
}

inline bool batchSightingsChanged(const JsonNode & before, const JsonNode & after, const JsonNode & executed, bool collected)
{
    const auto prior = externalSightings(before), current = externalSightings(after);
    for(const auto & object : prior.Vector())
    {
        const auto found = std::find_if(current.Vector().begin(), current.Vector().end(),
            [&](const JsonNode & next) { return next["id"] == object["id"]; });
        if(found != current.Vector().end() && *found == object) continue;
        if(collected && object["id"] == executed["object_id"] && found == current.Vector().end()) continue;
        return true;
    }
    for(const auto & object : current.Vector())
        if(std::none_of(prior.Vector().begin(), prior.Vector().end(),
            [&](const JsonNode & old) { return old["id"] == object["id"]; }))
        {
            const auto kind = object["kind"].String();
            if((kind != "resource" && kind != "artifact" && kind != "treasure_chest" && kind != "mine")
                || !object["owner"].isNumber() || (object["owner"].Integer() >= 0 && object["owner"] != after["player"])) return true;
        }
    return false;
}

inline bool batchSituationChanged(const JsonNode & before, const JsonNode & after, const JsonNode & executed)
{
	if(after["campaign_review"]["full"].Bool() && after["campaign_review"]["required"].Bool()) return true;
    const bool collected = collectedBatchTarget(before, after, executed);
    if(before["day"] != after["day"] || batchSightingsChanged(before, after, executed, collected)) return true;
    const auto kind = executed["kind"].String();
    if(before["towns"].Vector().size() != after["towns"].Vector().size()) return true;
    if(before["heroes"].Vector().size() != after["heroes"].Vector().size())
    {
        if(kind != "hire_hero" || after["heroes"].Vector().size() != before["heroes"].Vector().size() + 1) return true;
        for(const auto & hero : before["heroes"].Vector())
        {
            const auto found = std::find(after["heroes"].Vector().begin(), after["heroes"].Vector().end(), hero);
            if(found == after["heroes"].Vector().end()) return true;
        }
        for(const auto & hero : after["heroes"].Vector())
            if(std::none_of(before["heroes"].Vector().begin(), before["heroes"].Vector().end(),
                [&](const JsonNode & prior) { return prior["id"] == hero["id"]; })
                && hero["profile"]["hero_type"] != executed["hero_type"]) return true;
        if(before["resources"].Vector().size() != executed["cost"].Vector().size()
            || before["resources"].Vector().size() != after["resources"].Vector().size()) return true;
        for(size_t i = 0; i < before["resources"].Vector().size(); ++i)
            if(!before["resources"][i].isNumber() || !after["resources"][i].isNumber() || !executed["cost"][i].isNumber()
                || after["resources"][i].Float() != before["resources"][i].Float() - executed["cost"][i].Float()) return true;
    }
	if(kind == "attack") return true;
	if(kind != "visit" && kind != "explore") return false;
	for(const auto & encounter : executed["route_encounters"].Vector()) if(encounter["battle"].Bool()) return true;
    if(before["resources"] != after["resources"])
    {
        if(!collected || before["resources"].Vector().size() != after["resources"].Vector().size()) return true;
        for(size_t i = 0; i < before["resources"].Vector().size(); ++i)
            if(!before["resources"][i].isNumber() || !after["resources"][i].isNumber()
                || after["resources"][i].Float() < before["resources"][i].Float()) return true;
    }
	const JsonNode * moved = nullptr;
	for(const auto & hero : before["heroes"].Vector())
	{
		const JsonNode * current = nullptr;
		for(const auto & next : after["heroes"].Vector()) if(next["id"] == hero["id"]) current = &next;
		if(!current || hero["army"] != (*current)["army"] || hero["level"] != (*current)["level"]
			|| hero["secondary_skills"] != (*current)["secondary_skills"]) return true;
		if(hero["id"] == executed["hero"]) moved = current;
	}
	if(!moved) return true;
	for(const auto & position : executed["turn_stop"]["possible_positions"].Vector())
		if(position == (*moved)["position"]) return false;
	return true;
}
}
