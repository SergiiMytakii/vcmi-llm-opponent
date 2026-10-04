#include "Global.h"
#include "LocalState.h"
#include "networkPacks/SaveLocalState.h"
#include "serializer/CMemorySerializer.h"
#include <iostream>
#include <stdexcept>

JsonNode json(const std::string & text)
{
	JsonParsingSettings parser;
	parser.strict = true;
	parser.mode = JsonParsingSettings::JsonFormatMode::JSON;
	return JsonNode(text.data(), text.size(), parser, "local-state test");
}

void require(bool condition, const char * message)
{
	if(!condition) throw std::runtime_error(message);
}

// Pinned upstream SaveLocalState wire layout, independent of the patched header.
struct StandardLocalState : CPackForServer
{
	JsonNode data;
	template <typename Handler> void serialize(Handler & h)
	{
		h & static_cast<CPackForServer &>(*this);
		h & data;
	}
};

int main()
{
	try
	{
		StandardLocalState standard;
		standard.player = PlayerColor(1);
		standard.requestID = 17;
		standard.data = json(R"({"currentSelection":7,"spellbookLastPageBattle":2})");
		CMemorySerializer outgoing;
		standard.serialize(outgoing.oser);
		const auto expectedBytes = outgoing.extractBuffer();
		CMemorySerializer incoming(expectedBytes);
		SaveLocalState received;
		received.serialize(incoming.iser);
		require(received.player == standard.player && received.requestID == 17 && received.data == standard.data,
			"standard client state not decoded correctly");
		CMemorySerializer reply;
		received.serialize(reply.oser);
		require(reply.extractBuffer() == expectedBytes, "SaveLocalState wire differs from upstream");

		const auto originalUI = received.data;
		JsonNode settings = originalUI;
		const auto firstMemory = json(R"({"schema":1,"day":7,"attempts":2,"pending":{"id":"build-1"},"memory":{"plan":{"goal":"Reinforce"}}})");
		SaveLocalState ai;
		ai.player = PlayerColor(0);
		ai.data = externalai::localStateUpdate(firstMemory);
		CMemorySerializer aiOutgoing;
		ai.serialize(aiOutgoing.oser);
		CMemorySerializer aiIncoming(aiOutgoing.extractBuffer());
		StandardLocalState standardReader;
		standardReader.serialize(aiIncoming.iser);
		require(standardReader.data == ai.data, "AI JSON update changed the standard packet format");
		require(externalai::applyLocalState(settings, standardReader.data), "AI update rejected");
		require(settings["currentSelection"].Integer() == 7 && settings["spellbookLastPageBattle"].Integer() == 2,
			"AI update erased human UI state");
		require(settings["_namespaces"]["ExternalAI"] == firstMemory, "AI state was not stored");
		const auto otherMemory = json(R"({"memory":{"plan":{"goal":"Defend"}}})");
		JsonNode otherPlayer = json(R"({"currentSelection":12})");
		externalai::applyLocalState(otherPlayer, externalai::localStateUpdate(otherMemory));
		require(settings["_namespaces"]["ExternalAI"] == firstMemory, "players share AI memory");
		settings["_namespaces"]["OtherModule"] = json(R"({"value":9})");
		const auto newUI = json(R"({"currentSelection":8})");
		require(externalai::applyLocalState(settings, newUI), "standard UI update rejected");
		require(settings["currentSelection"].Integer() == 8 && !settings.Struct().count("spellbookLastPageBattle"),
			"UI snapshot was merged instead of replaced");
		require(settings["_namespaces"]["ExternalAI"] == firstMemory && settings["_namespaces"]["OtherModule"]["value"].Integer() == 9,
			"standard UI snapshot erased namespaced state");
		const auto saved = settings.toCompactString();
		settings = json(saved);
		require(settings["_namespaces"]["ExternalAI"] == firstMemory,
			"save/load changed AI plan, consumed budget or pending intent");
		require(externalai::applyLocalState(settings, externalai::localStateUpdate(otherMemory)), "second AI update rejected");
		require(settings["_namespaces"]["ExternalAI"] == otherMemory && settings["currentSelection"].Integer() == 8,
			"AI namespace replacement failed");
		const auto beforeMalformed = settings;
		require(!externalai::applyLocalState(settings, json(R"({"_namespaces":[]})")) && settings == beforeMalformed,
			"invalid namespace update changed persisted state");
		require(!externalai::applyLocalState(settings, json("null")) && settings == beforeMalformed,
			"invalid UI update changed persisted state");
		require(externalai::applyLocalState(settings, json("{}")) && settings["_namespaces"]["ExternalAI"] == otherMemory,
			"empty UI snapshot erased AI memory");
		std::cout << "PASS: standard client SaveLocalState decoded; exact upstream wire preserved\n";
		std::cout << "PASS: AI/UI updates, player isolation, namespace preservation, persistence and invalid updates\n";
	}
	catch(const std::exception & error)
	{
		std::cerr << error.what() << '\n';
		return 1;
	}
}
