#pragma once
#include "../Nullkiller2/AIGateway.h"
#include "../../lib/AsyncRunner.h"
#include "../../lib/gameState/CGameState.h"
#include "../../lib/mapObjects/CGTownInstance.h"
#include <cstdlib>

namespace nullkiller3
{
// Test-only starting-state driver. The ordinary, acknowledged swap packet
// puts the map's visiting hero into its garrison before the native planner runs.
class GarrisonProbe final : public NK2AI::AIGateway
{
    bool initialized=false;
    bool dipped=false;
public:
    GarrisonProbe() : AIGateway(true) {}
    void garrisonsChanged(ObjectInstanceID first,ObjectInstanceID second) override
    {
        AIGateway::garrisonsChanged(first,second);
        for(const auto * hero:cc->getHeroesInfo())
            if(hero->id==first || hero->id==second)
                logGlobal->info("NK3_TEST_ARMY day=%d hero=%d army=%llu slots=%d",cc->getCalendar().getCurrentDay(),
                    hero->id.getNum(),hero->estimateCombatValue(),hero->stacksCount());
    }
    void yourTurn(QueryID query) override
    {
        const auto * mode=std::getenv("VCMI_NK3_GARRISON_PROBE_MODE");
        if(initialized && !dipped && mode && (std::string(mode)=="force_dip" || std::string(mode)=="force_loss"))
        {
            dipped=true;
            const bool loss=std::string(mode)=="force_loss";
            asyncTasks->run([this,query,loss] {
                std::shared_lock lock(CGameState::mutex);
                for(const auto * town:cc->getTownsInfo())
                    if(town->getGarrisonHero())
                    {
                        const auto * army=town->getUpperArmy();
                        if(loss)
                        {
                            const auto * hero=town->getGarrisonHero();
                            cc->swapGarrisonHero(town);
                            for(int step=0;step<2;++step)
                                cc->moveHero(hero,hero->convertFromVisitablePos(hero->visitablePos()+int3(0,1,0)),false,EPathfindingLayer::LAND);
                            if(hero->visitablePos().y!=13) throw std::runtime_error("survivor fixture did not leave its safe town");
                        }
                        cc->dismissCreature(army,army->Slots().begin()->first);
                        logGlobal->info("NK3_TEST_DIP day=%d army=%llu",cc->getCalendar().getCurrentDay(),army->estimateCombatValue());
                        if(!loss)
                        {
                            const auto & stock=town->creatures.at(0);
                            cc->recruitCreatures(town,army,stock.second.front(),std::min<uint32_t>(10,stock.first),0);
                            logGlobal->info("NK3_TEST_RECOVERED day=%d army=%llu",cc->getCalendar().getCurrentDay(),army->estimateCombatValue());
                        }
                        break;
                    }
                AIGateway::yourTurn(query);
            });
            return;
        }
        if(initialized) { AIGateway::yourTurn(query);return; }
        initialized=true;
        asyncTasks->run([this,query] {
            std::shared_lock lock(CGameState::mutex);
            for(const auto * town:cc->getTownsInfo())
                if(town->getVisitingHero() && !town->getGarrisonHero())
                {
                    cc->swapGarrisonHero(town);
                    if(!town->getGarrisonHero()) throw std::runtime_error("garrison fixture swap was not acknowledged");
                    logGlobal->info("NK3_TEST_GARRISON town=%d hero=%d army=%llu",town->id.getNum(),
                        town->getGarrisonHero()->id.getNum(),town->getUpperArmy()->estimateCombatValue());
                    logGlobal->info("NK3_TEST_ARMY day=%d hero=%d army=%llu slots=%d",cc->getCalendar().getCurrentDay(),
                        town->getGarrisonHero()->id.getNum(),town->getUpperArmy()->estimateCombatValue(),town->getUpperArmy()->stacksCount());
                    break;
                }
            AIGateway::yourTurn(query);
        });
    }
};
}
