#pragma once

#include <limits>

namespace nullkiller3
{
// Transient selection metadata. Native scores order ways of the same goal;
// they never compete with the campaign's priority or another goal's order.
struct NativeTaskRank
{
    int goalOrder = -1;
    int tier = std::numeric_limits<int>::max();
    float score = 0;
};

template<class Task>
bool prefersTask(const Task & candidate, const Task & incumbent)
{
    if(candidate.priority != incumbent.priority)
        return candidate.priority > incumbent.priority;
    const auto & a = candidate.nativeRank;
    const auto & b = incumbent.nativeRank;
    if((a.goalOrder >= 0) != (b.goalOrder >= 0))
        return a.goalOrder >= 0;
    if(a.goalOrder < 0) return false;
    if(a.goalOrder != b.goalOrder) return a.goalOrder < b.goalOrder;
    if(a.tier != b.tier) return a.tier < b.tier;
    return a.score > b.score;
}
}
