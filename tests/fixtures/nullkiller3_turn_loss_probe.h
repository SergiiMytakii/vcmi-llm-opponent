#pragma once
#include "../Nullkiller2/AIGateway.h"
#include "../Nullkiller2/Engine/Nullkiller.h"
#include "NativeCampaign.h"
#include "../../lib/AsyncRunner.h"
#include "../../lib/gameState/CGameState.h"
#include "../../lib/networkPacks/PacksForClient.h"
#include <cstdlib>
#include <chrono>
#include <thread>

namespace nullkiller3
{
// Test-only driver: issue a real EndTurn packet while the normal NK3 planner
// waits. It is copied into one private build and never into normal preparation.
class TurnLossProbe final : public NK2AI::AIGateway
{
    std::atomic<bool> scheduled{false};
    bool movementMode() const
    {
        const auto * mode=std::getenv("VCMI_NK3_TURN_LOSS_PROBE_MODE");
        return mode && (std::string(mode)=="movement" || std::string(mode)=="movement_save" || std::string(mode)=="embark_save");
    }
    void endOwnedTurn(int day, const char * trigger)
    {
        std::shared_lock lock(CGameState::mutex);
        if(nullkiller->strategicCampaign->isStopping() || !cc->isPlayerMakingTurn(playerID)
            || cc->getCalendar().getCurrentDay()!=day) return;
        logGlobal->info("NK3_TEST_END_TURN player=%d day=%d trigger=%s",playerID.getNum(),day,trigger);
        const auto * mode=std::getenv("VCMI_NK3_TURN_LOSS_PROBE_MODE");
        if(mode && std::string(mode)=="movement_save" && std::string(trigger)=="movement")
        {
            cc->save("Saves/NK3NativeCommandProbe",false);
            logGlobal->info("NK3_TEST_NATIVE_SAVE day=%d",day);
        }
        cc->endTurn();
    }
public:
    TurnLossProbe() : AIGateway(true) {}
    void yourTurn(QueryID query) override
    {
        AIGateway::yourTurn(query);
        if(movementMode()) return;
        if(scheduled.exchange(true)) return;
        const auto day=cc->getCalendar().getCurrentDay();
        asyncTasks->run([this,day] {
            const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(2);
            while(std::chrono::steady_clock::now()<deadline)
            {
                if(nullkiller->strategicCampaign->isStopping()) return;
                std::this_thread::sleep_for(std::chrono::milliseconds(10));
            }
            try
            {
                endOwnedTurn(day,"model_wait");
            }
            catch(const TerminationRequestedException &) {}
            catch(const InterruptionRequestedException &) {}
        });
    }
    void heroMoved(const TryMoveHero & details, bool verbose) override
    {
        AIGateway::heroMoved(details,verbose);
        const auto * hero=cc->getHero(details.id);
        const auto * mode=std::getenv("VCMI_NK3_TURN_LOSS_PROBE_MODE");
        if(mode && std::string(mode)=="embark_save")
        {
            if(!hero || hero->getOwner()!=playerID || !hero->inBoat()
                || details.result!=TryMoveHero::EMBARK || scheduled.exchange(true)) return;
            // Freeze only this test instance after the real packet has attached
            // its hero to the boat. Saving runs outside the callback, under the
            // usual game-state lock; no subsequent native command can race it.
            nullkiller->strategicCampaign->cancel();
            nullkiller->makingTurnInterruption.interruptThread();
            const auto day=cc->getCalendar().getCurrentDay();
            const auto id=details.id;
            asyncTasks->run([this,day,id] {
                std::shared_lock lock(CGameState::mutex);
                const auto * own=cc->getHero(id);
                if(!own || own->getOwner()!=playerID || !own->inBoat()
                    || cc->getCalendar().getCurrentDay()!=day) return;
                cc->save("Saves/NK3EmbarkedProbe",false);
                logGlobal->info("NK3_TEST_EMBARKED_SAVE day=%d hero=%d",day,id.getNum());
            });
            return;
        }
        if(!movementMode() || !hero || hero->getOwner()!=playerID
            || details.result!=TryMoveHero::SUCCESS || details.start==details.end) return;
        logGlobal->info("NK3_TEST_MOVED player=%d day=%d hero=%d from=%s to=%s",
            playerID.getNum(),cc->getCalendar().getCurrentDay(),details.id.getNum(),
            details.start.toString(),details.end.toString());
        if(scheduled.exchange(true)) return;
        const auto day=cc->getCalendar().getCurrentDay();
        asyncTasks->run([this,day] {
            try { endOwnedTurn(day,"movement"); }
            catch(const TerminationRequestedException &) {}
            catch(const InterruptionRequestedException &) {}
        });
    }
};
}
