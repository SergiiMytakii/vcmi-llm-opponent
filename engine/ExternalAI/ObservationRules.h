#pragma once
#include "../../lib/GameLibrary.h"
#include "../../lib/callback/CCallback.h"
#include "../../lib/modding/CModHandler.h"
#include "../../lib/modding/ModDescription.h"
#include "../../lib/modding/CModVersion.h"
#include "../../lib/mapping/CMapHeader.h"
#include "../../lib/constants/StringConstants.h"
#include <set>

namespace externalai
{
inline std::string buildingAvailability(EBuildingState state)
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


// Shared public scenario rules. Never serialize special-event target identities.
inline void observeStrategicRules(const CCallback & callback, PlayerColor playerID, JsonNode & observation)
{
        observation["rules"]["engine_version"].String() = GameConstants::VCMI_VERSION;
        observation["rules"]["engine_revision"].String() = GameConstants::GIT_SHA1;
        for(const auto & mod : LIBRARY->modh->getActiveMods())
        {
            JsonNode ruleMod;
            ruleMod["id"].String() = mod;
            ruleMod["version"].String() = LIBRARY->modh->getModInfo(mod).getVersion().toString();
            observation["rules"]["mods"].Vector().push_back(ruleMod);
        }
        // Classify only supported generic predicates. Never serialize an event's
        // object IDs, instance names, positions or hidden values. Icons alone
        // cannot distinguish conquest from a custom map using the same icon.
        const auto * header = callback.getMapHeader();
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
        observation["victory"]["kind"].String() = victoryKind;
        observation["victory"]["supported"].Bool() = supported;
        observation["victory"]["description"].String() = victoryKind == "conquest"
            ? "Defeat all hostile teams; one captured town need not end the game."
            : victoryKind == "control_all_towns" ? "Control all towns as required by this scenario. One captured town alone does not prove victory."
            : "Special public victory condition is not implemented by this adapter.";
        observation["enemy_players"].Vector();
        for(int color = 0; color < PlayerColor::PLAYER_LIMIT.getNum(); ++color)
            if(callback.getPlayerRelations(playerID, PlayerColor(color)) == PlayerRelations::ENEMIES)
                observation["enemy_players"].Vector().push_back(JsonNode(color));
}
}
