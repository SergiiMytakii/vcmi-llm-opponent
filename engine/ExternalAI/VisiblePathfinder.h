#pragma once

#include <memory>

class CCallback;
class CGHeroInstance;
struct CPathsInfo;

// Caller holds the game-state shared lock for the entire calculation.
std::shared_ptr<CPathsInfo> visiblePaths(const CCallback & callback, const CGHeroInstance * hero);
