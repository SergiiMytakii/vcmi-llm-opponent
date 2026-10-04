#include "Global.h"
#include "StrategyMemory.h"
#include "TurnBatch.h"
#include "RouteForecast.h"
#include "SkillChoice.h"
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
		require(externalai::chooseSecondarySkill({SecondarySkill::EAGLE_EYE, SecondarySkill::ARCHERY}, 1000, 800, true) == 1,
			"ranged main hero took the first offered skill instead of Archery");
		require(externalai::chooseSecondarySkill({SecondarySkill::ARCHERY, SecondarySkill::OFFENCE}, 1000, 100, true) == 1, "melee army ignored Offence");
		require(externalai::chooseSecondarySkill({SecondarySkill::ARCHERY, SecondarySkill::LOGISTICS}, 1000, 1000, false) == 1, "travel task ignored Logistics");
		require(externalai::chooseSecondarySkill({SecondarySkill::ARCHERY, SecondarySkill::LOGISTICS}, 1000, 1000, true) == 0, "ranged combat task ignored Archery");
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
		JsonNode campaignMemory;
        auto campaignActions = json("[]");
        externalai::observeMemory(campaignMemory, json(R"({"day":1,"player":0,"heroes":[{"id":7}],"towns":[{"id":8}]})"), campaignActions, json("[]"));
        require(campaignMemory.Struct().count("campaign") && campaignMemory["campaign"].isNull(), "new campaign must begin unknown");
        require(campaignMemory["campaign_review"]["required"].Bool(), "initial campaign review not requested");

        auto campaignObservation = json(R"({"day":1,"player":0,"resources":[10,0,10,0,0,0,5000],"resource_order":["wood","mercury","ore","sulfur","crystal","gems","gold"],"victory":{"kind":"conquest","supported":true},"heroes":[{"id":1},{"id":2}],"towns":[{"id":3}]})");
        auto ownedActions = json(R"([{"id":"end","kind":"end_turn"},{"id":"move","kind":"visit","hero":1,"target_ref":"object:4"}])");
        auto ownedMemory = json(R"({"schema":2,"campaign":null,"plan":null,"campaign_review":{"required":true,"reasons":["initial_campaign"]},"known_objects":[{"ref":"object:4","kind":"mine"}]})");
        auto update = json(R"({"decision":"revise","reason":"The owned town and army can fund early expansion.","evidence_refs":["town:object:3","observation:resources"],"plan":{"victory_method":"Expand income and defeat every hostile team.","approach":"expansion","main_hero_ref":"object:1","horizon_day":5,"advantages":[{"fact_ref":"town:object:3","benefit":"Fund recruitment","constraint":"Delivery requires a town visit."},{"fact_ref":"hero:object:1","benefit":"Lead expansion","constraint":"Enemy strength remains unknown."}],"milestones":[{"target_ref":"object:4","executor_ref":"object:1","due_day":4,"expected":"Capture the observed mine."}],"assignments":[{"hero_ref":"object:1","role":"main","target_ref":"object:4","task":"Take mine"},{"hero_ref":"object:2","role":"scout","target_ref":null,"task":"Find a passage"}],"reserves":[{"resource":"gold","amount":1000,"purpose":"Reinforcement","release_if":"Threat or better capture"}],"alternatives":[{"approach":"economy","benefit":"Increase daily income","cost":"Delay army purchases","risk":"Early enemy pressure","abandon_if":"A nearby enemy appears"},{"approach":"expansion","benefit":"Capture mine income","cost":"Army and movement","risk":"Unknown encounters","abandon_if":"Route becomes unsafe"}]}})");
        externalai::observeMemory(ownedMemory, campaignObservation, ownedActions, json("[]"));
        require(externalai::validCampaign(update, JsonNode(), ownedMemory, campaignObservation, ownedActions), "valid campaign rejected");
        auto sequential = update;
        sequential["plan"]["milestones"].Vector().push_back(json(R"({"target_ref":null,"executor_ref":"object:1","due_day":5,"expected":"Scout next passage"})"));
        require(externalai::validCampaign(sequential, JsonNode(), ownedMemory, campaignObservation, ownedActions), "future sequential milestone rejected");
        sequential["plan"]["milestones"][1]["due_day"].Integer() = 4;
        require(externalai::validCampaign(sequential, JsonNode(), ownedMemory, campaignObservation, ownedActions), "same deadline prevented sequential results");
        sequential["plan"]["milestones"][1]["due_day"].Integer() = 1;
        require(externalai::validCampaign(sequential, JsonNode(), ownedMemory, campaignObservation, ownedActions), "deadline prevented sequential work today");
        auto collision = update;
        auto collisionMemory = ownedMemory;
        collisionMemory["known_objects"].Vector().push_back(json(R"({"ref":"object:5","kind":"mine"})"));
        collision["plan"]["milestones"] = json(R"([{"target_ref":"object:5","executor_ref":"object:1","due_day":4,"expected":"Capture mine"},{"target_ref":"object:5","executor_ref":"object:2","due_day":4,"expected":"Capture mine"}])");
        require(!externalai::validCampaign(collision, JsonNode(), collisionMemory, campaignObservation, ownedActions), "two milestone executors promised one target");
        auto badUpdate = update;
        badUpdate["plan"]["assignments"][1]["target_ref"].String() = "object:4";
        require(!externalai::validCampaign(badUpdate, JsonNode(), ownedMemory, campaignObservation, ownedActions), "two heroes promised one target");
        externalai::acceptCampaign(ownedMemory, JsonNode(), 1);
        require(ownedMemory["campaign_review"]["required"].Bool(), "null reply consumed review");
        externalai::acceptCampaign(ownedMemory, update, 1);
        require(!ownedMemory["campaign_review"]["required"].Bool(), "accepted campaign did not acknowledge review");
        auto loadedCampaign = json(ownedMemory.toCompactString());
        externalai::observeMemory(loadedCampaign, campaignObservation, ownedActions, json("[]"));
        require(!loadedCampaign["campaign_review"]["required"].Bool(), "ordinary repeated facts rewrote campaign");
        require(loadedCampaign["campaign"] == ownedMemory["campaign"], "campaign changed on save/load");
        // A confirmed purchase is expected execution, not a new campaign event.
        auto recruitmentObservation = campaignObservation;
        recruitmentObservation["heroes"][0]["strength"]["army_ai_value"].Integer() = 728;
        recruitmentObservation["heroes"][0]["army"] = json(R"([{"creature":"core:gnoll","count":13}])");
        auto recruitmentMemory = ownedMemory;
        externalai::observeMemory(recruitmentMemory, recruitmentObservation, ownedActions, json("[]"));
        const auto recruit = json(R"({"kind":"recruit","destination":1,"creature":"core:lizardman","amount":9,"army_value_gain":1134})");
        auto reinforced = recruitmentObservation;
        reinforced["heroes"][0]["army"].Vector().push_back(json(R"({"creature":"core:lizardman","count":9})"));
        reinforced["heroes"][0]["strength"]["army_ai_value"].Integer() = 1862;
        externalai::recordResult(recruitmentMemory, 1, recruit, true);
        auto failedRecruitment = ownedMemory;
        externalai::observeMemory(failedRecruitment, recruitmentObservation, ownedActions, json("[]"));
        externalai::recordResult(failedRecruitment, 1, recruit, false);
        auto unexpectedRecruitment = recruitmentMemory;
        externalai::observeMemory(recruitmentMemory, reinforced, ownedActions, json("[]"));
        reinforced["campaign_review"] = recruitmentMemory["campaign_review"];
        require(!externalai::batchSituationChanged(recruitmentObservation, reinforced, recruit),
            "confirmed planned recruitment discarded queued continuation");
        externalai::observeMemory(failedRecruitment, reinforced, ownedActions, json("[]"));
        require(failedRecruitment["campaign_review"]["full"].Bool(), "unconfirmed purchase suppressed army review");
        auto unexpected = reinforced;
        unexpected["heroes"][0]["army"][0]["count"].Integer() = 1;
        externalai::observeMemory(unexpectedRecruitment, unexpected, ownedActions, json("[]"));
        require(unexpectedRecruitment["campaign_review"]["full"].Bool(), "unrelated army change hidden by purchase");
        auto threatened = reinforced;
        threatened["enemy_players"] = json("[1]");
        threatened["visible_objects"].Vector().push_back(json(R"({"id":9,"kind":"hero","owner":1})"));
        auto threatMemory = recruitmentMemory;
        externalai::observeMemory(threatMemory, threatened, ownedActions, json("[]"));
        require(threatMemory["campaign_review"]["full"].Bool(), "new threat did not cancel recruitment continuation");
        const auto secondRecruit = json(R"({"kind":"recruit","destination":1,"creature":"core:gnoll","amount":12,"army_value_gain":672})");
        externalai::recordResult(recruitmentMemory, 1, secondRecruit, true);
        auto twiceReinforced = reinforced;
        twiceReinforced["heroes"][0]["army"][0]["count"].Integer() = 25;
        twiceReinforced["heroes"][0]["strength"]["army_ai_value"].Integer() = 2534;
        externalai::observeMemory(recruitmentMemory, twiceReinforced, ownedActions, json("[]"));
        twiceReinforced["campaign_review"] = recruitmentMemory["campaign_review"];
        require(!externalai::batchSituationChanged(reinforced, twiceReinforced, secondRecruit),
            "second confirmed recruitment discarded queued movement");
        // Reusing the latest completed purchase cannot excuse another increase.
        auto unexplained = twiceReinforced;
        unexplained["heroes"][0]["army"][0]["count"].Integer() = 37;
        unexplained["heroes"][0]["strength"]["army_ai_value"].Integer() = 3206;
        auto reuseMemory = recruitmentMemory;
        externalai::observeMemory(reuseMemory, unexplained, ownedActions, json("[]"));
        require(reuseMemory["campaign_review"]["full"].Bool(), "old purchase excused a later unexplained gain");
        auto later = reinforced;
        later["heroes"][0]["strength"]["army_ai_value"].Integer() = 728;
        externalai::observeMemory(recruitmentMemory, later, ownedActions, json("[]"));
        require(recruitmentMemory["campaign_review"]["full"].Bool(), "later army loss did not request review");
        campaignObservation["day"].Integer() = 2;
        externalai::observeMemory(loadedCampaign, campaignObservation, ownedActions, json("[]"));
        require(loadedCampaign["campaign_review"]["required"].Bool() && !loadedCampaign["campaign_review"]["full"].Bool(), "daily check became full rewrite");
        auto keep = json(R"({"decision":"retain","reason":"Same owned forces", "evidence_refs":["hero:object:1"],"plan":null})");
        require(externalai::validCampaign(keep, JsonNode(), loadedCampaign, campaignObservation, ownedActions), "evidenced retention rejected");
        externalai::acceptCampaign(loadedCampaign, keep, 2);
        require(loadedCampaign["campaign_full_review_day"].Integer() == 1, "daily check postponed full review");
        campaignObservation["day"].Integer() = 4;
        externalai::observeMemory(loadedCampaign, campaignObservation, ownedActions, json("[]"));
        require(loadedCampaign["campaign_review"]["full"].Bool(), "three-day review missing");
        externalai::acceptCampaign(loadedCampaign, keep, 4);
        campaignObservation["day"].Integer() = 7;
        externalai::observeMemory(loadedCampaign, campaignObservation, ownedActions, json("[]"));
        require(std::find(loadedCampaign["campaign_review"]["reasons"].Vector().begin(), loadedCampaign["campaign_review"]["reasons"].Vector().end(), JsonNode("before_weekly_growth")) != loadedCampaign["campaign_review"]["reasons"].Vector().end(), "weekly growth review missing");
        campaignObservation["heroes"].Vector().erase(campaignObservation["heroes"].Vector().begin());
        externalai::observeMemory(loadedCampaign, campaignObservation, ownedActions, json("[]"));
        require(!externalai::validCampaign(keep, JsonNode(), loadedCampaign, campaignObservation, ownedActions), "retained lost main hero");

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
		JsonNode loop;
		auto loopObservation = json(R"({"day":1,"player":0,"heroes":[{"id":7,"position":[1,1,0],"strength":{"army_ai_value":100}}],"visible_objects":[{"id":42,"kind":"mine","owner":255,"position":[9,1,0]}]})");
		auto loopActions = json(R"([{"id":"move","kind":"visit","hero":7,"object_id":42,"route_steps":8}])");
		externalai::observeMemory(loop, loopObservation, loopActions, json("[]"));
		loop["plan"] = json(R"({"goal":"Take mine","target_ref":"object:42","executor_ref":"object:7","ready_when":{"kind":"always","value":null},"complete_when":{"kind":"target_owned","value":null},"rationale":"income","steps":["move"],"reserves":"gold","reconsider_if":["loss"],"progress":"ready","change_reason":"initial"})");
		externalai::observeMemory(loop, loopObservation, loopActions, json("[]"));
		for(int day = 2; day <= 4; ++day)
		{
			loopObservation["day"].Integer() = day;
			loopObservation["heroes"][0]["position"][0].Integer() = day % 2 == 0 ? 2 : 1;
			loopActions[0]["route_steps"].Integer() = day % 2 == 0 ? 7 : 8;
			externalai::observeMemory(loop, loopObservation, loopActions, json("[]"));
		}
		require(loop["plan_review"]["status"].String() == "requires_revision", "walking back and forth counted as new goal progress");
		loopObservation["day"].Integer() = 5;
		loopActions[0]["route_steps"].Integer() = 6;
		loopObservation["heroes"][0]["strength"]["army_ai_value"].Integer() = 120;
		externalai::observeMemory(loop, loopObservation, loopActions, json("[]"));
		require(loop["plan_review"]["status"].String() == "active", "shorter path and delivered reinforcement did not advance goal");
		loopObservation["day"].Integer() = 6;
		loopObservation["heroes"][0]["strength"]["army_ai_value"].Integer() = 100;
		externalai::observeMemory(loop, loopObservation, loopActions, json("[]"));
		loopObservation["day"].Integer() = 7;
		loopObservation["heroes"][0]["strength"]["army_ai_value"].Integer() = 120;
		externalai::observeMemory(loop, loopObservation, loopActions, json("[]"));
		require(loop["plan_review"]["status"].String() == "requires_revision", "restoring the same army counted as a new reinforcement");
		loopObservation["visible_objects"][0]["position"][0].Integer() = 15;
		for(int day = 8; day <= 10; ++day)
		{
			loopObservation["day"].Integer() = day;
			loopActions[0]["route_steps"].Integer() = 20-day;
			externalai::observeMemory(loop, loopObservation, loopActions, json("[]"));
		}
		require(loop["plan_review"]["status"].String() == "active", "approaching a newly observed target position compared against its old distance");
		auto defenseTown = json(R"({"id":9,"position":[5,5,0],"strength":100,"fort_level":1,"stationed_heroes":[]})");
		auto defenseMemory = json(R"({"known_objects":[{"id":7,"kind":"hero","owner":1,"position":[7,5,0],"last_seen_day":1}]})");
		auto defenseObservation = json(R"({"day":4,"visible_objects":[]})");
		auto defense = externalai::townDefense(defenseTown, defenseObservation, defenseMemory, json("[]"), json("[]"), {1});
		require(defense["threats"].Vector().size() == 1 && defense["threats"][0]["age_days"].Integer() == 3, "aged city threat lost its observation age");
		require(defense["threats"][0]["arrival_turn_offset"].isNull(), "invented an enemy arrival time");
		defense = externalai::townDefense(defenseTown, defenseObservation, defenseMemory, json("[]"), json("[[7,5,0]]"), {1});
		require(defense["threats"].Vector().empty(), "visible absence retained city threat");
		defense = externalai::townDefense(defenseTown, defenseObservation, defenseMemory, json("[]"), json("[]"), {2});
		require(defense["threats"].Vector().empty(), "allied hero counted as city threat");
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
		checked["plan"]["complete_when"] = json(R"({"kind":"confirmed_action","value":"hire_hero"})");
		require(externalai::validStrategy(checked["plan"], checked, checkedActions), "hero hire intent rejected");
		auto hireResult = json(R"({"kind":"hire_hero","target_ref":"object:42","town":42})");
		externalai::recordResult(checked, 6, hireResult, false);
		externalai::observeMemory(checked, own, checkedActions, json("[]"));
		require(checked["plan_review"]["complete"].String() == "not_met", "unconfirmed hero hire completed intent");
		externalai::recordResult(checked, 6, hireResult, true);
		externalai::observeMemory(checked, own, checkedActions, json("[]"));
		require(checked["plan_review"]["complete"].String() == "met", "confirmed hero hire did not complete intent");
		checked["plan_result_cursor"] = checked["result_sequence"];
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
