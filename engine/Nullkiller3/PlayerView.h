#pragma once

#include "../../lib/callback/CGameInfoCallback.h"
#include "../../lib/mapping/TerrainTile.h"
#include "../../lib/json/JsonNode.h"

class CCallback;
struct CPathsInfo;
class CGHeroInstance;
class IShipyard;
struct PathfinderOptions;

namespace nullkiller3
{
// The native pathfinder must use the same visibility boundary as the model.
// Unknown neighbour terrain is a constant placeholder until the fog gate;
// global guarding positions and raw object IDs never pass through this view.
class PlayerView final : public CGameInfoCallback
{
    const CCallback & source;
    TerrainTile unknown;
    mutable std::map<int3, TerrainTile> tiles;

public:
    explicit PlayerView(const CCallback & callback);
    void refresh();
    void calculatePaths(const std::shared_ptr<PathfinderConfig> & config) const override;
    CGameState & gameState() override;
    const CGameState & gameState() const override;
    std::optional<PlayerColor> getPlayerID() const override;
    const CGObjectInstance * getObjInstance(ObjectInstanceID id) const override;
    const TerrainTile * getTile(int3 pos, bool verbose = true) const override;
    const TerrainTile * getTileUnchecked(int3 pos) const override;
    std::vector<const CGObjectInstance *> getGuardingCreatures(int3 pos) const override;
    int3 guardingCreaturePosition(int3 pos) const override;
    bool isTileGuardedUnchecked(int3 pos) const override;
    bool checkForVisitableDir(const int3 & src, const int3 & dst) const override;
};

// Creature-count categories are estimates, never a battle probability. Owned
// armies retain exact information; other visible armies use the ordinary UI DTO.
void restrictToSupportedMovement(PathfinderOptions & options);
int3 observedBoatPlacement(const CCallback & callback, const IShipyard * shipyard);
std::shared_ptr<const CPathsInfo> currentPlayerPaths(const CCallback & callback, const CGHeroInstance * hero);

uint64_t observedArmyStrength(const CCallback & callback, const CGObjectInstance * object);
JsonNode observedArmyInterval(const CCallback & callback, const CGObjectInstance * object);
}
