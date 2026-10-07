#include "AI/Nullkiller2/StdInc.h"
#include "AI/Nullkiller3/NativeCampaign.h"
#include "lib/GameLibrary.h"
#include "lib/entities/ResourceTypeHandler.h"
#include <fstream>
#include <iostream>
#include <stdexcept>

void require(bool value,const char * message) { if(!value) throw std::runtime_error(message); }
JsonNode ownResult()
{
    JsonNode result;
    result["player"].Integer()=0;result["day"].Integer()=1;
    result["engine_object_id"].Integer()=11;result["army_value_before"].Integer()=1000;
    result["army_loss_value"].Integer()=0;result["won"].Bool()=true;result["draw"].Bool()=false;
    // Later producer metadata must never replace a captured start context.
    result["goal_id"].String()="later-plan";result["campaign_revision"].Integer()=77;
    return result;
}
JsonNode completedHire()
{
    // A valid restored intention lets the public accept() boundary change the
    // revision while battle callbacks are pending, without a private test hook.
    const std::string worldText=R"({"day":1,"player":0,"capabilities":[],"resources":[0,0,0,0,0,0,10000],"heroes":[],"towns":[{"ref":"home","buildings":[],"hiring_options":[{"ref":"tavern:42","hero_type_id":42,"can_recruit":true,"cost":[0,0,0,0,0,0,2500]}]}],"objects":[{"ref":"gold","kind":"resource","visible":true,"owner":-1}]})";
    const std::string planText=R"({"version":3,"revision":1,"approach":"economy","horizon_days":5,"goals":[{"id":"helper","kind":"hire_helper","actor_ref":null,"target_ref":"home","deadline_day":5,"priority":50,"building_id":-1,"min_army_value":0,"depends_on":[],"required_capabilities":[],"complete_when":{"kind":"helper_hired","value":0},"candidate_ref":"tavern:42","helper_role":"collector","job_ref":"gold"}],"reserves":[],"policy":{"max_loss_ratio":0.2,"allow_route_repair":true,"allow_helper_replacement":true,"critical_towns":[]}})";
    JsonNode world(worldText.data(),worldText.size(),"own-test-world");
    JsonNode plan(planText.data(),planText.size(),"own-test-plan");
    nullkiller3::CampaignState state;std::string reason;
    require(state.accept(plan,world,reason),reason.c_str());
    JsonNode hero;hero["ref"].String()="new";hero["army_value"].Integer()=500;hero["hero_type_id"].Integer()=42;
    world["heroes"].Vector().push_back(hero);
    JsonNode receipt;receipt["goal"]=plan["goals"][0];receipt["day"].Integer()=1;
    receipt["hero_ref"].String()="new";receipt["hero_type_id"].Integer()=42;
    world["confirmed_helper_hires"].Vector().push_back(receipt);state.review(world);
    require(state.statuses()["helper"]["state"].String()=="completed","hire fixture did not complete");
    JsonNode saved;saved["object_ids"].Struct();saved["native_campaign"]=state.save();return saved;
}
int main(int argc,char ** argv)
{
    try
    {
        auto library=std::make_unique<GameLibrary>();
        library->resourceTypeHandler=std::make_unique<ResourceTypeHandler>();
        LIBRARY=library.get();
        require(argc==2,"expected journal path");
        std::remove(argv[1]);setenv("VCMI_NK3_LEARNING_JOURNAL",argv[1],1);
        for(int mode=0;mode<3;++mode)
        {
            nullkiller3::NativeCampaign campaign{completedHire()};
            require(campaign.commitments().plan()["revision"].Integer()==1,"start fixture was not restored");
            JsonNode position;for(int value:{5,6,0}) position.Vector().emplace_back(value);
            if(mode<2) campaign.battleStarted(11,22,mode==1,position);
            auto revised=campaign.commitments().plan();revised["revision"].Integer()=2;
            std::string reason;require(campaign.accept(revised,reason),reason.c_str());
            require(campaign.commitments().plan()["revision"].Integer()==2,"revision did not change during battle");
            campaign.battleResult(ownResult());
            campaign.terminalResult(0,1,false);
            // Public callback drains the same queue as the worker.
            const auto & action=campaign.memory()["recent_results"].Vector().back()["action"];
            require(action["goal_id"].String().empty(),"unproved goal was assigned to a battle");
            if(mode<2) require(action["campaign_revision"].Integer()==1,"start revision replaced by end metadata");
            else require(action["campaign_revision"].isNull(),"restore gap inherited an unproved revision");
            for(const auto * field:{"battle_origin","own_side","battle_position","selected_route"})
                require(action[field].isNull(),"diagnostic field leaked into saved/model memory");
        }
        std::ifstream journal(argv[1]);std::string line;int executions=0;
        while(std::getline(journal,line))
        {
            const JsonNode event(line.data(),line.size(),"callback-journal");
            if(event["phase"].String()!="execution") continue;
            const auto & action=event["own_result"]["action"];
            require(action["battle_origin"].String()==(executions==0 ? "incoming_attack" : "unknown"),
                    "restored/interrupted battle without selected execution was attributed to native action");
            ++executions;
        }
        require(executions==3,"missing queued callback receipts");
        std::cout<<"callback snapshot, incoming attack, interruption and memory isolation passed\n";
    }
    catch(const std::exception & error) { std::cerr<<error.what()<<'\n';return 1; }
}
