#pragma once
// Test-only observation and permutation of real generated tasks. Never copied
// by prepare_engine.py or included in an ordinary installed engine.
#include "../Nullkiller2/Goals/ExecuteHeroChain.h"
#include "../Nullkiller2/Goals/BuyArmy.h"
#include "../Nullkiller2/Engine/Nullkiller.h"
#include <cstdlib>

namespace nullkiller3
{
#ifdef NK3_RANK_CONTRACT_PROBE
inline void observeRankingContract(const NK2AI::Nullkiller & ai)
{
    using namespace NK2AI;
    const auto * town=ai.cc->getTownsInfo().front();
    auto task=[&](int amount,float priority,int order,int tier,float score) {
        auto result=Goals::sptr(Goals::BuyArmy(town,amount));
        result->asTask()->priority=priority;
        result->asTask()->nativeRank={order,tier,score};
        return result;
    };
    auto check=[&](const char * name,Goals::TSubgoal first,Goals::TSubgoal second,int expected) {
        TaskPlan plan;plan.mergeAndFilter(first);plan.mergeAndFilter(second);
        const auto selected=plan.getTasks();
        const auto * actual=selected.size()==1 ? dynamic_cast<const Goals::AbstractGoal *>(selected.front().get()) : nullptr;
        JsonNode record;record["case"].String()=name;record["passed"].Bool()=actual && actual->value==expected;
        logAi->info("NK3_TEST_RANK_CONTRACT %s",record.toCompactString());
    };
    const int none=std::numeric_limits<int>::max();
    check("earlier_tier",task(1,50080,0,PriorityEvaluator::EXPLORE_AND_GATHER,10000),task(2,50080,0,PriorityEvaluator::INSTAKILL,10),2);
    check("strategy_priority",task(1,50080,0,PriorityEvaluator::INSTAKILL,1000000),task(2,50090,1,PriorityEvaluator::DEFEND,1),2);
    check("equal_goal_order",task(1,50080,1,PriorityEvaluator::INSTAKILL,1000000),task(2,50080,0,PriorityEvaluator::DEFEND,1),2);
    check("equal_rank_stable",task(1,50080,0,PriorityEvaluator::DEFEND,10),task(2,50080,0,PriorityEvaluator::DEFEND,10),1);
    check("all_zero_admitted",task(1,50080,0,none,0),task(2,50080,0,none,0),1);
    check("urgent_preempts",task(1,50080,0,PriorityEvaluator::INSTAKILL,1000000),task(2,110000,-1,none,0),2);
    check("native_baseline",task(1,10,-1,none,0),task(2,20,-1,none,0),2);
}
#endif

inline JsonNode rankingPath(const NK2AI::Goals::AbstractGoal & task)
{
    JsonNode result;
    result["goal"].String()=task.strategicGoalID;
    result["kind"].Integer()=task.goalType;
    if(const auto * chain=dynamic_cast<const NK2AI::Goals::ExecuteHeroChain *>(&task))
    {
        const auto & path=chain->getPath();
        result["movement_cost"].Float()=path.movementCost();
        result["exchanges"].Integer()=path.exchangeCount;
        result["army"].Integer()=path.heroArmy->estimateCombatValue();
        for(const auto & node:path.nodes)
        {
            JsonNode step;step["hero"].Integer()=node.targetHero->id.getNum();
            for(int n:{node.coord.x,node.coord.y,node.coord.z}) step["position"].Vector().emplace_back(n);
            result["nodes"].Vector().push_back(step);
        }
    }
    return result;
}

template<class Contexts>
void observeRankingChoices(const NK2AI::Nullkiller & ai,NK2AI::Goals::TGoalVec & tasks,
                           const Contexts & contexts,int pass)
{
    using namespace NK2AI;
#ifdef NK3_RANK_CONTRACT_PROBE
    if(pass==1) observeRankingContract(ai);
#endif
    std::map<std::string,std::vector<size_t>> groups;
    std::map<const Goals::AbstractGoal *,std::pair<int,float>> ranks;
    JsonNode record;record["day"].Integer()=ai.cc->getCalendar().getCurrentDay();
    record["pass"].Integer()=pass;
    for(size_t i=0;i<tasks.size();++i)
    {
        const auto & task=tasks[i];
        if(task->strategicGoalID.empty()) continue;
        auto rank=std::make_pair(int(PriorityEvaluator::MAX_PRIORITY_TIER)+1,0.0f);
        for(int tier=PriorityEvaluator::INSTAKILL;tier<=PriorityEvaluator::MAX_PRIORITY_TIER;++tier)
        {
            const float score=ai.priorityEvaluator->evaluate(task,tier,contexts.at(task.get()));
            if(score>0) { rank={tier,score};break; }
        }
        ranks[task.get()]=rank;groups[task->strategicGoalID].push_back(i);
        auto item=rankingPath(*task);item["tier"].Integer()=rank.first;item["score"].Float()=rank.second;
        record["choices"].Vector().push_back(item);
    }
    logAi->info("NK3_TEST_RANK_CHOICES %s",record.toCompactString());
    const auto * order=std::getenv("NK3_RANK_ORDER");
    const bool worst=order && std::string(order)=="worst";
    for(const auto & [goal,indices]:groups)
    {
        Goals::TGoalVec alternatives;
        for(auto i:indices) alternatives.push_back(tasks[i]);
        std::stable_sort(alternatives.begin(),alternatives.end(),[&](const auto & a,const auto & b) {
            const auto ra=ranks.at(a.get()),rb=ranks.at(b.get());
            if(ra.first!=rb.first) return worst ? ra.first>rb.first : ra.first<rb.first;
            return worst ? ra.second<rb.second : ra.second>rb.second;
        });
        for(size_t i=0;i<indices.size();++i) tasks[indices[i]]=alternatives[i];
    }
}

inline void observeRankingSelection(const NK2AI::Goals::TTaskVec & tasks,int pass)
{
    JsonNode record;record["pass"].Integer()=pass;
    for(const auto & task:tasks)
        if(const auto * goal=dynamic_cast<const NK2AI::Goals::AbstractGoal *>(task.get()))
            record["selected"].Vector().push_back(rankingPath(*goal));
    logAi->info("NK3_TEST_RANK_SELECTED %s",record.toCompactString());
}
}
