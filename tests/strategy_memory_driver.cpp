#include "Global.h"
#include "StrategyMemory.h"
#include "RouteForecast.h"
#include <iostream>
#include <stdexcept>

JsonNode json(const std::string & text)
{
	JsonParsingSettings parser;
	parser.strict = true;
	parser.mode = JsonParsingSettings::JsonFormatMode::JSON;
	return JsonNode(text.data(), text.size(), parser, "memory test");
}

void require(bool condition, const char * message)
{
	if(!condition) throw std::runtime_error(message);
}

int main()
{
	try
	{
		JsonNode experienceState, otherExperienceState;
		const auto experienceID = externalai::initializeExperience(experienceState);
		require(!experienceID.empty(), "missing player-game experience identity");
		require(externalai::initializeExperience(experienceState) == experienceID, "identity changed between decisions");
		auto restoredExperience = json(experienceState.toCompactString());
		require(externalai::initializeExperience(restoredExperience) == experienceID, "identity changed after save/load");
		require(externalai::initializeExperience(otherExperienceState) != experienceID, "new player game reused experience identity");
		for(const auto * kind : {"day_at_least", "army_strength_at_least"})
		{
			for(const auto * value : {"7.0", "7e0", "true", "-1", "2147483648"})
				require(!externalai::validCondition(json(std::string("{\"kind\":\"") + kind + "\",\"value\":" + value + "}")), "invalid threshold accepted");
			for(const auto * value : {"0", "7", "2147483647"})
				require(externalai::validCondition(json(std::string("{\"kind\":\"") + kind + "\",\"value\":" + value + "}")), "valid integer threshold rejected");
		}
		auto rememberedEnemy = json(R"({"id":7,"kind":"hero","position":[12,10,0],"last_seen_day":2})");
		require(externalai::rememberedThreatStillPossible(rememberedEnemy, json("[]")), "hidden old sighting discarded");
		require(externalai::rememberedThreatStillPossible(rememberedEnemy, json("[[13,10,0]]")), "unrelated visible tile refuted sighting");
		require(!externalai::rememberedThreatStillPossible(rememberedEnemy, json("[[12,10,0]]")), "currently visible absence kept as positional threat");
		rememberedEnemy["not_seen_at_last_position"].Bool() = true;
		require(!externalai::rememberedThreatStillPossible(rememberedEnemy, json("[]")), "previously confirmed absence forgotten");
		JsonNode firstAliases, otherAliases;
		for(const auto [first, other] : {std::pair{13, 14}, {16, 17}, {0, 0}, {14, 15}})
			require(externalai::objectAlias(firstAliases, first) == externalai::objectAlias(otherAliases, other),
				"hidden ID renumbering changed public labels");
		auto aliasesRestored = json(firstAliases.toCompactString());
		require(externalai::objectAlias(aliasesRestored, 16) == 1, "object label changed after load");
		require(externalai::objectAlias(aliasesRestored, 33) == 4, "newly observed object reused a label");
		auto legacy = json(R"({"day":7,"attempts":2,"memory":{"known_objects":[{"id":42}],"recent_results":[{"action":{"hero":3,"object_id":42}}]},"pending":{"town":50}})");
		require(externalai::initializeObjectAliases(legacy), "old memory was not identified");
		require(legacy["memory"].isNull() && legacy["pending"].isNull(), "global IDs retained in exported memory");
		require(externalai::objectAlias(legacy["object_ids"], 42) == 0, "fresh public labels did not start at zero");
		require(legacy["day"].Integer() == 7 && legacy["attempts"].Integer() == 2, "legacy load reset consumed budget");
		require(!externalai::initializeObjectAliases(legacy), "current identities were reset on reload");
		auto route = json(R"([{"position":[1,0,0],"turn":0,"interaction":false},{"position":[2,0,0],"turn":0,"interaction":false},{"position":[3,0,0],"turn":1,"interaction":false}])");
		auto forecast = externalai::routeForecast(json("[0,0,0]"), route);
		require(forecast["position"] == json("[2,0,0]") && forecast["condition"].String() == "unchanged_route", "multi-day stop wrong");
		route[2]["turn"].Integer() = 0;
		forecast = externalai::routeForecast(json("[0,0,0]"), route);
		require(forecast["position"] == json("[3,0,0]"), "one-day stop wrong");
		route[0]["interaction"].Bool() = true;
		forecast = externalai::routeForecast(json("[0,0,0]"), route);
		require(forecast["position"] == json("[1,0,0]") && forecast["condition"].String() == "interaction_outcome_unknown", "intermediate encounter ignored");
		route[0]["stops_before_tile"].Bool() = true;
		forecast = externalai::routeForecast(json("[0,0,0]"), route);
		require(forecast["position"] == json("[0,0,0]"), "blocking visit predicted entry into object tile");
		JsonNode forces;
		auto noActions = json("[]");
		externalai::observeMemory(forces, json(R"({"day":1,"heroes":[{"id":7},{"id":8}]})"), noActions, json("[]"));
		externalai::observeMemory(forces, json(R"({"day":2})"), noActions, json("[]"));
		require(forces["own_force_changes"].Vector().empty(), "missing heroes inferred as loss");
		require(forces["schema"].Integer() == 2 && forces.Struct().count("plan"), "initial memory contract missing");
		externalai::observeMemory(forces, json(R"({"day":3,"heroes":[{"id":8}]})"), noActions, json("[]"));
		require(forces["own_force_changes"].Vector().size() == 1 && forces["own_force_changes"][0]["hero"].Integer() == 7,
			"confirmed missing own hero not reported");
		externalai::observeMemory(forces, json(R"({"day":4,"heroes":[]})"), noActions, json("[]"));
		require(forces["own_force_changes"].Vector().size() == 2, "last hero loss not reported");
		auto oldIntent = json(R"({"day":7,"attempts":2,"object_ids":{},"memory":{"schema":1,"plan":{"goal":"legacy"},"known_objects":[{"id":4}],"recent_results":[{"outcome":"completed"}]}})");
		externalai::initializePlanSchema(oldIntent);
		require(oldIntent["memory"]["plan"].isNull() && oldIntent["memory"]["known_objects"].Vector().size() == 1,
			"plan migration discarded observations");
		require(oldIntent["attempts"].Integer() == 2 && oldIntent["memory"]["recent_results"].Vector().size() == 1,
			"plan migration reset execution or budget");
		JsonNode checked;
		auto checkedActions = json("[]");
		auto own = json(R"({"day":1,"player":0,"heroes":[{"id":7,"position":[1,1,0],"strength":{"army_ai_value":100}}],"visible_objects":[{"id":42,"kind":"mine","owner":255,"position":[2,1,0]}]})");
		externalai::observeMemory(checked, own, checkedActions, json("[]"));
		checked["plan"] = json(R"({"goal":"Take mine","target_ref":"object:42","executor_ref":"object:7","ready_when":{"kind":"always","value":null},"complete_when":{"kind":"target_owned","value":null},"rationale":"income","steps":["move"],"reserves":"gold","reconsider_if":["loss"],"progress":"ready","change_reason":"initial"})");
		require(externalai::validStrategy(checked["plan"], checked, checkedActions), "checkable plan rejected");
		externalai::observeMemory(checked, own, checkedActions, json("[]"));
		require(checked["plan_review"]["status"].String() == "active", "viable plan not active");
		own["day"].Integer() = 3;
		externalai::observeMemory(checked, own, checkedActions, json("[]"));
		require(checked["plan_review"]["status"].String() == "requires_revision", "stagnant plan not flagged");
		checked["plan"]["ready_when"] = json(R"({"kind":"day_at_least","value":8})");
		externalai::observeMemory(checked, own, checkedActions, json("[]"));
		own["day"].Integer() = 6;
		externalai::observeMemory(checked, own, checkedActions, json("[]"));
		require(checked["plan_review"]["status"].String() == "waiting_for_readiness", "useful growth waiting flagged as loop");
		own["visible_objects"][0]["owner"].Integer() = 0;
		externalai::observeMemory(checked, own, checkedActions, json("[]"));
		require(checked["plan_review"]["status"].String() == "completed", "observed ownership did not complete plan");
		own["heroes"].Vector().clear();
		externalai::observeMemory(checked, own, checkedActions, json("[]"));
		require(checked["plan_review"]["status"].String() == "infeasible", "lost executor did not invalidate plan");
		own["heroes"] = json(R"([{"id":7,"position":[1,1,0],"strength":{"army_ai_value":100}}])");
		checked["plan"]["executor_ref"] = JsonNode();
		checked["plan"]["ready_when"] = json(R"({"kind":"always","value":null})");
		checked["plan"]["complete_when"] = json(R"({"kind":"confirmed_action","value":"upgrade"})");
		auto upgradeResult = json(R"({"kind":"upgrade","target_ref":"object:42","destination":7})");
		externalai::recordResult(checked, 6, upgradeResult, false);
		externalai::observeMemory(checked, own, checkedActions, json("[]"));
		require(checked["plan_review"]["complete"].String() == "not_met", "unconfirmed command completed intent");
		externalai::recordResult(checked, 6, upgradeResult, true);
		externalai::observeMemory(checked, own, checkedActions, json("[]"));
		require(checked["plan_review"]["complete"].String() == "met", "confirmed command did not complete intent");
		checked["plan_result_cursor"] = checked["result_sequence"];
		externalai::observeMemory(checked, own, checkedActions, json("[]"));
		require(checked["plan_review"]["complete"].String() == "not_met", "old command completed new intent");
		checked["plan"]["ready_when"] = json(R"({"kind":"target_owned","value":null})");
		externalai::observeMemory(checked, own, checkedActions, json("[]"));
		own["visible_objects"][0]["owner"].Integer() = 1;
		externalai::observeMemory(checked, own, checkedActions, json("[]"));
		require(checked["plan_review"]["reason"].String() == "readiness_premise_changed", "refuted readiness ignored");
		auto invalidChecked = checked["plan"];
		invalidChecked["ready_when"]["kind"].Integer() = 1;
		require(!externalai::validStrategy(invalidChecked, checked, checkedActions), "non-string condition accepted");
		JsonNode memory;
		auto actions = json(R"([{"id":"visit-0","kind":"visit","object_id":42,"target":[4,5,0]}])");
		auto observation = json(R"({"day":4,"visible_objects":[{"id":42,"kind":"mine","position":[4,5,0],"owner":255}]})");
		externalai::observeMemory(memory, observation, actions, json("[[4,5,0]]"));
		require(actions[0]["target_ref"].String() == "object:42", "stable target ref missing");
		auto plan = json(R"({"executor_ref":null,"ready_when":{"kind":"always","value":null},"complete_when":{"kind":"target_owned","value":null},"goal":"Take the mine","target_ref":"object:42","rationale":"Need ore","steps":["Recruit","Visit mine"],"reserves":"Keep 5 wood","reconsider_if":["Town threatened"],"progress":"Preparing","change_reason":"Initial plan"})");
		require(externalai::validStrategy(plan, memory, actions), "valid plan rejected");
		memory["plan"] = plan;
		JsonNode saved;
		saved["_namespaces"]["ExternalAI"]["memory"] = memory;
		const auto oldSave = saved.toCompactString();
		externalai::observeMemory(memory, json(R"({"day":5,"visible_objects":[]})"), actions, json("[]"));
		require(memory["plan"] == plan, "plan lost across day");
		require(memory["known_objects"][0]["last_seen_day"].Integer() == 4, "hidden sighting refreshed");
		require(memory["known_objects"][0]["stale"].Bool(), "hidden sighting not stale");
		require(!memory["known_objects"][0]["not_seen_at_last_position"].Bool(), "hidden removal inferred");
		externalai::observeMemory(memory, json(R"({"day":6,"visible_objects":[]})"), actions, json("[[4,5,0]]"));
		require(memory["known_objects"][0]["not_seen_at_last_position"].Bool(), "visible absence not recorded");
		auto failedRecruit = json(R"({"kind":"recruit","amount":12,"creature":"archer"})");
		externalai::recordResult(memory, 6, failedRecruit, false);
		require(memory["recent_results"][0]["outcome"].String() == "unconfirmed", "failed hire became fact");
		externalai::recordResult(memory, 6, actions[0], true);
		require(memory["recent_results"][1]["outcome"].String() == "progress_observed", "movement declared capture");
		plan["goal"].String() = "Defend town";
		plan["change_reason"].String() = "Visible enemy approaching town";
		require(externalai::validStrategy(plan, memory, actions), "defensive plan rejected");
		memory["plan"] = plan;
		const auto restored = json(oldSave)["_namespaces"]["ExternalAI"]["memory"];
		require(restored["plan"]["goal"].String() == "Take the mine", "future strategy leaked into old save");
		require(restored["recent_results"].Vector().empty(), "future outcomes leaked into old save");
		JsonNode otherPlayer;
		externalai::observeMemory(otherPlayer, json(R"({"day":6,"visible_objects":[]})"), actions, json("[]"));
		require(otherPlayer["plan"].isNull(), "plan shared across players");
		plan["target_ref"].String() = "object:999";
		require(!externalai::validStrategy(plan, memory, actions), "invented target accepted");
		plan["target_ref"].String() = "object:42";
		plan["known_objects"].Vector();
		require(!externalai::validStrategy(plan, memory, actions), "model factual update accepted");
		for(int day = 7; day < 30; ++day) externalai::recordResult(memory, day, failedRecruit, false);
		require(memory["recent_results"].Vector().size() == 8, "unbounded history");
		JsonNode many;
		many["day"].Integer() = 30;
		for(int id = 100; id < 260; ++id)
		{
			JsonNode item;
			item["id"].Integer() = id;
			many["visible_objects"].Vector().push_back(item);
		}
		externalai::observeMemory(memory, many, actions, json("[]"));
		require(memory["known_objects"].Vector().size() == 128, "unbounded world memory");
		require(memory["known_objects"][0]["ref"].String() == "object:42", "active target evicted");
		auto same = memory;
		externalai::observeMemory(memory, many, actions, json("[]"));
		externalai::observeMemory(same, many, actions, json("[]"));
		require(memory == same, "same visible history produced different memory");
		JsonNode exploration;
		auto exploreActions = json(R"([{"id":"move-1","kind":"explore","target":[1,2,0]}])");
		externalai::observeMemory(exploration, json(R"({"day":1})"), exploreActions, json("[[1,2,0]]"));
		auto emptyActions = json("[]");
		externalai::observeMemory(exploration, json(R"({"day":2})"), emptyActions, json("[[1,2,0]]"));
		require(!exploration["known_objects"][0]["not_seen_at_last_position"].Bool(), "frontier treated as vanished object");
		std::cout << "PASS: persistence, stale sightings, observed absence, outcomes, load rollback, player isolation, validation, bounds\n";
	}
	catch(const std::exception & error)
	{
		std::cerr << error.what() << '\n';
		return 1;
	}
}
