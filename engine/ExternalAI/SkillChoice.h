#pragma once
#include "constants/EntityIdentifiers.h"
#include <vector>
#include <algorithm>

namespace externalai
{
// The level-up callback chooses an offered index; no extra model call or command.
inline int chooseSecondarySkill(const std::vector<SecondarySkill> & offered,
	double armyValue, double rangedValue, bool combatGoal)
{
	const double rangedShare = armyValue > 0 ? std::clamp(rangedValue / armyValue, 0.0, 1.0) : 0;
	auto score = [&](SecondarySkill skill) -> double {
		if(skill == SecondarySkill::LOGISTICS) return combatGoal ? 80 : 110;
		if(skill == SecondarySkill::PATHFINDING) return combatGoal ? 40 : 90;
		if(skill == SecondarySkill::SCOUTING) return combatGoal ? 20 : 75;
		if(armyValue <= 0) return 0;
		if(skill == SecondarySkill::ARCHERY) return 100 * rangedShare;
		if(skill == SecondarySkill::OFFENCE) return 100 * (1 - rangedShare);
		if(skill == SecondarySkill::ARMORER) return 65;
		if(skill == SecondarySkill::TACTICS) return combatGoal ? 60 : 30;
		if(skill == SecondarySkill::LEADERSHIP) return 45;
		// Unsupported/modded skills stay tied, preserving the offered order.
		return 0;
	};
	int best = 0;
	for(size_t index = 1; index < offered.size(); ++index)
		if(score(offered[index]) > score(offered[best])) best = index;
	return best;
}
}
