#include "StdInc.h"
#include "VisiblePathfinder.h"
#include "../../lib/callback/CCallback.h"
#include "../../lib/gameState/CGameState.h"
#include "../../lib/mapObjects/CGHeroInstance.h"
#include "../../lib/mapping/TerrainTile.h"
#include "../../lib/mapObjects/ObjectTemplate.h"
#include "../../lib/pathfinder/CPathfinder.h"
#include "../../lib/pathfinder/CGPathNode.h"
#include "../../lib/pathfinder/PathfinderOptions.h"

namespace
{
// Stock calculatePaths uses the omniscient CGameState callback. Give the same
// pathfinder a player-scoped view instead, including guards on fog boundaries.
class VisiblePathInfo final : public CGameInfoCallback
{
	const CCallback & source;
	TerrainTile unknown;
	mutable std::map<int3, TerrainTile> tiles;
public:
	VisiblePathInfo(const CCallback & callback, const CGHeroInstance * hero) : source(callback)
	{
		// The pathfinder asks about unrevealed neighbours before its fog gate.
		// Supply a constant known terrain there, never the actual hidden tile.
		unknown = *source.getTile(hero->visitablePos());
		unknown.visitableObjects.clear();
		unknown.blockingObjects.clear();
	}
	CGameState & gameState() override { throw std::logic_error("Pathfinding is read-only"); }
	const CGameState & gameState() const override { return static_cast<const IGameInfoCallback &>(source).gameState(); }
	std::optional<PlayerColor> getPlayerID() const override { return source.getPlayerID(); }
	const CGObjectInstance * getObjInstance(ObjectInstanceID id) const override { return source.getObj(id, false); }
	const TerrainTile * getTile(int3 pos, bool verbose = true) const override
	{
		if(!source.isInTheMap(pos) || !source.isVisible(pos))
			return &unknown;
		auto found = tiles.find(pos);
		if(found != tiles.end())
			return &found->second;
		auto tile = *source.getTile(pos, false);
		auto hidden = [&](ObjectInstanceID id) { return !source.getObj(id, false); };
		std::erase_if(tile.visitableObjects, hidden);
		std::erase_if(tile.blockingObjects, hidden);
		return &tiles.emplace(pos, std::move(tile)).first->second;
	}
	const TerrainTile * getTileUnchecked(int3 pos) const override { return getTile(pos, false); }
	std::vector<const CGObjectInstance *> getGuardingCreatures(int3 pos) const override
	{
		if(!source.isInTheMap(pos) || !source.isVisible(pos))
			return {};
		auto guards = source.getGuardingCreatures(pos);
		std::erase_if(guards, [&](const auto * guard) { return !source.isVisible(guard); });
		return guards;
	}
	int3 guardingCreaturePosition(int3 pos) const override
	{
		auto guards = getGuardingCreatures(pos);
		for(const auto * guard : guards)
			if(guard->visitablePos() == pos)
				return pos;
		return guards.empty() ? int3(-1) : guards.front()->visitablePos();
	}
	bool isTileGuardedUnchecked(int3 pos) const override { return guardingCreaturePosition(pos).isValid(); }
	bool checkForVisitableDir(const int3 & src, const int3 & dst) const override
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
};
}

std::shared_ptr<CPathsInfo> visiblePaths(const CCallback & callback, const CGHeroInstance * hero)
{
	VisiblePathInfo view(callback, hero);
	auto paths = std::make_shared<CPathsInfo>(callback.getMapSize(), hero);
	auto config = std::make_shared<SingleHeroPathfinderConfig>(*paths, view, hero);
	auto & options = config->options;
	options.useFlying = options.useWaterWalking = options.useEmbarkAndDisembark = false;
	options.useTeleportTwoWay = options.useTeleportOneWay = options.useTeleportOneWayRandom = false;
	options.useTeleportWhirlpool = options.forceUseTeleportWhirlpool = options.useCastleGate = false;
	options.canUseCast = options.useDimensionDoor = options.ignoreGuards = false;
	options.turnLimit = 3;
	CPathfinder pathfinder(view, config);
	pathfinder.calculatePaths();
	return paths;
}
