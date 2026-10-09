#include "../Nullkiller2/StdInc.h"
#include "PlayerView.h"
#include "ObservedPassages.h"

#include "../../lib/callback/CCallback.h"
#include "../../lib/gameState/InfoAboutArmy.h"
#include "../../lib/battle/CombatValue.h"
#include "../../lib/mapObjects/CGHeroInstance.h"
#include "../../lib/mapObjects/CGTownInstance.h"
#include "../../lib/mapObjects/ObjectTemplate.h"
#include "../../lib/mapObjects/IObjectInterface.h"
#include "../../lib/mapObjects/MiscObjects.h"
#include "../../lib/pathfinder/CPathfinder.h"
#include "../../lib/pathfinder/PathfinderOptions.h"

namespace nullkiller3
{
PlayerView::PlayerView(const CCallback & callback) : source(callback)
{
    const auto heroes = source.getHeroesInfo();
    const auto towns = source.getTownsInfo();
    if(!heroes.empty())
        unknown = *source.getTile(heroes.front()->visitablePos());
    else if(!towns.empty())
        unknown = *source.getTile(towns.front()->visitablePos());
    unknown.visitableObjects.clear();
    unknown.blockingObjects.clear();
    refresh();
}

void PlayerView::refresh()
{
    tiles.clear();
    const auto size = source.getMapSize();
    for(int z = 0; z < size.z; ++z)
        for(int y = 0; y < size.y; ++y)
            for(int x = 0; x < size.x; ++x)
            {
                const int3 pos(x, y, z);
                if(!source.isVisible(pos)) continue;
                auto tile = *source.getTile(pos, false);
                auto hidden = [&](ObjectInstanceID id) { return !source.getObj(id, false); };
                std::erase_if(tile.visitableObjects, hidden);
                std::erase_if(tile.blockingObjects, hidden);
                tiles.emplace(pos, std::move(tile));
            }
}
bool PlayerView::setObservedPassages(const JsonNode & links)
{
    if(!validObservedPassages(links) || observedPassages==links) return false;
    observedPassages=links;return true;
}
std::vector<ObjectInstanceID> PlayerView::getTeleportChannelExits(TeleportChannelID id,PlayerColor player) const
{
    std::vector<ObjectInstanceID> exits;
    const auto owner=source.getPlayerID();
    if(!owner || (player!=PlayerColor::UNFLAGGABLE && player!=*owner) || !observedPassages.isVector()) return exits;
    auto portalAt=[&](const JsonNode & p) -> const CGTeleport * {
        if(!passagePosition(p)) return nullptr;
        const int3 position(p[0].Integer(),p[1].Integer(),p[2].Integer());
        if(!source.isInTheMap(position) || !source.isVisible(position)) return nullptr;
        const auto * tile=source.getTile(position,false);
        if(!tile) return nullptr;
        for(const auto objectID:tile->visitableObjects)
            if(const auto * object=source.getObj(objectID,false);object && (object->ID==Obj::SUBTERRANEAN_GATE
                || object->ID==Obj::MONOLITH_TWO_WAY || object->ID==Obj::MONOLITH_ONE_WAY_ENTRANCE || object->ID==Obj::MONOLITH_ONE_WAY_EXIT))
                return dynamic_cast<const CGTeleport *>(object);
        return nullptr;
    };
    // No global channel table: only own observations. Random one-way exits
    // remain threat possibilities; they cannot establish a chosen own route.
    for(const auto & link:observedPassages.Vector()) {
        const auto * from=portalAt(link["from"]), *to=portalAt(link["to"]);
        if(!from || !to || from->channel!=id || to->channel!=id || !passageLinkFrom(link,link["from"],true)) continue;
        if(link["kind"].isNull()) {
            if(from->ID!=Obj::SUBTERRANEAN_GATE || to->ID!=Obj::SUBTERRANEAN_GATE) continue;
        } else if(from->ID!=Obj::MONOLITH_TWO_WAY || to->ID!=Obj::MONOLITH_TWO_WAY) continue;
        for(const auto endpoint:{from->id,to->id})
            if(std::find(exits.begin(),exits.end(),endpoint)==exits.end()) exits.push_back(endpoint);
    }
    return exits;
}
void PlayerView::calculatePaths(const std::shared_ptr<PathfinderConfig> & config) const
{
    CPathfinder(*this, config).calculatePaths();
}
CGameState & PlayerView::gameState() { throw std::logic_error("PlayerView is read-only"); }
const CGameState & PlayerView::gameState() const { return static_cast<const IGameInfoCallback &>(source).gameState(); }
std::optional<PlayerColor> PlayerView::getPlayerID() const { return source.getPlayerID(); }
const CGObjectInstance * PlayerView::getObjInstance(ObjectInstanceID id) const { return source.getObj(id, false); }

const TerrainTile * PlayerView::getTile(int3 pos, bool verbose) const
{
    if(!source.isInTheMap(pos) || !source.isVisible(pos))
        return &unknown;
    if(const auto found = tiles.find(pos); found != tiles.end())
        return &found->second;
    return &unknown;
}
const TerrainTile * PlayerView::getTileUnchecked(int3 pos) const { return getTile(pos, false); }
std::vector<const CGObjectInstance *> PlayerView::getGuardingCreatures(int3 pos) const
{
    if(!source.isInTheMap(pos) || !source.isVisible(pos))
        return {};
    auto guards = source.getGuardingCreatures(pos);
    std::erase_if(guards, [&](const auto * guard) { return !source.isVisible(guard); });
    return guards;
}
int3 PlayerView::guardingCreaturePosition(int3 pos) const
{
    auto guards = getGuardingCreatures(pos);
    for(const auto * guard : guards)
        if(guard->visitablePos() == pos)
            return pos;
    return guards.empty() ? int3(-1) : guards.front()->visitablePos();
}
bool PlayerView::isTileGuardedUnchecked(int3 pos) const { return guardingCreaturePosition(pos).isValid(); }
bool PlayerView::checkForVisitableDir(const int3 & src, const int3 & dst) const
{
    const auto * tile = getTile(dst);
    if(!tile->entrableTerrain())
        return false;
    for(const auto id : tile->visitableObjects)
        if(vstd::contains(tile->blockingObjects, id))
            if(const auto * object = getObjInstance(id); object && !object->appearance->isVisitableFrom(src.x - dst.x, src.y - dst.y))
                return false;
    return true;
}

void restrictToSupportedMovement(PathfinderOptions & options)
{
    options.useFlying = options.useWaterWalking = false;
    options.useEmbarkAndDisembark = true;
    // PlayerView admits observed visible gates and selectable monolith exits.
    options.useTeleportTwoWay = true;
    options.useTeleportOneWay = options.useTeleportOneWayRandom = false;
    options.useTeleportWhirlpool = options.forceUseTeleportWhirlpool = options.useCastleGate = false;
    options.canUseCast = options.useDimensionDoor = options.ignoreGuards = false;
}

int3 observedBoatPlacement(const CCallback & callback, const IShipyard * shipyard)
{
    if(!shipyard || shipyard->getObject()->getOwner()!=callback.getPlayerID()
        || shipyard->getBoatLayer()!=EPathfindingLayer::SAIL) return int3(-1);
    const auto * object=dynamic_cast<const CGObjectInstance *>(shipyard->getObject());
    if(!object || !callback.isVisible(object)) return int3(-1);
    std::vector<int3> offsets;
    shipyard->getOutOffsets(offsets);
    // The public shipyard window uses these placement/status queries. Require
    // all potential launch tiles to be currently visible before that query;
    // a hidden coast or blocker cannot choose a different virtual boat edge.
    for(const auto & offset:offsets)
    {
        const auto tile=object->visitablePos()+offset;
        if(callback.isInTheMap(tile) && !callback.isVisible(tile)) return int3(-1);
    }
    if(shipyard->shipyardStatus()!=IBoatGenerator::GOOD) return int3(-1);
    const auto position=shipyard->bestLocation();
    return position.isValid() && callback.isVisible(position) ? position : int3(-1);
}

// Each command may reveal tiles or remove a visitable object. Do not reuse the
// planning snapshot for the next command: stale tile IDs can name deleted objects.
std::shared_ptr<const CPathsInfo> currentPlayerPaths(const CCallback & callback, const CGHeroInstance * hero, const JsonNode & observedPassages)
{
    PlayerView view(callback);
    view.setObservedPassages(observedPassages);
    auto paths = std::make_shared<CPathsInfo>(callback.getMapSize(), hero);
    auto config = std::make_shared<SingleHeroPathfinderConfig>(*paths, view, hero);
    restrictToSupportedMovement(config->options);
    CPathfinder(view, config).calculatePaths();
    return paths;
}

JsonNode observedArmyInterval(const CCallback & callback, const CGObjectInstance * object)
{
    JsonNode result;
    result["status"].String() = "unknown";
    result["lower"].Integer() = 0;
    if(!object || !callback.isVisible(object)) return result;
    if(object->getOwner() == callback.getPlayerID())
    {
        const auto * armed = dynamic_cast<const CArmedInstance *>(object);
        const auto value = armed ? armed->estimateCombatValue() : 0;
        result["status"].String() = "exact_own";
        result["lower"].Integer() = value;
        result["upper"].Integer() = value;
        result["estimate"].Integer() = value;
        return result;
    }
    ArmyDescriptor army;
    // Exact visible troop counts are an explicit privileged observation.
    // Preserve the visibility gate above and expose no hero skills or town economy.
    if(const auto * town = dynamic_cast<const CGTownInstance *>(object))
        army = ArmyDescriptor(town->getUpperArmy(), true);
    else if(const auto * armed = dynamic_cast<const CArmedInstance *>(object))
        army = ArmyDescriptor(armed, object->ID == Obj::HERO || object->ID == Obj::MONSTER);
    else
    {
        result["status"].String() = "not_armed";
        result["upper"].Integer() = 0;
        result["estimate"].Integer() = 0;
        return result;
    }
    // Other armed objects retain their ordinary categorical observations.
    static constexpr int64_t low[] = {0,1,5,10,20,50,100,250,500,1000};
    static constexpr int64_t high[] = {0,4,9,19,49,99,249,499,999,0};
    int64_t minimum=0, maximum=0, midpoint=0;
    bool bounded=true;
    const bool exactVisible = army.isDetailed;
    if(exactVisible) result["stacks"].Vector();
    for(const auto & [slot, stack] : army)
    {
        const auto count=stack.getCount();
        const int64_t value=LIBRARY->creh->getCombatValue().getAIValue(stack.getType());
        if(exactVisible)
        {
            JsonNode observed;
            observed["creature_id"].Integer() = stack.getType()->getId().getNum();
            observed["count"].Integer() = count;
            result["stacks"].Vector().push_back(observed);
        }
        if(army.isDetailed) { minimum+=value*count; maximum+=value*count; midpoint+=value*count; }
        else if(count>=1 && count<=9)
        {
            minimum+=value*low[count]; maximum+=value*high[count];
            midpoint+=value*CCreature::estimateCreatureCount(count);
            bounded &= count<9; // Legion has no public finite upper bound.
        }
        else bounded=false;
    }
    result["status"].String() = !bounded ? "unbounded" : army.isDetailed ? "exact_observed" : "category_interval";
    result["lower"].Integer()=minimum;
    result["estimate"].Integer()=midpoint;
    if(bounded) result["upper"].Integer()=maximum;
    result["basis"].String()=exactVisible
        ? "Exact currently visible creature counts and public creature AI values; privileged for enemy heroes/towns, excludes hero combat bonuses; not a battle simulation or loss guarantee"
        : "UI creature counts and public creature AI values; enemy combat bonuses and intentions unknown";
    return result;
}
uint64_t observedArmyStrength(const CCallback & callback, const CGObjectInstance * object)
{
    const auto interval=observedArmyInterval(callback,object);
    // Native safety uses the visible upper interval. Unknown is a conservative
    // risk sentinel, never an assertion that the enemy has zero troops.
    return interval["upper"].isNumber() ? interval["upper"].Integer() : 1000000000000ULL;
}
}
