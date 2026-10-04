#include "StdInc.h"
#include "ExternalAI.h"
#include "ProcessExchange.h"
#include "VisiblePathfinder.h"
#include "StrategyMemory.h"
#include "LocalState.h"
#include "RouteForecast.h"
#include "SkillChoice.h"
#include "TurnBatch.h"
#include "TransportJSON.h"

#include "../../lib/callback/CCallback.h"
#include "../../lib/callback/Calendar.h"
#include "../../lib/entities/building/CBuilding.h"
#include "../../lib/entities/faction/CTown.h"
#include "../../lib/entities/faction/CFaction.h"
#include "../../lib/entities/artifact/CArtifact.h"
#include "../../lib/entities/artifact/CArtifactInstance.h"
#include "../../lib/modding/CModHandler.h"
#include "../../lib/modding/ModDescription.h"
#include "../../lib/modding/CModVersion.h"
#include "../../lib/mapping/CMapHeader.h"
#include "../../lib/spells/CSpellHandler.h"
#include "../../lib/entities/hero/CHero.h"
#include "../../lib/IGameSettings.h"
#include "../../lib/gameState/CGameState.h"
#include "../../lib/json/JsonNode.h"
#include "../../lib/mapObjects/CGTownInstance.h"
#include "../../lib/mapObjects/CGHeroInstance.h"
#include "../../lib/mapObjects/CGResource.h"
#include "../../lib/mapObjects/MiscObjects.h"
#include "../../lib/mapObjects/army/CStackInstance.h"
#include "../../lib/CCreatureHandler.h"
#include "../../lib/constants/StringConstants.h"
#include "../../lib/gameState/InfoAboutArmy.h"
#include "../../lib/gameState/UpgradeInfo.h"
#include "../../lib/gameState/EVictoryLossCheckResult.h"
#include "../../lib/mapping/TerrainTile.h"
#include "../../lib/pathfinder/CGPathNode.h"
#include "../../lib/networkPacks/PacksForClient.h"
#include "../../lib/networkPacks/PacksForServer.h"
#include "../../lib/networkPacks/SaveLocalState.h"
#include "../../lib/CPlayerState.h"
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

struct RecruitChoice
{
	ObjectInstanceID town;
	ObjectInstanceID destination;
	CreatureID creature;
	int amount;
	int level;
};

struct HeroHireChoice
{
	ObjectInstanceID town;
	HeroTypeID hero;
};

ResourceSet heroHireCost()
{
	ResourceSet cost;
	cost[GameResID::GOLD] = GameConstants::HERO_GOLD_COST;
	return cost;
}

bool canHireHero(const CCallback & callback, PlayerColor player, const CGTownInstance * town)
{
	return town && town->tempOwner == player && town->hasBuilt(BuildingID::TAVERN)
		&& !town->getVisitingHero() && callback.getResourceAmount().canAfford(heroHireCost())
		&& callback.getHeroCount(player, false) < callback.getSettings().getInteger(EGameSettings::HEROES_PER_PLAYER_ON_MAP_CAP)
		&& callback.getHeroCount(player, true) < callback.getSettings().getInteger(EGameSettings::HEROES_PER_PLAYER_TOTAL_CAP);
}

struct UpgradeChoice
{
	ObjectInstanceID destination;
	SlotID slot;
	CreatureID original;
	CreatureID upgraded;
	int amount;
	ResourceSet cost;
};

struct MoveChoice
{
	ObjectInstanceID hero;
	int3 destination;
};

struct TransferChoice
{
	ObjectInstanceID town;
	ObjectInstanceID hero;
	SlotID slot;
	CreatureID creature;
	int amount;
};

JsonNode positionJSON(int3 position)
{
	JsonNode result;
	result.Vector() = {JsonNode(position.x), JsonNode(position.y), JsonNode(position.z)};
	return result;
}

JsonNode visibleArmyJSON(const ArmyDescriptor & army)
{
	JsonNode result;
	result["detailed"].Bool() = army.isDetailed;
	result["stacks"].Vector();
	double lower = 0, upper = 0, estimate = 0;
	bool bounded = true, known = true;
	// Standard quantity categories used by VCMI; never recover hidden counts.
	static const int minimum[] = {0, 1, 5, 10, 20, 50, 100, 250, 500, 1000};
	static const int maximum[] = {0, 4, 9, 19, 49, 99, 249, 499, 999, 0};
	for(const auto & [slot, stack] : army)
	{
		JsonNode item;
		item["creature"].String() = stack.getCreature()->getJsonKey();
		item[army.isDetailed ? "count" : "quantity_category"].Integer() = stack.getCount();
		const auto value = stack.getCreature()->getAIValue();
		item["unit_ai_value"].Integer() = value;
		if(army.isDetailed)
		{
			lower += static_cast<double>(value) * stack.getCount();
			upper += static_cast<double>(value) * stack.getCount();
			estimate += static_cast<double>(value) * stack.getCount();
		}
		else if(stack.getCount() > 0 && stack.getCount() <= 9)
		{
			lower += static_cast<double>(value) * minimum[stack.getCount()];
			upper += static_cast<double>(value) * maximum[stack.getCount()];
			estimate += static_cast<double>(value) * CCreature::estimateCreatureCount(stack.getCount());
			bounded &= stack.getCount() != 9;
		}
		else { known = false; bounded = false; }

		result["stacks"].Vector().push_back(item);
	}
	result["strength"]["basis"].String() = "vcmi_creature_ai_value_without_hero_or_siege";
	result["strength"]["uncertainty"].String() = army.isDetailed ? "exact_creature_counts" : "quantity_categories";
	if(known)
	{
		result["strength"]["estimate"].Float() = estimate;
		result["strength"]["minimum"].Float() = lower;
		if(bounded) result["strength"]["maximum"].Float() = upper;
		else result["strength"]["maximum"] = JsonNode();
	}
	else result["strength"]["uncertainty"].String() = "unknown_count";
	return result;
}

JsonNode resourcesJSON(const ResourceSet & resources)
{
	JsonNode result;
	for(int index = 0; index < GameConstants::RESOURCE_QUANTITY; ++index)
		result.Vector().push_back(JsonNode(resources[GameResID(index)]));
	return result;
}

void appendResourceInfo(JsonNode & item, const CGObjectInstance * object)
{
	if(const auto * resource = dynamic_cast<const CGResource *>(object))
	{
		item["resource_type"].String() = GameResID::encode(resource->resourceID().getNum());
		// Hover text reveals the type, not the pile's hidden map amount.
		item["resource_amount"] = JsonNode();
		item["resource_amount_visibility"].String() = "revealed_on_collection";
	}
	else if(const auto * mine = dynamic_cast<const CGMine *>(object))
	{
		if(mine->isAbandoned() && mine->tempOwner == PlayerColor::NEUTRAL)
		{
			item["resource_type"] = JsonNode();
			item["production_per_day"] = JsonNode();
			item["resource_visibility"].String() = "hidden_until_captured";
		}
		else
		{
			item["resource_type"].String() = GameResID::encode(mine->producedResource.getNum());
			item["production_per_day"].Integer() = mine->defaultResProduction();
			item["production_basis"].String() = "base_before_bonuses_and_handicap";
		}
	}
}

JsonNode armyJSON(const CArmedInstance * army)
{
	JsonNode result;
	result.Vector();
	for(const auto & [slot, stack] : army->Slots())
	{
		JsonNode item;
		item["creature"].String() = stack->getCreature()->getJsonKey();
		item["count"].Integer() = stack->getCount();
		const auto * creature = stack->getCreature();
		item["unit_ai_value"].Integer() = creature->getAIValue();
		item["hit_points"].Integer() = creature->getBaseHitPoints();
		item["speed"].Integer() = creature->getBaseSpeed();
		item["ranged"].Bool() = creature->getBaseShots() > 0;
		result.Vector().push_back(item);
	}
	return result;
}

// Descriptions are public rules, not executable instructions. Oversized mod
// prose is explicitly unknown rather than risking an invalid UTF-8 truncation.
std::string strategicDescription(const std::string & text)
{
    return text.size() <= 320 ? text : "unknown_description_exceeds_budget";
}

std::string buildingAvailability(EBuildingState state)
{
    switch(state)
    {
        case EBuildingState::ALLOWED: return "allowed_now";
        case EBuildingState::ALREADY_PRESENT: return "built";
        case EBuildingState::FORBIDDEN: return "forbidden";
        case EBuildingState::NO_RESOURCES: return "insufficient_resources";
        case EBuildingState::CANT_BUILD_TODAY: return "daily_limit";
        case EBuildingState::PREREQUIRES: return "missing_prerequisites";
        case EBuildingState::MISSING_BASE: return "missing_base";
        case EBuildingState::HAVE_CAPITAL: return "another_capitol_exists";
        case EBuildingState::NO_WATER: return "no_water";
        case EBuildingState::ADD_MAGES_GUILD: return "mage_guild_required";
        default: return "unknown";
    }
}

JsonNode factionRules(const CTown * town)
{
    JsonNode rules;
    rules["primary_resource"].String() = GameConstants::RESOURCE_NAMES[town->primaryRes.getNum()];
    for(const auto & tier : town->creatures)
    {
        JsonNode line;
        for(const auto & id : tier)
        {
            const auto * creature = id.toCreature();
            JsonNode unit;
            unit["creature"].String() = creature->getJsonKey();
            unit["recruit_cost"] = resourcesJSON(creature->getFullRecruitCost());
            unit["base_growth"].Integer() = creature->getGrowth();
            unit["unit_ai_value"].Integer() = creature->getAIValue();
            unit["hit_points"].Integer() = creature->getBaseHitPoints();
            unit["speed"].Integer() = creature->getBaseSpeed();
            unit["ranged"].Bool() = creature->getBaseShots() > 0;
            unit["flying"].Bool() = creature->hasBonusOfType(BonusType::FLYING);
            unit["other_effects"].String() = "unknown_not_interpreted";
            line.Vector().push_back(unit);
        }
        rules["creature_lineup"].Vector().push_back(line);
    }
    for(const auto & [id, building] : town->buildings)
        if(building->mode == CBuilding::BUILD_NORMAL)
        {
            JsonNode entry;
            entry["building"].String() = building->getJsonKey();
            entry["cost"] = resourcesJSON(building->resources);
            entry["production"] = resourcesJSON(building->produce);
            entry["description"].String() = strategicDescription(building->getDescriptionTranslated());
            entry["requirements"] = building->requirements.toJson([&](const BuildingID & required) {
                const auto found = town->buildings.find(required);
                return JsonNode(found == town->buildings.end() ? "unknown_building" : found->second->getJsonKey());
            });
            if(building->upgrade != BuildingID::NONE)
            {
                const auto found = town->buildings.find(building->upgrade);
                entry["upgrade_of"].String() = found == town->buildings.end() ? "unknown_building" : found->second->getJsonKey();
            }
            rules["buildings"].Vector().push_back(entry);
        }
    rules["future_commands"].String() = "conditional_not_offered";
    return rules;
}

int creatureCount(const CArmedInstance * army, CreatureID creature)
{
	int count = 0;
	for(const auto & [slot, stack] : army->Slots())
		if(stack->getId() == creature)
			count += stack->getCount();
	return count;
}

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
	if(const auto * player = cb->getPlayerState(playerID); player && player->playerLocalSettings)
		savedState = (*player->playerLocalSettings)["_namespaces"]["ExternalAI"];
	if(externalai::initializeObjectAliases(savedState))
		logAi->warn("ExternalAI discarded pre-alias developer memory; game state and attempt budget are retained");
	externalai::initializePlanSchema(savedState);
	experienceID = externalai::initializeExperience(savedState);
}

void ExternalAI::gameOver(PlayerColor player, const EVictoryLossCheckResult & result)
{
	if(player != playerID || (!result.victory() && !result.loss()) || finalReviewStarted.exchange(true)) return;
	const auto executable = environmentValue("VCMI_EXTERNAL_AI_EXECUTABLE");
	const auto script = environmentValue("VCMI_EXTERNAL_AI_SCRIPT");
	if(executable.empty() || script.empty()) return;
	// Only the recipient's own terminal result and public calendar are disclosed.
	// No savedState access: the turn worker can still be unwinding a battle.
	JsonNode request;
	const auto day = cb->getCalendar().getCurrentDay();
	request["protocol"].Integer() = 1;
	request["request_id"].String() = std::to_string(playerID.getNum()) + ":" + std::to_string(day) + ":final";
	request["observation"]["player"].Integer() = playerID.getNum();
	request["observation"]["day"].Integer() = day;
	request["observation"]["terminal_result"].String() = result.victory() ? "win" : "loss";
	request["memory"]["experience_id"].String() = experienceID;
	JsonNode end;
	end["id"].String() = "end";
	end["kind"].String() = "end_turn";
	request["actions"].Vector().push_back(end);
	// A bounded final reflection runs before this callback returns. Its reply
	// never executes a game command or changes a saved operational plan.
	auto response = externalai::exchange(executable, {script}, externalai::transportJSON(request.toCompactString()), std::chrono::seconds(70), stopping);
	logAi->info("ExternalAI final experience review player=%d outcome=%s delivered=%d", playerID.getNum(),
		result.victory() ? "win" : "loss", response.error.empty());
}

int ExternalAI::objectAlias(ObjectInstanceID id)
{
	return externalai::objectAlias(savedState["object_ids"], id.getNum());
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
	{
		{
			std::lock_guard lock(requestMutex);
			pendingQueries.insert(id);
		}
		cb->selectionMade(choice, id);
	}
}

void ExternalAI::queryResolved(QueryID id)
{
	std::lock_guard lock(requestMutex);
	pendingQueries.erase(id);
	requestChanged.notify_all();
}

void ExternalAI::playerBlocked(int reason, bool start)
{
	if(reason == 0)
	{
		std::lock_guard lock(requestMutex);
		battleBlocked = start;
		requestChanged.notify_all();
	}
}

void ExternalAI::battleEnded()
{
	// UPCOMING_BATTLE has no matching PlayerBlocked END packet. The engine
	// delivers this callback only after applying results and removing battle queries.
	std::lock_guard lock(requestMutex);
	battleBlocked = false;
	requestChanged.notify_all();
}

void ExternalAI::yourTurn(QueryID queryID)
{
	finish();
	stopping = false;
	answer(queryID, 0);
	const auto turn = ++turnNumber;
	worker = std::thread([this, turn]() {
		try { runTurn(turn); }
		catch(const std::exception & error) { logAi->error("ExternalAI turn stopped: %s", error.what()); }
	});
}

void ExternalAI::requestSent(const CPackForServer * pack, int requestID)
{
	if(const auto * reply = dynamic_cast<const QueryReply *>(pack))
	{
		std::lock_guard lock(requestMutex);
		queryRequests.emplace(requestID, reply->qid);
	}
	if(dynamic_cast<const BuildStructure *>(pack) || dynamic_cast<const RecruitCreatures *>(pack) || dynamic_cast<const HireHero *>(pack)
		|| dynamic_cast<const UpgradeCreature *>(pack) || dynamic_cast<const ArrangeStacks *>(pack) || dynamic_cast<const MoveHero *>(pack)
		|| dynamic_cast<const SaveLocalState *>(pack))
	{
		std::lock_guard lock(requestMutex);
		pendingRequest = requestID;
		requestCompleted = false;
		requestSucceeded = false;
	}
}

void ExternalAI::requestRealized(PackageApplied * pack)
{
	std::lock_guard lock(requestMutex);
	const auto query = queryRequests.find(pack->requestID);
	if(query != queryRequests.end())
	{
		if(pack->result)
			pendingQueries.erase(query->second);
		else
			logAi->error("ExternalAI query reply rejected id=%d", query->second.getNum());
		queryRequests.erase(query);
		requestChanged.notify_all();
	}
	if(static_cast<int>(pack->requestID) == pendingRequest)
	{
		requestCompleted = true;
		requestSucceeded = pack->result;
		requestChanged.notify_all();
	}
}

void ExternalAI::runTurn(uint64_t turn)
{
	int day;
	{
		std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
		if(!lockState(gsLock, stopping)) return;
		day = cb->getCalendar().getCurrentDay();
	}
	if(savedState["day"].Integer() != day)
	{
		savedState["day"].Integer() = day;
		savedState["attempts"].Integer() = 0;
		savedState["timeout_retries"].Integer() = 0;
	}
	// The server owns this state and serializes it into ordinary saves. Loading
	// rebuilds every candidate; a pending intent is evidence, never a command to replay.
	queuedActions.clear(); // A batch is never restored or replayed from a save.
	for(int attempt = std::clamp<int>(savedState["attempts"].Integer(), 0, externalai::TURN_ACTION_LIMIT);
		attempt < externalai::TURN_ACTION_LIMIT && !stopping; ++attempt)
	{
		savedState["attempts"].Integer() = attempt + 1;
		if(!persistState()) break;
		const bool confirmed = runDecision(day, attempt);
		if(decisionTimedOut && !stopping && savedState["timeout_retries"].Integer() < 1
			&& attempt + 1 < externalai::TURN_ACTION_LIMIT)
		{
			// Retry only an unanswered request, never a dispatched game action.
			// Save the per-day retry budget before rebuilding fresh candidates.
			++savedState["timeout_retries"].Integer();
			if(!persistState()) break;
			logAi->warn("ExternalAI timed-out decision will retry once day=%d attempt=%d", day, attempt);
			continue;
		}
		externalai::recordResult(savedState["memory"], day, selectedAction, confirmed);
		if(confirmed) savedState.Struct().erase("pending");
		if(!persistState()) break;
		if(!confirmed) break;
	}
	std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
	if(lockState(gsLock, stopping) && cb->isPlayerMakingTurn(playerID))
		cb->endTurn();
}

bool ExternalAI::persistState()
{
	{
		std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
		if(!lockState(gsLock, stopping) || !cb->isPlayerMakingTurn(playerID)) return false;
		const JsonNode memory = savedState["memory"];
		const auto & plan = memory["plan"];
		std::string targetKind;
		for(const auto & target : memory["known_objects"].Vector())
			if(target["ref"] == plan["target_ref"]) targetKind = target["kind"].String();
		const CGHeroInstance * mainHero = nullptr;
		for(const auto * hero : cb->getHeroesInfo())
			if(hero->tempOwner == playerID && (!mainHero || hero->getArmyStrength() > mainHero->getArmyStrength())) mainHero = hero;
		std::map<ObjectInstanceID, bool> goals;
		for(const auto * hero : cb->getHeroesInfo())
			if(hero->tempOwner == playerID)
			{
				const bool executor = plan["executor_ref"].isString() && externalai::objectReference(JsonNode(objectAlias(hero->id))) == plan["executor_ref"].String();
				const auto ref = externalai::objectReference(JsonNode(objectAlias(hero->id)));
                const JsonNode * assignment = nullptr;
                for(const auto & task : memory["campaign"]["assignments"].Vector())
                    if(task["hero_ref"].String() == ref) assignment = &task;
                goals[hero->id] = assignment ? ((*assignment)["role"].String() == "main" || (*assignment)["role"].String() == "defender") : executor ? targetKind != "frontier" && targetKind != "mine" && targetKind != "resource" && targetKind != "artifact" && targetKind != "treasure_chest" : hero == mainHero;
			}
		{
			std::lock_guard lock(requestMutex);
			developmentCombatGoals = std::move(goals);
			// observeMemory owns fresh-memory initialization. Keep notices buffered
			// until it has established the schema, including before the first decision.
			if(!memory.isNull())
			{
				for(auto & notice : resourceNotifications)
				{
					notice["observed_day"].Integer() = cb->getCalendar().getCurrentDay();
					savedState["memory"]["resource_notifications"].Vector().push_back(std::move(notice));
				}
				resourceNotifications.clear();
				auto & notices = savedState["memory"]["resource_notifications"].Vector();
				if(notices.size() > 16) notices.erase(notices.begin(), notices.end() - 16);
			}
		}
		savedState["schema"].Integer() = 1;
		cb->saveLocalState(externalai::localStateUpdate(savedState));
	}
	return waitForRequest();
}

bool ExternalAI::waitForRequest(int seconds)
{
	std::unique_lock lock(requestMutex);
	auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(seconds);
	while(!stopping)
	{
		if(battleBlocked)
		{
			// A human battle/result dialog can take arbitrarily long. It is not
			// a model or transport timeout; shutdown still cancels this wait.
			requestChanged.wait(lock, [&]() { return stopping || !battleBlocked; });
			deadline = std::chrono::steady_clock::now() + std::chrono::seconds(seconds);
		}
		else if(requestCompleted && pendingQueries.empty())
			return requestSucceeded;
		else if(requestChanged.wait_until(lock, deadline) == std::cv_status::timeout
			&& !battleBlocked && !(requestCompleted && pendingQueries.empty()))
			return false;
	}
	return false;
}

bool ExternalAI::runDecision(uint64_t turn, int attempt)
{
	selectedAction = JsonNode();
	decisionTimedOut = false;
	std::map<std::string, BuildChoice> builds;
	std::map<std::string, RecruitChoice> recruits;
	std::map<std::string, HeroHireChoice> hires;
	std::map<std::string, UpgradeChoice> upgrades;
	std::map<std::string, MoveChoice> moves;
	std::map<std::string, TransferChoice> transfers;
	JsonNode request;
	const std::string requestID = std::to_string(playerID.getNum()) + ":" + std::to_string(turn) + ":" + std::to_string(attempt);
	request["protocol"].Integer() = 1;
	request["request_id"].String() = requestID;
	{
		std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
		if(!lockState(gsLock, stopping) || !cb->isPlayerMakingTurn(playerID))
			return false;
		request["observation"]["player"].Integer() = playerID.getNum();
		request["observation"]["day"].Integer() = cb->getCalendar().getCurrentDay();
		request["observation"]["resources"] = resourcesJSON(cb->getResourceAmount());
        request["observation"]["rules"]["engine_version"].String() = GameConstants::VCMI_VERSION;
        request["observation"]["rules"]["engine_revision"].String() = GameConstants::GIT_SHA1;
        for(const auto & mod : LIBRARY->modh->getActiveMods())
        {
            JsonNode ruleMod;
            ruleMod["id"].String() = mod;
            ruleMod["version"].String() = LIBRARY->modh->getModInfo(mod).getVersion().toString();
            request["observation"]["rules"]["mods"].Vector().push_back(ruleMod);
        }
        // Classify only supported generic predicates. Never serialize an event's
        // object IDs, instance names, positions or hidden values. Icons alone
        // cannot distinguish conquest from a custom map using the same icon.
        const auto * header = cb->getMapHeader();
        std::set<std::string> victoryKinds;
        if(header)
            for(const auto & event : header->triggeredEvents)
                if(event.effect.type == EventEffect::VICTORY)
                {
                    const JsonNode predicate = event.trigger.toJson([](const EventCondition & condition) {
                        if(condition.condition == EventCondition::STANDARD_WIN) return JsonNode("conquest");
                        if((condition.condition == EventCondition::CONTROL || condition.condition == EventCondition::CONTROL_CURRENT)
                            && condition.objectType.as<MapObjectID>() == MapObjectID(Obj::TOWN)
                            && !condition.objectID.hasValue() && condition.objectInstanceName.empty()
                            && condition.position == int3(-1, -1, -1)) return JsonNode("control_all_towns");
                        return JsonNode("unsupported_special");
                    });
                    victoryKinds.insert(predicate.isString() ? predicate.String() : "unsupported_special");
                }
        const bool supported = victoryKinds.size() == 1 && !victoryKinds.count("unsupported_special");
        const auto victoryKind = supported ? *victoryKinds.begin() : "unsupported_special";
        request["observation"]["victory"]["kind"].String() = victoryKind;
        request["observation"]["victory"]["supported"].Bool() = supported;
        request["observation"]["victory"]["description"].String() = victoryKind == "conquest"
            ? "Defeat all hostile teams; one captured town need not end the game."
            : victoryKind == "control_all_towns" ? "Control all towns as required by this scenario. One captured town alone does not prove victory."
            : "Special public victory condition is not implemented by this adapter.";
        request["observation"]["enemy_players"].Vector();
        for(int color = 0; color < PlayerColor::PLAYER_LIMIT.getNum(); ++color)
            if(cb->getPlayerRelations(playerID, PlayerColor(color)) == PlayerRelations::ENEMIES)
                request["observation"]["enemy_players"].Vector().push_back(JsonNode(color));
		request["observation"]["hero_limits"]["on_map_count"].Integer() = cb->getHeroCount(playerID, false);
		request["observation"]["hero_limits"]["total_count"].Integer() = cb->getHeroCount(playerID, true);
		request["observation"]["hero_limits"]["on_map_cap"].Integer() = cb->getSettings().getInteger(EGameSettings::HEROES_PER_PLAYER_ON_MAP_CAP);
		request["observation"]["hero_limits"]["total_cap"].Integer() = cb->getSettings().getInteger(EGameSettings::HEROES_PER_PLAYER_TOTAL_CAP);
		for(const auto * name : GameConstants::RESOURCE_NAMES)
			request["observation"]["resource_order"].Vector().push_back(JsonNode(std::string(name)));
		for(const auto * capability : {"build", "recruit", "hire_hero", "transfer", "upgrade", "visit", "attack", "explore", "end_turn"})
			request["observation"]["capabilities"].Vector().push_back(JsonNode(std::string(capability)));
		request["observation"]["turn_actions_remaining"].Integer() = externalai::TURN_ACTION_LIMIT - attempt;
		request["observation"]["batch_action_limit"].Integer() = std::min(externalai::BATCH_ACTION_LIMIT, externalai::TURN_ACTION_LIMIT - attempt);
		if(!savedState["pending"].isNull()) request["observation"]["previous_unconfirmed_action"] = savedState["pending"];
		// Only player-visible objects enter factual memory, independent of whether
		// the hero can currently reach them. Hidden removals never update sightings.
		JsonNode visiblePositions;
		std::set<ObjectInstanceID> observedObjects;
		const auto mapSize = cb->getMapSize();
		for(int z = 0; z < mapSize.z; ++z)
		for(int y = 0; y < mapSize.y; ++y)
		for(int x = 0; x < mapSize.x; ++x)
		{
			const int3 pos(x, y, z);
			if(!cb->isVisible(pos)) continue;
			visiblePositions.Vector().push_back(positionJSON(pos));
			for(const auto * object : cb->getVisitableObjs(pos, false))
			{
				if(!cb->isVisible(object->visitablePos()) || !observedObjects.insert(object->id).second) continue;
				const auto type = object->ID;
				std::string kind;
				if(type == Obj::TOWN) kind = "town";
				else if(type == Obj::HERO) kind = "hero";
				else if(type == Obj::MONSTER) kind = "monster";
				else if(type == Obj::MINE) kind = "mine";
				else if(type == Obj::RESOURCE) kind = "resource";
				else if(type == Obj::ARTIFACT) kind = "artifact";
				else if(type == Obj::TREASURE_CHEST) kind = "treasure_chest";
				else continue;
				JsonNode item;
				item["id"].Integer() = objectAlias(object->id);
				item["kind"].String() = kind;
				item["position"] = positionJSON(object->visitablePos());
				item["owner"].Integer() = object->tempOwner.getNum();
				appendResourceInfo(item, object);
				if(type == Obj::HERO)
				{
					InfoAboutHero info;
					if(cb->getHeroInfo(object, info)) item["army"] = visibleArmyJSON(info.army);
				}
				else if(type == Obj::TOWN)
				{
					InfoAboutTown info;
					if(cb->getTownInfo(object, info)) { item["army"] = visibleArmyJSON(info.army); item["fort_level"].Integer() = info.fortLevel; }
				}
				else if(const auto * armed = dynamic_cast<const CArmedInstance *>(object))
					item["army"] = visibleArmyJSON(InfoAboutArmy(armed, false).army);
				request["observation"]["visible_objects"].Vector().push_back(item);
			}
		}
		request["observation"]["heroes"].Vector();
		for(const auto * hero : cb->getHeroesInfo())
		{
			if(hero->tempOwner != playerID)
				continue;
			JsonNode item;
			item["id"].Integer() = objectAlias(hero->id);
			item["movement"].Integer() = hero->movementPointsRemaining();
			item["position"] = positionJSON(hero->visitablePos());
			item["army"] = armyJSON(hero);
			item["strength"]["army_ai_value"].Float() = hero->getArmyStrength();
			item["strength"]["hero_fighting_multiplier"].Float() = hero->getFightingStrength();
			item["strength"]["basis"].String() = "approximate_not_battle_prediction";
			for(int skill = 0; skill < 4; ++skill)
				item["primary_skills"].Vector().push_back(JsonNode(hero->getPrimSkillLevel(PrimarySkill(skill))));
			item["mana"].Integer() = hero->mana;
			item["level"].Integer() = hero->level;
            item["profile"]["hero_type"].String() = hero->getHeroType()->getJsonKey();
            item["profile"]["specialty"]["name"].String() = hero->getHeroType()->getSpecialtyNameTranslated();
            item["profile"]["specialty"]["description"].String() = strategicDescription(hero->getHeroType()->getSpecialtyDescriptionTranslated());
            item["profile"]["specialty"]["effects"].String() = "description_only_unmodeled_effects_unknown";
            item["profile"]["known_spells"].Vector();
            for(const auto spell : hero->getSpellsInSpellbook())
            {
                JsonNode magic;
                magic["spell"].String() = spell.toSpell()->getJsonKey();
                magic["castable_with_current_equipment"].Bool() = hero->canCastThisSpell(spell.toSpell());
                magic["mana_cost"].Integer() = hero->getSpellCost(spell.toSpell());
                magic["execution"].String() = "BattleAI_only_no_adventure_command";
                item["profile"]["known_spells"].Vector().push_back(magic);
            }
            item["profile"]["equipped_artifacts"].Vector();
            for(const auto & [slot, info] : hero->artifactsWorn)
                if(const auto * artifact = info.getArt(); artifact && !info.locked)
                {
                    JsonNode equipment;
                    equipment["artifact"].String() = artifact->getType()->getJsonKey();
                    equipment["description"].String() = strategicDescription(artifact->getType()->getDescriptionTranslated());
                    equipment["effects"].String() = "description_only_unmodeled_effects_unknown";
                    item["profile"]["equipped_artifacts"].Vector().push_back(equipment);
                }
			item["secondary_skills"].Vector();
			for(const auto & [skill, level] : hero->secSkills)
				if(skill != SecondarySkill::NONE)
				{
					JsonNode known;
					known["skill"].String() = SecondarySkill::encode(skill.getNum());
					known["level"].Integer() = level;
					item["secondary_skills"].Vector().push_back(known);
				}

			request["observation"]["heroes"].Vector().push_back(item);
		}
		auto addUpgrades = [&](const CArmedInstance * army) {
			for(const auto & [slot, stack] : army->Slots())
			{
				UpgradeInfo info(stack->getId());
				cb->fillUpgradeInfo(army, slot, info);
				for(const auto creature : info.getAvailableUpgrades())
				{
					const auto cost = info.getUpgradeCostsFor(creature) * stack->getCount();
					if(!cb->getResourceAmount().canAfford(cost)) continue;
					const auto id = "upgrade-" + std::to_string(upgrades.size());
					upgrades.emplace(id, UpgradeChoice{army->id, slot, stack->getId(), creature, stack->getCount(), cost});
					JsonNode action;
					action["id"].String() = id;
					action["kind"].String() = "upgrade";
					action["destination"].Integer() = objectAlias(army->id);
					action["slot"].Integer() = slot.getNum();
					action["from_creature"].String() = stack->getCreature()->getJsonKey();
					action["creature"].String() = creature.toCreature()->getJsonKey();
					action["amount"].Integer() = stack->getCount();
					action["cost"] = resourcesJSON(cost);
					action["effect"].String() = "replace_existing_stack_type_keep_count";
					action["army_value_gain"].Float() = static_cast<double>(creature.toCreature()->getAIValue() - stack->getCreature()->getAIValue()) * stack->getCount();
					action["joins_hero"].String() = army->ID == Obj::HERO ? "immediately" : "separate_visit_and_transfer";
					request["actions"].Vector().push_back(action);
				}
			}
		};
		for(const auto * hero : cb->getHeroesInfo())
			if(hero->tempOwner == playerID) addUpgrades(hero);
		JsonNode end;
		end["id"].String() = "end";
		end["kind"].String() = "end_turn";
		request["actions"].Vector().push_back(end);
		request["observation"]["towns"].Vector();
		for(const auto * town : cb->getTownsInfo(true))
		{
			if(canHireHero(*cb, playerID, town))
				for(const auto * candidate : cb->getAvailableHeroes(town))
				{
					const auto id = "hire-hero-" + std::to_string(hires.size());
					hires.emplace(id, HeroHireChoice{town->id, candidate->getHeroTypeID()});
					JsonNode action;
					action["id"].String() = id;
					action["kind"].String() = "hire_hero";
					action["town"].Integer() = objectAlias(town->id);
					action["hero_type"].String() = candidate->getHeroType()->getJsonKey();
					action["level"].Integer() = candidate->level;
					action["army"] = armyJSON(candidate);
					action["secondary_skills"].Vector();
					for(const auto & [skill, level] : candidate->secSkills)
						if(skill != SecondarySkill::NONE)
						{
							JsonNode item;
							item["skill"].String() = SecondarySkill::encode(skill.getNum());
							item["level"].Integer() = level;
							action["secondary_skills"].Vector().push_back(item);
						}
					action["cost"] = resourcesJSON(heroHireCost());
					action["spawn_position"] = positionJSON(town->visitablePos());
					action["effect"].String() = "new_owned_visiting_hero_with_starting_army_separate_movement_required";
					request["actions"].Vector().push_back(action);
				}
			addUpgrades(town);
			JsonNode townInfo;
			townInfo["id"].Integer() = objectAlias(town->id);
            const auto faction = town->getTown()->faction->getJsonKey();
            townInfo["faction"].String() = faction;
            if(request["observation"]["rules"]["factions"][faction].isNull())
                request["observation"]["rules"]["factions"][faction] = factionRules(town->getTown());
            for(const auto & [id, building] : town->getTown()->buildings)
                if(building->mode == CBuilding::BUILD_NORMAL)
                    townInfo["development"][building->getJsonKey()].String() = buildingAvailability(cb->canBuildStructure(town, id));
			townInfo["army"] = armyJSON(town);
			townInfo["strength"].Float() = town->getArmyStrength();
			townInfo["fort_level"].Integer() = town->fortLevel();
			townInfo["stationed_heroes"].Vector();
			for(const auto * hero : {town->getVisitingHero(), town->getGarrisonHero()})
				if(hero && hero->tempOwner == playerID)
				{
					JsonNode presence;
					presence["hero"].Integer() = objectAlias(hero->id);
					presence["army_ai_value"].Float() = hero->getArmyStrength();
					presence["role"].String() = hero == town->getGarrisonHero() ? "garrison" : "visiting";
					townInfo["stationed_heroes"].Vector().push_back(presence);
				}
			townInfo["daily_income"] = resourcesJSON(town->dailyIncome());
			townInfo["position"] = positionJSON(town->visitablePos());
			for(const auto & [id, building] : town->getTown()->buildings)
				if(town->hasBuilt(id))
					townInfo["buildings"].Vector().push_back(JsonNode(building->getJsonKey()));
			for(int tier = 0; tier < town->creatures.size(); ++tier)
			{
				JsonNode stock;
				stock["tier"].Integer() = tier + 1;
				stock["available"].Integer() = town->creatures[tier].first;
				stock["growth_now"].Integer() = town->creatures[tier].second.empty() ? 0 : town->getGrowthInfo(tier).totalGrowth();
				stock["days_to_next_growth"].Integer() = 7 - ((static_cast<int>(turn) - 1) % 7);
				for(const auto creature : town->creatures[tier].second)
					stock["creatures"].Vector().push_back(JsonNode(creature.toCreature()->getJsonKey()));
				townInfo["stock"].Vector().push_back(stock);
			}
			request["observation"]["towns"].Vector().push_back(townInfo);
			if(const auto * hero = town->getVisitingHero(); hero && hero->tempOwner == playerID)
			{
				for(const auto & [slot, stack] : town->Slots())
				{
					if(!hero->getSlotFor(stack->getId()).validSlot()) continue;
					const auto id = "transfer-" + std::to_string(transfers.size());
					transfers.emplace(id, TransferChoice{town->id, hero->id, slot, stack->getId(), stack->getCount()});
					JsonNode action;
					action["id"].String() = id;
					action["kind"].String() = "transfer";
					action["town"].Integer() = objectAlias(town->id);
					action["destination"].Integer() = objectAlias(hero->id);
					action["creature"].String() = stack->getCreature()->getJsonKey();
					action["amount"].Integer() = stack->getCount();
					action["cost"] = resourcesJSON(ResourceSet{});
					action["army_value_gain"].Float() = static_cast<double>(stack->getCreature()->getAIValue()) * stack->getCount();
					action["joins_hero"].String() = "immediately";
					request["actions"].Vector().push_back(action);
				}
			}
			for(const auto & [id, building] : town->getTown()->buildings)
			{
				if(building->mode != CBuilding::BUILD_NORMAL || cb->canBuildStructure(town, id) != EBuildingState::ALLOWED)
					continue;
				const auto actionID = "build-" + std::to_string(builds.size());
				builds.emplace(actionID, BuildChoice{town->id, id});
				JsonNode action;
				action["id"].String() = actionID;
				action["kind"].String() = "build";
				action["town"].Integer() = objectAlias(town->id);
				action["building"].String() = building->getJsonKey();
				action["cost"] = resourcesJSON(building->resources);
				action["effects"]["existing_stacks_changed"].Bool() = false;
				action["effects"]["description"].String() = building->getDescriptionTranslated();
				action["effects"]["fortification_component"]["walls_health"].Integer() = building->fortifications.wallsHealth;
				action["effects"]["fortification_component"]["citadel_health"].Integer() = building->fortifications.citadelHealth;
				action["effects"]["fortification_component"]["upper_tower_health"].Integer() = building->fortifications.upperTowerHealth;
				action["effects"]["fortification_component"]["lower_tower_health"].Integer() = building->fortifications.lowerTowerHealth;
				action["effects"]["fortification_component"]["moat"].Bool() = building->fortifications.hasMoat;
				action["effects"]["building_production"] = resourcesJSON(building->produce);
				ResourceSet incomeDelta = building->produce;
				for(auto predecessor = building->upgrade; predecessor != BuildingID::NONE; )
				{
					const auto previous = town->getTown()->buildings.find(predecessor);
					if(previous == town->getTown()->buildings.end()) break;
					if(town->hasBuilt(predecessor)) { incomeDelta -= previous->second->produce; break; }
					predecessor = previous->second->upgrade;
				}
				action["effects"]["production_delta_before_handicap"] = resourcesJSON(incomeDelta);
				action["effects"]["income_benefit"].String() = "next_day_production_only_bonuses_not_projected";
				if(incomeDelta[GameResID::GOLD] > 0)
					action["effects"]["gold_payback_days_before_handicap"].Float() = static_cast<double>(building->resources[GameResID::GOLD]) / incomeDelta[GameResID::GOLD];
				action["effects"]["follow_up"].String() = "separate_recruit_or_upgrade_when_offered";
				for(int tier = 0; tier < town->getTown()->creatures.size(); ++tier)
					for(int version = 0; version < town->getTown()->creatures[tier].size(); ++version)
						if(id == BuildingID::getDwellingFromLevel(tier, version))
						{
							action["effects"]["dwelling_tier"].Integer() = tier + 1;
							action["effects"]["creature"].String() = town->getTown()->creatures[tier][version].toCreature()->getJsonKey();
							action["effects"]["available_stock_now"].Integer() = town->creatures[tier].first;
							action["effects"]["future_stock"].String() = "conditional_recheck_after_build";
						}

				request["actions"].Vector().push_back(action);
			}
			const CArmedInstance * destination = town;
			if(const auto * visitor = town->getVisitingHero(); visitor && visitor->tempOwner == playerID)
				destination = visitor;
			for(int level = 0; level < town->creatures.size(); ++level)
			{
				const auto & available = town->creatures[level];
				for(const auto & creatureID : available.second)
				{
					const auto * creature = creatureID.toCreature();
					if(creature->warMachine != ArtifactID::NONE || !destination->getSlotFor(creatureID).validSlot())
						continue;
					const auto amount = std::min<int>(available.first, creature->maxAmount(cb->getResourceAmount()));
					if(amount <= 0)
						continue;
					for(const int count : std::set<int>{amount, std::max(1, amount / 2)})
					{
						const auto actionID = "recruit-" + std::to_string(recruits.size());
						recruits.emplace(actionID, RecruitChoice{town->id, destination->id, creatureID, count, level});
						JsonNode action;
						action["id"].String() = actionID;
						action["kind"].String() = "recruit";
						action["town"].Integer() = objectAlias(town->id);
						action["destination"].Integer() = objectAlias(destination->id);
						action["creature"].String() = creature->getJsonKey();
						action["amount"].Integer() = count;
						action["cost"] = resourcesJSON(creature->getFullRecruitCost() * count);
						action["army_value_gain"].Float() = static_cast<double>(creature->getAIValue()) * count;
						action["joins_hero"].String() = destination->ID == Obj::HERO ? "immediately" : "separate_visit_and_transfer";
						request["actions"].Vector().push_back(action);
					}
				}
			}
		}
		// Build routes from the player-scoped pathfinder; only known objects or
		// revealed frontier tiles may become strategic targets.
		for(const auto * hero : cb->getHeroesInfo())
		{
			if(hero->tempOwner != playerID || hero->isGarrisoned() || hero->movementPointsRemaining() <= 0)
				continue;
			auto paths = visiblePaths(*cb, hero);
			std::set<ObjectInstanceID> seen;
			std::map<int, std::pair<float, int3>> frontiers;
			const auto size = cb->getMapSize();
			auto addMove = [&](int3 pos, const std::string & kind, const CGObjectInstance * object) {
				CGPath path;
				if(pos == hero->visitablePos() || !paths->getPath(path, pos, EPathfindingLayer::LAND)
					|| !path.hasNextNode() || path.nextNode().turns > 0)
					return;
				const auto actionID = "move-" + std::to_string(moves.size());
				moves.emplace(actionID, MoveChoice{hero->id, pos});
				JsonNode action;
				action["id"].String() = actionID;
				action["kind"].String() = kind;
				action["hero"].Integer() = objectAlias(hero->id);
				action["target"] = positionJSON(pos);
				action["travel_turns"].Float() = path.lastNode().cost;
				action["route_steps"].Integer() = path.nodes.size() - 1;
				action["arrival_turn_offset"].Integer() = path.lastNode().turns;
				JsonNode route;
				for(auto node = path.nodes.rbegin() + 1; node != path.nodes.rend(); ++node)
				{
					JsonNode step;
					step["position"] = positionJSON(node->coord);
					step["turn"].Integer() = node->turns;
					step["interaction"].Bool() = node->action != EPathNodeAction::NORMAL;
					step["stops_before_tile"].Bool() = node->action == EPathNodeAction::BLOCKING_VISIT;
					step["battle"].Bool() = node->action == EPathNodeAction::BATTLE;
					step["known_guards"].Vector();
					for(const auto * guard : cb->getGuardingCreatures(node->coord))
						if(cb->isVisible(guard)) step["known_guards"].Vector().push_back(JsonNode(objectAlias(guard->id)));
					route.Vector().push_back(step);
				}
				action["turn_stop"] = externalai::routeForecast(positionJSON(hero->visitablePos()), route);
				if(!action["turn_stop"]["encounters"].Vector().empty()
					&& action["turn_stop"]["encounters"][0]["stops_before_tile"].Bool())
				{
					// Replanning equal-cost approaches can choose another neighbour.
					// Supply a visible reachable envelope rather than an exact claim.
					const auto & encounter = action["turn_stop"]["interaction_position"].Vector();
					for(int dx = -1; dx <= 1; ++dx)
					for(int dy = -1; dy <= 1; ++dy)
					{
						if(dx == 0 && dy == 0) continue;
						const int3 neighbour(encounter[0].Integer() + dx, encounter[1].Integer() + dy, encounter[2].Integer());
						if(!cb->isInTheMap(neighbour) || !cb->isVisible(neighbour)) continue;
						const auto * node = paths->getPathInfo(neighbour, EPathfindingLayer::LAND);
						if(!node || !node->reachable() || node->turns > 0 || node->action != EPathNodeAction::NORMAL) continue;
						const auto position = positionJSON(neighbour);
						if(!vstd::contains(action["turn_stop"]["possible_positions"].Vector(), position))
							action["turn_stop"]["possible_positions"].Vector().push_back(position);
					}
				}
				action["route_encounters"].Vector();
				for(const auto & step : route.Vector())
					if(step["interaction"].Bool()) action["route_encounters"].Vector().push_back(step);
				// Proximity only: enemy movement/routing and unseen armies remain unknown.
				action["stop_threats"].Vector();
				auto addThreat = [&](const JsonNode & sighting, bool stale) {
					if(sighting["kind"].String() != "hero" || sighting["owner"].Integer() == playerID.getNum()
						|| sighting["not_seen_at_last_position"].Bool()) return;
					if(stale && !externalai::rememberedThreatStillPossible(sighting, visiblePositions)) return;
					const auto & enemy = sighting["position"].Vector();
					const auto & stop = action["turn_stop"]["position"].Vector();
					if(enemy.size() != 3 || enemy[2] != stop[2]) return;
					JsonNode threat;
					threat["object_id"] = sighting["id"];
					threat["position"] = sighting["position"];
					threat["tile_distance"].Integer() = std::max(std::abs(enemy[0].Integer() - stop[0].Integer()), std::abs(enemy[1].Integer() - stop[1].Integer()));
					for(const auto & possible : action["turn_stop"]["possible_positions"].Vector())
						threat["tile_distance"].Integer() = std::min<int>(threat["tile_distance"].Integer(), std::max(std::abs(enemy[0].Integer() - possible[0].Integer()), std::abs(enemy[1].Integer() - possible[1].Integer())));
					threat["distance_basis"].String() = "minimum_over_possible_stops";
					threat["age_days"].Integer() = stale ? static_cast<int>(turn) - sighting["last_seen_day"].Integer() : 0;
					threat["stale"].Bool() = stale;
					threat["army"] = sighting["army"];
					threat["interception"].String() = "unknown_enemy_movement";
					action["stop_threats"].Vector().push_back(threat);
				};
				std::set<int> currentThreats;
				for(const auto & item : request["observation"]["visible_objects"].Vector())
				{
					currentThreats.insert(item["id"].Integer());
					addThreat(item, false);
				}
				for(const auto & item : static_cast<const JsonNode &>(savedState)["memory"]["known_objects"].Vector())
					if(!currentThreats.count(item["id"].Integer())) addThreat(item, true);
				action["unseen_threats"].String() = "unknown";

				if(object)
				{
					action["object_id"].Integer() = objectAlias(object->id);
					action["object_type"].Integer() = object->ID.getNum();
					action["owner"].Integer() = object->tempOwner.getNum();
					appendResourceInfo(action, object);
					if(object->ID == Obj::HERO)
					{
						InfoAboutHero info;
						if(cb->getHeroInfo(object, info)) action["army"] = visibleArmyJSON(info.army);
					}
					else if(object->ID == Obj::TOWN)
					{
						InfoAboutTown info;
						if(cb->getTownInfo(object, info)) { action["army"] = visibleArmyJSON(info.army); action["fort_level"].Integer() = info.fortLevel; }
					}
					else if(const auto * armed = dynamic_cast<const CArmedInstance *>(object))
						action["army"] = visibleArmyJSON(InfoAboutArmy(armed, false).army);
				}
				if(object && object->ID == Obj::TOWN && object->tempOwner == playerID)
				{
					const auto * town = static_cast<const CGTownInstance *>(object);
					action["reinforcement"]["town_army_ai_value"].Float() = town->getArmyStrength();
					action["reinforcement"]["joins_hero"].String() = "visit_then_separate_transfer_or_recruit";
					action["reinforcement"]["purchase_availability"].String() = "conditional_recheck_stock_resources_slots";
					action["reinforcement"]["onward_travel"].String() = "unknown_recheck_after_return";
				}
				if(action["army"]["strength"]["estimate"].isNumber())
				{
					action["combat"]["own_army_ai_value"].Float() = hero->getArmyStrength();
					action["combat"]["enemy"] = action["army"]["strength"];
					const auto enemy = action["army"]["strength"]["estimate"].Float();
					if(enemy > 0) action["combat"]["creature_value_ratio"].Float() = hero->getArmyStrength() / enemy;
					action["combat"]["losses"].String() = "unknown_battle_ai_terrain_spells_siege";
				}
				request["actions"].Vector().push_back(action);
			};
			for(int z = 0; z < size.z; ++z)
			for(int y = 0; y < size.y; ++y)
			for(int x = 0; x < size.x; ++x)
			{
				const int3 pos(x, y, z);
				if(!cb->isVisible(pos)) continue;
				const auto * tile = cb->getTile(pos, false);
				if(!tile || !tile->isLand()) continue;
				for(const auto * object : cb->getVisitableObjs(pos, false))
				{
					if(!seen.insert(object->id).second || !cb->isVisible(object->visitablePos())) continue;
					const auto type = object->ID;
					if(type != Obj::TOWN && type != Obj::HERO && type != Obj::MONSTER && type != Obj::MINE
						&& type != Obj::RESOURCE && type != Obj::ARTIFACT && type != Obj::TREASURE_CHEST) continue;
					if(type == Obj::HERO && object->tempOwner == playerID) continue;
					if(type == Obj::MINE && object->tempOwner == playerID) continue;
					const bool attack = type == Obj::MONSTER || ((type == Obj::HERO || type == Obj::TOWN) && object->tempOwner != playerID);
					addMove(object->visitablePos(), attack ? "attack" : "visit", object);
				}
				int unknownNeighbours = 0;
				for(int dx = -1; dx <= 1; ++dx)
				for(int dy = -1; dy <= 1; ++dy)
					if(cb->isInTheMap(pos + int3(dx, dy, 0)) && !cb->isVisible(pos + int3(dx, dy, 0))) ++unknownNeighbours;
				if(!unknownNeighbours || pos == hero->visitablePos()) continue;
				CGPath path;
				if(!paths->getPath(path, pos, EPathfindingLayer::LAND) || !path.hasNextNode() || path.nextNode().turns > 0) continue;
				const auto delta = pos - hero->visitablePos();
				const int sector = (delta.x > 0 ? 1 : delta.x < 0 ? -1 : 0) + 3 * (delta.y > 0 ? 1 : delta.y < 0 ? -1 : 0) + 20 * z;
				const float score = unknownNeighbours / (1.f + path.lastNode().cost);
				if(!frontiers.count(sector) || frontiers.at(sector).first < score) frontiers[sector] = {score, pos};
			}
			for(const auto & [sector, frontier] : frontiers) addMove(frontier.second, "explore", nullptr);
		}
		std::set<int> enemies;
		const JsonNode & currentSightings = request["observation"]["visible_objects"];
		const JsonNode & oldSightings = static_cast<const JsonNode &>(savedState)["memory"]["known_objects"];
		for(const auto * sightings : {&currentSightings, &oldSightings})
			for(const auto & sighting : sightings->Vector())
				if(sighting["owner"].isNumber() && sighting["owner"].Integer() >= 0 && sighting["owner"].Integer() < PlayerColor::PLAYER_LIMIT.getNum()
					&& cb->getPlayerRelations(playerID, PlayerColor(sighting["owner"].Integer())) == PlayerRelations::ENEMIES)
					enemies.insert(sighting["owner"].Integer());
		for(auto & town : request["observation"]["towns"].Vector())
			town["defense"] = externalai::townDefense(town, request["observation"], savedState["memory"], request["actions"], visiblePositions, enemies);
		externalai::observeMemory(savedState["memory"], request["observation"], request["actions"], visiblePositions);
		request["observation"]["campaign_review"] = savedState["memory"]["campaign_review"];
		request["memory"] = savedState["memory"];
		request["memory"]["experience_id"].String() = experienceID;
	}
	if(!persistState()) return false;

	std::string actionID = "end";
	bool fromBatch = false;
	if(!queuedActions.empty())
	{
		if(!externalai::batchSituationChanged(batchObservation, request["observation"], batchPreviousAction))
			for(const auto & action : request["actions"].Vector())
				if(externalai::sameCommand(queuedActions.front(), action))
				{
					actionID = action["id"].String();
					fromBatch = true;
					break;
				}
		if(fromBatch) queuedActions.erase(queuedActions.begin());
		else
		{
			logAi->info("ExternalAI batch invalidated request=%s source=%s; replanning", requestID, batchRequestID);
			queuedActions.clear();
		}
	}
	const auto executable = environmentValue("VCMI_EXTERNAL_AI_EXECUTABLE");
	const auto script = environmentValue("VCMI_EXTERNAL_AI_SCRIPT");
	if(!fromBatch && !executable.empty() && !script.empty())
	{
		auto response = externalai::exchange(executable, {script}, externalai::transportJSON(request.toCompactString()), std::chrono::seconds(70), stopping);
		if(response.error.empty())
		{
			try
			{
				JsonParsingSettings parser;
				parser.strict = true;
				parser.mode = JsonParsingSettings::JsonFormatMode::JSON;
				const JsonNode reply(response.output.data(), response.output.size(), parser, "ExternalAI reply");
				const bool hasStrategy = reply.isStruct() && reply.Struct().count("strategy");
				const bool hasCampaign = reply.isStruct() && reply.Struct().count("campaign");
				const bool hasBatch = reply.isStruct() && reply.Struct().count("follow_up_action_ids");
				if(!reply.isStruct() || reply.Struct().size() != 3 + hasStrategy + hasBatch + hasCampaign || !reply["protocol"].isNumber()
					|| reply["protocol"].Float() != 1 || !reply["request_id"].isString()
					|| reply["request_id"].String() != requestID || !reply["action_id"].isString()
					|| (reply["action_id"].String() != "end" && !builds.count(reply["action_id"].String()) && !recruits.count(reply["action_id"].String()) && !hires.count(reply["action_id"].String()) && !moves.count(reply["action_id"].String()) && !transfers.count(reply["action_id"].String()) && !upgrades.count(reply["action_id"].String())))
					throw std::runtime_error("invalid or stale action choice");
				if(hasStrategy && !externalai::validStrategy(reply["strategy"], request["memory"], request["actions"]))
					throw std::runtime_error("invalid strategy update");
				if(hasCampaign && !externalai::validCampaign(reply["campaign"], reply["strategy"], request["memory"], request["observation"], request["actions"]))
                    throw std::runtime_error("invalid campaign update");
                if(!request["memory"]["campaign"].isNull() && (!hasCampaign || reply["campaign"].isNull()) && hasStrategy && !reply["strategy"].isNull())
                {
                    JsonNode retained;
                    retained["decision"].String() = "retain";
                    retained["reason"].String() = "Operational alignment";
                    retained["evidence_refs"].Vector().push_back(JsonNode("observation:day"));
                    retained["plan"] = JsonNode();
                    if(!externalai::validCampaign(retained, reply["strategy"], request["memory"], request["observation"], request["actions"]))
                        throw std::runtime_error("operational goal conflicts with campaign");
                }
                auto choices = externalai::batchChoices(reply, request["actions"]);
				if(choices.size() > request["observation"]["batch_action_limit"].Integer())
					throw std::runtime_error("batch exceeds remaining turn budget");
				if(hasStrategy && !reply["strategy"].isNull())
				{
					bool sameIntent = !savedState["memory"]["plan"].isNull();
					for(const auto * key : {"target_ref", "executor_ref", "ready_when", "complete_when"})
						sameIntent &= savedState["memory"]["plan"][key] == reply["strategy"][key];
					if(!sameIntent)
					{
						savedState["memory"]["plan_result_cursor"] = savedState["memory"]["result_sequence"];
						savedState["memory"].Struct().erase("plan_tracking");
					}
					savedState["memory"]["plan"] = reply["strategy"];
					savedState["memory"]["plan_updated_day"] = request["observation"]["day"];
				}
				if(hasCampaign) externalai::acceptCampaign(savedState["memory"], reply["campaign"], request["observation"]["day"].Integer());
                actionID = reply["action_id"].String();
				queuedActions.assign(choices.begin()+1, choices.end());
				batchRequestID = requestID;
				logAi->info("ExternalAI batch planned request=%s actions=%d", requestID, static_cast<int>(choices.size()));
			}
			catch(const std::exception & error)
			{
				logAi->warn("ExternalAI rejected reply: %s request=%s", error.what(), requestID);
			}
		}
		else
		{
			logAi->warn("ExternalAI controller failure: %s request=%s", response.error, requestID);
			if(response.error == "timeout")
			{
				decisionTimedOut = true;
				return false;
			}
		}
	}
	else if(!fromBatch)
		logAi->warn("ExternalAI executable/script not configured; ending turn");
	if(stopping)
		return false;
	logAi->info("ExternalAI request %s selected %s", requestID, actionID);
	for(const auto & action : request["actions"].Vector())
		if(action["id"].String() == actionID) selectedAction = action;
	batchObservation = request["observation"];
	batchPreviousAction = selectedAction;
	if(fromBatch)
	{
		selectedAction["chosen_in_request"].String() = batchRequestID;
		logAi->info("ExternalAI batch step request=%s action=%s source=%s", requestID, actionID, batchRequestID);
	}
	if(actionID != "end")
	{
		for(const auto & action : request["actions"].Vector())
			if(action["id"].String() == actionID) savedState["pending"] = action;
		if(!persistState()) return false;
	}
	if(moves.count(actionID))
	{
		const auto choice = moves.at(actionID);
		return moveTo(choice.hero, choice.destination, requestID, actionID);
	}
	if(hires.count(actionID))
	{
		const auto choice = hires.at(actionID);
		ResourceSet expectedResources;
		int beforeCount = 0;
		std::set<ObjectInstanceID> beforeHeroes;
		{
			std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
			if(!lockState(gsLock, stopping) || !cb->isPlayerMakingTurn(playerID)) return false;
			const auto * town = cb->getTown(choice.town);
			if(!canHireHero(*cb, playerID, town)) return false;
			const CGHeroInstance * candidate = nullptr;
			for(const auto * available : cb->getAvailableHeroes(town))
				if(available->getHeroTypeID() == choice.hero) candidate = available;
			if(!candidate) return false;
			beforeCount = cb->getHeroCount(playerID, true);
			for(const auto * owned : cb->getHeroesInfo())
				if(owned->tempOwner == playerID) beforeHeroes.insert(owned->id);
			expectedResources = cb->getResourceAmount() - heroHireCost();
			cb->recruitHero(town, candidate);
		}
		const bool acknowledged = waitForRequest();
		std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
		if(!lockState(gsLock, stopping)) return false;
		const auto * town = cb->getTown(choice.town);
		const auto * hired = town ? town->getVisitingHero() : nullptr;
		const bool observed = acknowledged && town && town->tempOwner == playerID && hired && hired->tempOwner == playerID
			&& hired->getHeroTypeID() == choice.hero && !beforeHeroes.count(hired->id)
			&& cb->getHeroCount(playerID, true) == beforeCount + 1 && cb->getResourceAmount() == expectedResources;
		logAi->info("ExternalAI hire hero result observed=%d request=%s action=%s dispatched=1", observed, requestID, actionID);
		return observed;
	}
	if(upgrades.count(actionID))
	{
		const auto choice = upgrades.at(actionID);
		ResourceSet expectedResources;
		{
			std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
			if(!lockState(gsLock, stopping) || !cb->isPlayerMakingTurn(playerID)) return false;
			const auto * army = dynamic_cast<const CArmedInstance *>(cb->getObj(choice.destination));
			if(!army || army->tempOwner != playerID || !army->hasStackAtSlot(choice.slot)) return false;
			const auto & stack = army->getStack(choice.slot);
			if(stack.getId() != choice.original || stack.getCount() != choice.amount) return false;
			UpgradeInfo info(stack.getId());
			cb->fillUpgradeInfo(army, choice.slot, info);
			if(!vstd::contains(info.getAvailableUpgrades(), choice.upgraded)) return false;
			const auto cost = info.getUpgradeCostsFor(choice.upgraded) * choice.amount;
			if(cost != choice.cost || !cb->getResourceAmount().canAfford(cost)) return false;
			expectedResources = cb->getResourceAmount() - cost;
			cb->upgradeCreature(army, choice.slot, choice.upgraded);
		}
		const bool acknowledged = waitForRequest();
		std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
		if(!lockState(gsLock, stopping)) return false;
		const auto * army = dynamic_cast<const CArmedInstance *>(cb->getObj(choice.destination));
		const bool observed = acknowledged && army && army->tempOwner == playerID && army->hasStackAtSlot(choice.slot)
			&& army->getStack(choice.slot).getId() == choice.upgraded && army->getStack(choice.slot).getCount() == choice.amount
			&& cb->getResourceAmount() == expectedResources;
		logAi->info("ExternalAI upgrade result observed=%d request=%s action=%s dispatched=1", observed, requestID, actionID);
		return observed;
	}
	if(transfers.count(actionID))
	{
		const auto choice = transfers.at(actionID);
		int beforeHero = 0, beforeTown = 0;
		ResourceSet beforeResources;
		{
			std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
			if(!lockState(gsLock, stopping) || !cb->isPlayerMakingTurn(playerID)) return false;
			const auto * town = cb->getTown(choice.town);
			const auto * hero = cb->getHero(choice.hero);
			if(!town || !hero || town->tempOwner != playerID || hero->tempOwner != playerID
				|| town->getVisitingHero() != hero || !town->hasStackAtSlot(choice.slot)) return false;
			const auto & stack = town->getStack(choice.slot);
			const auto destination = hero->getSlotFor(choice.creature);
			if(stack.getId() != choice.creature || stack.getCount() != choice.amount || !destination.validSlot()) return false;
			beforeHero = creatureCount(hero, choice.creature);
			beforeTown = creatureCount(town, choice.creature);
			beforeResources = cb->getResourceAmount();
			if(hero->hasStackAtSlot(destination))
				cb->mergeStacks(town, hero, choice.slot, destination);
			else
				cb->swapCreatures(town, hero, choice.slot, destination);
		}
		const bool acknowledged = waitForRequest();
		std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
		if(!lockState(gsLock, stopping)) return false;
		const auto * town = cb->getTown(choice.town);
		const auto * hero = cb->getHero(choice.hero);
		const bool observed = acknowledged && town && hero && town->tempOwner == playerID
			&& hero->tempOwner == playerID && town->getVisitingHero() == hero
			&& creatureCount(town, choice.creature) == beforeTown - choice.amount
			&& creatureCount(hero, choice.creature) == beforeHero + choice.amount
			&& cb->getResourceAmount() == beforeResources;
		logAi->info("ExternalAI transfer result observed=%d request=%s action=%s dispatched=1", observed, requestID, actionID);
		return observed;
	}
	if(recruits.count(actionID))
	{
		const auto choice = recruits.at(actionID);
		int before = 0;
		ResourceSet expectedResources;
		unsigned expectedAvailable = 0;
		{
			std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
			if(!lockState(gsLock, stopping) || !cb->isPlayerMakingTurn(playerID))
				return false;
			const auto * town = cb->getTown(choice.town);
			const auto * destination = dynamic_cast<const CArmedInstance *>(cb->getObj(choice.destination));
			const auto * creature = choice.creature.toCreature();
			if(!town || town->tempOwner != playerID || !destination || destination->tempOwner != playerID
				|| (destination != town && destination != town->getVisitingHero())
				|| choice.level >= town->creatures.size() || town->creatures[choice.level].first < choice.amount
				|| !vstd::contains(town->creatures[choice.level].second, choice.creature)
				|| !destination->getSlotFor(choice.creature).validSlot()
				|| !cb->getResourceAmount().canAfford(creature->getFullRecruitCost() * choice.amount))
				return false;
			before = creatureCount(destination, choice.creature);
			expectedAvailable = town->creatures[choice.level].first - choice.amount;
			expectedResources = cb->getResourceAmount() - creature->getFullRecruitCost() * choice.amount;
			cb->recruitCreatures(town, destination, choice.creature, choice.amount, choice.level);
		}
		const bool acknowledged = waitForRequest();
		std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
		if(!lockState(gsLock, stopping))
			return false;
		const auto * town = cb->getTown(choice.town);
		const auto * destination = dynamic_cast<const CArmedInstance *>(cb->getObj(choice.destination));
		const bool observed = acknowledged && town && destination && destination->tempOwner == playerID
			&& creatureCount(destination, choice.creature) == before + choice.amount
			&& town->creatures[choice.level].first == expectedAvailable && cb->getResourceAmount() == expectedResources;
		logAi->info("ExternalAI recruit result observed=%d request=%s action=%s dispatched=1", observed, requestID, actionID);
		return observed;
	}
	if(builds.count(actionID))
	{
		const auto choice = builds.at(actionID);
		bool sent = false;
		{
			std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
			if(!lockState(gsLock, stopping) || !cb->isPlayerMakingTurn(playerID))
				return false;
			const auto * town = cb->getTown(choice.town);
			if(town && town->tempOwner == playerID)
				sent = cb->buildBuilding(town, choice.building);
		}
		if(sent)
		{
			waitForRequest();
			std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
			if(!lockState(gsLock, stopping))
				return false;
			const auto * town = cb->getTown(choice.town);
			const bool built = town && town->tempOwner == playerID && town->hasBuilt(choice.building);
			logAi->info("ExternalAI build result town=%d building=%d observed=%d request=%s action=%s dispatched=1",
				choice.town.getNum(), choice.building.getNum(), built, requestID, actionID);
			return built;
		}
		else
			logAi->info("ExternalAI build result town=%d building=%d observed=0 request=%s action=%s dispatched=0",
				choice.town.getNum(), choice.building.getNum(), requestID, actionID);
	}
	return false;
}

bool ExternalAI::moveTo(ObjectInstanceID heroID, int3 destination, const std::string & requestID, const std::string & actionID)
{
	bool progressed = false;
	// A route is a bounded sequence of ordinary engine steps. Recompute after
	// every result so new visibility, queries, battles and lost heroes invalidate it.
	for(int step = 0; step < 256 && !stopping; ++step)
	{
		int3 before;
		int movementBefore;
		bool stopAfterStep;
		{
			std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
			if(!lockState(gsLock, stopping) || !cb->isPlayerMakingTurn(playerID)) return false;
			const auto * hero = cb->getHero(heroID);
			if(!hero || hero->tempOwner != playerID || hero->isGarrisoned() || !cb->isVisible(destination)) break;
			before = hero->visitablePos();
			movementBefore = hero->movementPointsRemaining();
			if(before == destination || movementBefore <= 0) break;
			CGPath path;
			if(!visiblePaths(*cb, hero)->getPath(path, destination, EPathfindingLayer::LAND)
				|| !path.hasNextNode() || path.nextNode().turns > 0) break;
			const auto & next = path.nextNode();
			stopAfterStep = next.action != EPathNodeAction::NORMAL;
			cb->moveHero(hero, hero->convertFromVisitablePos(next.coord), false, EPathfindingLayer::LAND);
		}
		if(!waitForRequest(180))
		{
			logAi->error("ExternalAI move outcome unknown request=%s action=%s", requestID, actionID);
			return false;
		}
		std::shared_lock gsLock(CGameState::mutex, std::defer_lock);
		if(!lockState(gsLock, stopping)) return false;
		const auto * hero = cb->getHero(heroID);
		if(!hero || hero->tempOwner != playerID) break;
		const bool changed = hero->visitablePos() != before || hero->movementPointsRemaining() != movementBefore;
		progressed |= changed;
		if(!changed || stopAfterStep) break;
	}
	logAi->info("ExternalAI move result observed=%d request=%s action=%s dispatched=1", progressed, requestID, actionID);
	return progressed;
}

void ExternalAI::showInfoDialog(EInfoWindowMode, const std::string &, const std::vector<Component> & components, int)
{
	// Only player-addressed information reaches this interface. Do not touch
	// worker-owned savedState here; drain the bounded notifications when persisting.
	std::lock_guard lock(requestMutex);
	for(const auto & component : components)
	{
		if(component.type != ComponentType::RESOURCE || !component.value) continue;
		JsonNode notice;
		notice["resource_type"].String() = GameResID::encode(component.subType.as<GameResID>().getNum());
		notice["amount"].Integer() = *component.value;
		notice["source"].String() = "player_info_dialog";
		resourceNotifications.push_back(std::move(notice));
	}
	if(resourceNotifications.size() > 16)
		resourceNotifications.erase(resourceNotifications.begin(), resourceNotifications.end() - 16);
}

void ExternalAI::showRecruitmentDialog(const CGDwelling *, const CArmedInstance *, int, QueryID id) { answer(id, 0); }
void ExternalAI::showMarketWindow(const IMarket *, const CGHeroInstance *, QueryID id) { answer(id, 0); }
void ExternalAI::showUniversityWindow(const IMarket *, const CGHeroInstance *, QueryID id) { answer(id, 0); }
void ExternalAI::showTavernWindow(const CGObjectInstance *, const CGHeroInstance *, QueryID id) { answer(id, 0); }

void ExternalAI::heroGotLevel(const CGHeroInstance * hero, PrimarySkill, std::vector<SecondarySkill> & offered, QueryID id)
{
	double total = 0, ranged = 0;
	bool combatGoal = true;
	if(hero && hero->tempOwner == playerID)
	{
		for(const auto & [slot, stack] : hero->Slots())
		{
			const auto value = static_cast<double>(stack->getCreature()->getAIValue()) * stack->getCount();
			total += value;
			if(stack->getCreature()->getBaseShots() > 0) ranged += value;
		}
		std::lock_guard lock(requestMutex);
		if(const auto found = developmentCombatGoals.find(hero->id); found != developmentCombatGoals.end()) combatGoal = found->second;
	}
	const auto choice = externalai::chooseSecondarySkill(offered, total, ranged, combatGoal);
	if(!offered.empty()) logAi->info("ExternalAI secondary skill choice=%d skill=%s goal=%s ranged_value=%f army_value=%f", choice,
		SecondarySkill::encode(offered[choice].getNum()), combatGoal ? "combat" : "travel", ranged, total);
	answer(id, choice);
}
void ExternalAI::commanderGotLevel(const CCommanderInstance *, std::vector<ui32>, QueryID id) { answer(id, 0); }
void ExternalAI::showBlockingDialog(const std::string &, const std::vector<Component> &, QueryID id, int, bool selection, bool cancel, bool safeToAutoaccept)
{
	answer(id, cancel || !selection ? 0 : 1);
}
void ExternalAI::showTeleportDialog(const CGHeroInstance *, TeleportChannelID, TTeleportExitsList, bool, QueryID id) { answer(id, 0); }
// A hero encounter only closes the existing engine dialog; it never transfers armies.
void ExternalAI::heroExchangeStarted(ObjectInstanceID, ObjectInstanceID, QueryID id) { answer(id, 0); }
void ExternalAI::showGarrisonDialog(const CArmedInstance *, const CGHeroInstance *, bool, QueryID id, const MetaString &) { answer(id, 0); }
void ExternalAI::showMapObjectSelectDialog(QueryID id, const Component &, const MetaString &, const MetaString &, const std::vector<ObjectInstanceID> &) { answer(id, 0); }
std::optional<BattleAction> ExternalAI::makeSurrenderRetreatDecision(const BattleID &, const BattleStateInfoForRetreat &) { return std::nullopt; }
