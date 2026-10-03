#include "StdInc.h"
#include "ExternalAI.h"
#include "ProcessExchange.h"

#include "../../lib/callback/CCallback.h"
#include "../../lib/callback/Calendar.h"
#include "../../lib/entities/building/CBuilding.h"
#include "../../lib/entities/faction/CTown.h"
#include "../../lib/gameState/CGameState.h"
#include "../../lib/json/JsonNode.h"
#include "../../lib/mapObjects/CGTownInstance.h"
#include "../../lib/networkPacks/PacksForClient.h"
#include "../../lib/networkPacks/PacksForServer.h"
#include <cstdlib>
#ifdef _WIN32
#include <boost/locale/encoding_utf.hpp>
#endif

namespace
{
std::string environmentValue(const char * name)
{
#ifdef _WIN32
	const auto wideName = boost::locale::conv::utf_to_utf<wchar_t>(name);
	const auto * value = _wgetenv(wideName.c_str());
	return value ? boost::locale::conv::utf_to_utf<char>(value) : std::string{};
#else
	const auto * value = std::getenv(name);
	return value ? value : std::string{};
#endif
}

struct BuildChoice
{
	ObjectInstanceID town;
	BuildingID building;
};

bool lockState(std::shared_lock<std::shared_mutex> & lock, const std::atomic<bool> & stopping)
{
	while(!stopping)
	{
		if(lock.try_lock())
			return true;
		std::this_thread::sleep_for(std::chrono::milliseconds(5));
	}
	return false;
}
}

ExternalAI::~ExternalAI() { finish(); }

void ExternalAI::initGameInterface(std::shared_ptr<Environment> environment, std::shared_ptr<CCallback> callback)
{
	cb = callback;
	cbc = callback;
	env = environment;
	playerID = *cb->getPlayerID();
}

std::string ExternalAI::getBattleAIName() const { return "BattleAI"; }

void ExternalAI::finish()
{
	{
		std::lock_guard lock(requestMutex);
		stopping = true;
	}
	requestChanged.notify_all();
	if(worker.joinable())
		worker.join();
}

void ExternalAI::answer(QueryID id, int choice)
{
	if(id != QueryID(-1))
		cb->selectionMade(choice, id);
}

void ExternalAI::yourTurn(QueryID queryID)
{
	finish();
	stopping = false;
	answer(queryID, 0);
	const auto turn = ++turnNumber;
	worker = std::thread([this, turn]() { runTurn(turn); });
}

void ExternalAI::requestSent(const CPackForServer * pack, int requestID)
{
	if(dynamic_cast<const BuildStructure *>(pack))
	{
		std::lock_guard lock(requestMutex);
		pendingRequest = requestID;
		requestCompleted = false;
	}
}

void ExternalAI::requestRealized(PackageApplied * pack)
{
	std::lock_guard lock(requestMutex);
	if(static_cast<int>(pack->requestID) == pendingRequest)
	{
		requestCompleted = true;
		requestChanged.notify_all();
	}
}

void ExternalAI::runTurn(uint64_t turn)
{
	std::map<std::string, BuildChoice> builds;
	JsonNode request;
	const std::string requestID = std::to_string(playerID.getNum()) + ":" + std::to_string(turn);
	request["protocol"].Integer() = 1;
	request["request_id"].String() = requestID;
	{
		std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
		if(!lockState(gsLock, stopping) || !cb->isPlayerMakingTurn(playerID))
			return;
		request["observation"]["player"].Integer() = playerID.getNum();
		request["observation"]["day"].Integer() = cb->getCalendar().getCurrentDay();
		JsonNode end;
		end["id"].String() = "end";
		end["kind"].String() = "end_turn";
		request["actions"].Vector().push_back(end);
		for(const auto * town : cb->getTownsInfo(true))
		{
			for(const auto & [id, building] : town->getTown()->buildings)
			{
				if(building->mode != CBuilding::BUILD_NORMAL || cb->canBuildStructure(town, id) != EBuildingState::ALLOWED)
					continue;
				const auto actionID = "build-" + std::to_string(builds.size());
				builds.emplace(actionID, BuildChoice{town->id, id});
				JsonNode action;
				action["id"].String() = actionID;
				action["kind"].String() = "build";
				action["building"].String() = building->getJsonKey();
				for(int resource = 0; resource < GameConstants::RESOURCE_QUANTITY; ++resource)
					action["cost"].Vector().push_back(JsonNode(building->resources[GameResID(resource)]));
				request["actions"].Vector().push_back(action);
			}
		}
	}

	std::string actionID = "end";
	const auto executable = environmentValue("VCMI_EXTERNAL_AI_EXECUTABLE");
	const auto script = environmentValue("VCMI_EXTERNAL_AI_SCRIPT");
	if(!executable.empty() && !script.empty())
	{
		auto response = externalai::exchange(executable, {script}, request.toCompactString(), std::chrono::seconds(20), stopping);
		if(response.error.empty())
		{
			try
			{
				JsonParsingSettings parser;
				parser.strict = true;
				parser.mode = JsonParsingSettings::JsonFormatMode::JSON;
				const JsonNode reply(response.output.data(), response.output.size(), parser, "ExternalAI reply");
				if(!reply.isStruct() || reply.Struct().size() != 3 || !reply["protocol"].isNumber()
					|| reply["protocol"].Float() != 1 || !reply["request_id"].isString()
					|| reply["request_id"].String() != requestID || !reply["action_id"].isString()
					|| (reply["action_id"].String() != "end" && !builds.count(reply["action_id"].String())))
					throw std::runtime_error("invalid or stale action choice");
				actionID = reply["action_id"].String();
			}
			catch(const std::exception & error)
			{
				logAi->warn("ExternalAI rejected reply: %s request=%s", error.what(), requestID);
			}
		}
		else
			logAi->warn("ExternalAI controller failure: %s request=%s", response.error, requestID);
	}
	else
		logAi->warn("ExternalAI executable/script not configured; ending turn");
	if(stopping)
		return;
	logAi->info("ExternalAI request %s selected %s", requestID, actionID);
	if(actionID != "end")
	{
		const auto choice = builds.at(actionID);
		bool sent = false;
		{
			std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
			if(!lockState(gsLock, stopping) || !cb->isPlayerMakingTurn(playerID))
				return;
			const auto * town = cb->getTown(choice.town);
			if(town && town->tempOwner == playerID)
				sent = cb->buildBuilding(town, choice.building);
		}
		if(sent)
		{
			std::unique_lock lock(requestMutex);
			requestChanged.wait_for(lock, std::chrono::seconds(5), [&]() { return stopping || requestCompleted; });
			lock.unlock();
			std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
			if(!lockState(gsLock, stopping))
				return;
			const auto * town = cb->getTown(choice.town);
			const bool built = town && town->tempOwner == playerID && town->hasBuilt(choice.building);
			logAi->info("ExternalAI build result town=%d building=%d observed=%d request=%s action=%s dispatched=1",
				choice.town.getNum(), choice.building.getNum(), built, requestID, actionID);
		}
		else
			logAi->info("ExternalAI build result town=%d building=%d observed=0 request=%s action=%s dispatched=0",
				choice.town.getNum(), choice.building.getNum(), requestID, actionID);
	}
	std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
	if(lockState(gsLock, stopping) && cb->isPlayerMakingTurn(playerID))
		cb->endTurn();
}

void ExternalAI::heroGotLevel(const CGHeroInstance *, PrimarySkill, std::vector<SecondarySkill> &, QueryID id) { answer(id, 0); }
void ExternalAI::commanderGotLevel(const CCommanderInstance *, std::vector<ui32>, QueryID id) { answer(id, 0); }
void ExternalAI::showBlockingDialog(const std::string &, const std::vector<Component> &, QueryID id, int, bool selection, bool cancel, bool safeToAutoaccept)
{
	answer(id, cancel || !selection ? 0 : 1);
}
void ExternalAI::showTeleportDialog(const CGHeroInstance *, TeleportChannelID, TTeleportExitsList, bool, QueryID id) { answer(id, 0); }
void ExternalAI::showGarrisonDialog(const CArmedInstance *, const CGHeroInstance *, bool, QueryID id, const MetaString &) { answer(id, 0); }
void ExternalAI::showMapObjectSelectDialog(QueryID id, const Component &, const MetaString &, const MetaString &, const std::vector<ObjectInstanceID> &) { answer(id, 0); }
std::optional<BattleAction> ExternalAI::makeSurrenderRetreatDecision(const BattleID &, const BattleStateInfoForRetreat &) { return std::nullopt; }
