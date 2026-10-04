#include "Global.h"
#include "TurnBatch.h"
#include <iostream>

JsonNode json(const std::string & text)
{
	JsonParsingSettings settings;
	settings.strict = true;
	settings.mode = JsonParsingSettings::JsonFormatMode::JSON;
	return JsonNode(text.data(), text.size(), settings, "turn batch test");
}

void require(bool condition, const char * message)
{
	if(!condition) throw std::runtime_error(message);
}

int main()
{
	try
	{
		const auto actions = json(R"([
			{"id":"build-a","kind":"build","town":1,"building":"tavern","cost":[0,500]},
			{"id":"build-b","kind":"build","town":2,"building":"tavern","cost":[0,500]},
			{"id":"move-a","kind":"explore","hero":3,"target":[5,5,0],"cost":null,"route_encounters":[],"stop_threats":[],"turn_stop":{"possible_positions":[[5,5,0]]}},
			{"id":"move-b","kind":"explore","hero":4,"target":[9,9,0]},
			{"id":"end","kind":"end_turn"}])");
		const auto batch = externalai::batchChoices(json(R"({"action_id":"build-a","follow_up_action_ids":["build-b","move-a","move-b"]})"), actions);
		require(batch.size() == 4 && batch[1]["town"].Integer() == 2 && batch[3]["hero"].Integer() == 4, "town/hero batch lost order");
		for(const auto * bad : {R"({"action_id":"build-a","follow_up_action_ids":["unknown"]})",
			R"({"action_id":"build-a","follow_up_action_ids":["build-a"]})",
			R"({"action_id":"end","follow_up_action_ids":["move-a"]})",
			R"({"action_id":"build-a","follow_up_action_ids":false})"})
		{
			bool rejected = false;
			try { externalai::batchChoices(json(bad), actions); } catch(const std::exception &) { rejected = true; }
			require(rejected, "unsafe batch accepted");
		}
		auto newID = batch[1];
		newID["id"].String() = "build-7";
		require(externalai::sameCommand(batch[1], newID), "fresh ID discarded same command");
		newID["cost"] = json("[0,700]");
		require(!externalai::sameCommand(batch[1], newID), "changed cost reused");
		auto before = json(R"({"day":1,"player":0,"resources":[0,1000],"towns":[{"id":1},{"id":2}],"heroes":[{"id":3,"army":[],"level":1,"position":[4,5,0]},{"id":4,"army":[],"level":1}],"visible_objects":[{"id":3,"kind":"hero","owner":0,"position":[4,5,0]}]})");
		auto after = before;
		after["heroes"][0]["position"] = json("[5,5,0]");
		after["visible_objects"][0]["position"] = json("[5,5,0]");
		require(!externalai::batchSituationChanged(before, after, batch[2]), "expected own movement discarded independent step");
		after["visible_objects"].Vector().push_back(json(R"({"id":10,"kind":"hero","owner":1,"position":[6,5,0]})"));
		require(externalai::batchSituationChanged(before, after, batch[2]), "new enemy did not trigger replanning");
		after = before;
		after["heroes"][0]["position"] = json("[3,5,0]");
		require(externalai::batchSituationChanged(before, after, batch[2]), "unexpected stop did not replan");
		after = before;
		after["heroes"].Vector().erase(after["heroes"].Vector().begin());
		require(externalai::batchSituationChanged(before, after, batch[2]), "lost hero did not replan");
		after = before;
		after["resources"] = json("[0,1500]");
		require(externalai::batchSituationChanged(before, after, batch[2]), "pickup did not replan");
		auto battle = batch[2];
		battle["kind"].String() = "attack";
		require(externalai::batchSituationChanged(before, before, battle), "battle retained stale queue");
		std::cout << "PASS: ordered multi-town/hero actions, validation, fresh IDs, costs, movement, sightings, losses, pickups, battle replanning\n";
	}
	catch(const std::exception & error)
	{
		std::cerr << error.what() << '\n';
		return 1;
	}
}
