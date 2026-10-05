#pragma once
#include "../Nullkiller2/AIGateway.h"
#include "../Nullkiller2/Engine/Nullkiller.h"
#include "NativeCampaign.h"
#include "../../lib/AsyncRunner.h"
#include "../../lib/gameState/CGameState.h"
#include "../../lib/mapObjects/CGTownInstance.h"
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <set>
#include <thread>

namespace nullkiller3
{
// Private event driver: three distinct owned armies change only after the
// preceding critical reply has been accepted by the native owner. No game facts
// are injected into the model. Ordinary preparation excludes this class.
class CriticalEventsProbe final : public NK2AI::AIGateway
{
    bool initialized=false,scheduled=false;
    bool withdraw(ObjectInstanceID townID,int ordinal)
    {
        std::shared_lock lock(CGameState::mutex);
        if(nullkiller->strategicCampaign->isStopping() || !cc->isPlayerMakingTurn(playerID)
            || cc->getCalendar().getCurrentDay()!=2) return false;
        for(const auto * town:cc->getTownsInfo())
            if(town->id==townID && town->getGarrisonHero() && town->getUpperArmy()->stacksCount()>1)
            {
                const auto * army=town->getUpperArmy();const auto before=army->estimateCombatValue();
                cc->dismissCreature(army,army->Slots().begin()->first);
                logGlobal->info("NK3_TEST_INDEPENDENT_LOSS day=2 ordinal=%d hero=%d before=%llu after=%llu",
                    ordinal,army->id.getNum(),before,army->estimateCombatValue());
                return army->estimateCombatValue()<before;
            }
        return false;
    }
    bool awaitReview(int count)
    {
        const auto * path=std::getenv("VCMI_NK3_EVENT_LOG");
        if(!path) return false;
        const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(8);
        while(std::chrono::steady_clock::now()<deadline)
        {
            if(nullkiller->strategicCampaign->isStopping()) return false;
            std::ifstream stream(path);std::string line,record;std::set<std::string> received;
            int depth=0;bool quoted=false,escaped=false;
            while(std::getline(stream,line))
            {
                if(record.empty())
                {
                    const auto start=line.find(" ai - NK3_STRATEGY ");
                    if(start==std::string::npos) continue;
                    line=line.substr(start+std::string(" ai - NK3_STRATEGY ").size());
                }
                record+=line+"\n";
                for(const auto ch:line)
                {
                    if(escaped) { escaped=false;continue; }
                    if(quoted && ch=='\\') { escaped=true;continue; }
                    if(ch=='\"') quoted=!quoted;
                    if(!quoted && ch=='{') ++depth;
                    if(!quoted && ch=='}') --depth;
                }
                if(depth) continue;
                JsonParsingSettings parser;parser.strict=true;parser.mode=JsonParsingSettings::JsonFormatMode::JSON;
                JsonNode value(record.data(),record.size(),parser,"private finished-review log");
                if(value["day"].Integer()==2 && value["requested"].Bool() && value["accepted"].Bool())
                    for(const auto & signal:value["signals"].Vector())
                        if(signal["question"].String().starts_with("commitment:")) received.insert(signal["question"].String());
                record.clear();quoted=false;escaped=false;
            }
            if(received.size()>=count) return true;
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
        return false;
    }
public:
    CriticalEventsProbe() : AIGateway(true) {}
    void yourTurn(QueryID query) override
    {
        if(!initialized)
        {
            initialized=true;
            asyncTasks->run([this,query] {
                std::shared_lock lock(CGameState::mutex);
                for(const auto * town:cc->getTownsInfo())
                    if(town->getVisitingHero() && !town->getGarrisonHero()) cc->swapGarrisonHero(town);
                AIGateway::yourTurn(query);
            });
            return;
        }
        if(!scheduled && cc->getCalendar().getCurrentDay()==2)
        {
            scheduled=true;
            asyncTasks->run([this,query] {
                std::vector<ObjectInstanceID> towns;
                { std::shared_lock lock(CGameState::mutex);
                  for(const auto * town:cc->getTownsInfo()) if(town->getGarrisonHero()) towns.push_back(town->id); }
                if(towns.size()!=3 || !withdraw(towns[0],1)) throw std::runtime_error("three owned-garrison fixture was not established");
                AIGateway::yourTurn(query);
                for(int index=1;index<3;++index)
                    if(!awaitReview(index) || !withdraw(towns[index],index+1)) return;
            });
            return;
        }
        AIGateway::yourTurn(query);
    }
};
}
