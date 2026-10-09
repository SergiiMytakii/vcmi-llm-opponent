#include "Global.h"
#include "CampaignState.h"
#include <iostream>
#include <stdexcept>
JsonNode parse(const std::string & text) {
    JsonParsingSettings parser; parser.strict=true;parser.mode=JsonParsingSettings::JsonFormatMode::JSON;
    return JsonNode(text.data(),text.size(),parser,"decision waits proof");
}
void require(bool value,const char * why) { if(!value) throw std::runtime_error(why); }
int main() {
try {
    auto world=parse(R"({"day":1,"player":0,"resources":[0,0,0,0,0,0,10000],"capabilities":[],"heroes":[{"ref":"main","army_value":1000,"position":[1,1,0]},{"ref":"courier","army_value":5000,"position":[2,1,0]},{"ref":"guard","army_value":1000,"position":[1,1,0]}],"towns":[{"ref":"home","position":[1,1,0],"buildings":[],"building_options":[{"id":10,"supported":true}]}],"objects":[],"forecasts":{"routes":[]}})");
    auto plan=parse(R"({"version":3,"revision":1,"approach":"defense","horizon_days":7,"goals":[{"id":"wait","kind":"preserve_force","actor_ref":"main","target_ref":"home","deadline_day":7,"priority":80,"building_id":-1,"min_army_value":1000,"depends_on":[],"required_capabilities":[],"complete_when":{"kind":"force_preserved_until","value":7}},{"id":"build","kind":"develop_town","actor_ref":null,"target_ref":"home","deadline_day":7,"priority":70,"building_id":10,"min_army_value":0,"depends_on":[],"required_capabilities":[],"complete_when":{"kind":"building_present","value":10}},{"id":"defend","kind":"preserve_force","actor_ref":"main","target_ref":"home","deadline_day":7,"priority":60,"building_id":-1,"min_army_value":1000,"depends_on":[],"required_capabilities":[],"complete_when":{"kind":"force_preserved_until","value":7}},{"id":"delivery","kind":"reinforce_hero","actor_ref":"main","target_ref":"courier","deadline_day":7,"priority":50,"building_id":-1,"min_army_value":2000,"depends_on":[],"required_capabilities":[],"complete_when":{"kind":"army_at_least","value":2000}}],"reserves":[{"goal_id":"wait","resources":[0,0,0,0,0,0,1000],"force_value":1000},{"goal_id":"defend","resources":[0,0,0,0,0,0,1000],"force_value":1000}],"policy":{"max_loss_ratio":0.2,"allow_route_repair":true,"allow_helper_replacement":true,"critical_towns":[]}})");
    nullkiller3::CampaignState campaign;std::string reason;
    require(campaign.accept(plan,world,reason),reason.c_str());campaign.review(world,false);
    auto basis=parse(R"({"waits":[{"goal_id":"wait","purpose":"prepare","basis_goal_ids":["build"],"next_goal_id":null},{"goal_id":"defend","purpose":"safety","basis_goal_ids":["defend"],"next_goal_id":null}],"town_choices":[]})");
    world["towns"][0]["buildings"].Vector().emplace_back(10);world["day"].Integer()=2;
    campaign.review(world,false);
    const auto facts=campaign.observeDecisionBasis(basis,world);
    require(campaign.statuses()["wait"]["state"].String()=="cancelled","completed preparation did not release its specific hold");
    require(campaign.holdsCommitment("defend"),"independent same-hero safety hold lost");
    require(campaign.holdsCommitment("delivery"),"independent delivery lost");
    require(campaign.reservedResources()[6].Integer()==1000,"invalid wait reserve retained or live reserve erased");
    campaign.review(world,false);campaign.observeDecisionBasis(basis,world);
    require(campaign.statuses()["wait"]["state"].String()=="cancelled","safe pass resurrected cancelled wait");
    nullkiller3::CampaignState restored(campaign.save());
    require(!restored.plan().isNull() && restored.statuses()["wait"]["state"].String()=="cancelled","cancelled wait failed save restore");
    require(!facts.isNull(),"missing observable basis facts");
    // A model renumbering the same stalled delivery must not create progress.
    nullkiller3::CampaignState previous;require(previous.accept(plan,parse(R"({"day":1,"player":0,"resources":[0,0,0,0,0,0,10000],"capabilities":[],"heroes":[{"ref":"main","army_value":1000,"position":[1,1,0]},{"ref":"courier","army_value":5000,"position":[2,1,0]}],"towns":[{"ref":"home","position":[1,1,0],"buildings":[],"building_options":[{"id":10,"supported":true}]}],"objects":[],"forecasts":{"routes":[]}})"),reason),reason.c_str());
    auto extended=plan;extended["revision"].Integer()=2;
    extended["goals"][3]["id"].String()="renamed_delivery";extended["goals"][3]["deadline_day"].Integer()=9;
    auto stalled=world;stalled["day"].Integer()=3;
    stalled["accepted_decision_basis"]=parse(R"({"waits":[{"goal_id":"wait","purpose":"prepare","basis_goal_ids":["delivery"],"next_goal_id":null}],"town_choices":[]})");
    stalled["operation_progress"]["delivery"]["last_progress_day"].Integer()=1;
    stalled["operation_progress"]["delivery"]["last_no_change_day"].Integer()=2;
    require(!previous.accept(extended,stalled,reason) && reason=="preparation_extended_without_progress","cosmetic ID/deadline reset extended stalled preparation");
    stalled["operation_progress"]["delivery"]["last_progress_day"].Integer()=3;
    require(previous.accept(extended,stalled,reason),"real participant progress could not support continuation");
    auto garrisonWorld=world;garrisonWorld["towns"][0]["buildings"].Vector().clear();
    auto garrisonPlan=plan;garrisonPlan["goals"].Vector().resize(2);garrisonPlan["reserves"].Vector().clear();
    auto & garrison=garrisonPlan["goals"][0];garrison["id"].String()="garrison";
    garrison["kind"].String()="prepare_garrison";garrison["garrison_mode"].String()="recruit";
    garrison["complete_when"]["kind"].String()="garrison_at_least";garrison["complete_when"]["value"].Integer()=3000;
    garrison["depends_on"].Vector().emplace_back("build");
    nullkiller3::CampaignState stationed;require(stationed.accept(garrisonPlan,garrisonWorld,reason),reason.c_str());
    stationed.review(garrisonWorld,false);
    auto garrisonBasis=parse(R"({"waits":[{"goal_id":"garrison","purpose":"prepare","basis_goal_ids":["build"],"next_goal_id":null}],"town_choices":[]})");
    stationed.observeDecisionBasis(garrisonBasis,garrisonWorld);
    require(stationed.statuses()["garrison"]["reason"].String()=="dependency_failed","invalid dependent wait was not failed");
    require(stationed.reservedForce("home",garrisonWorld)==0,"failed garrison wait retained town force reserve");
    stationed.review(garrisonWorld,false);
    require(!stationed.holdsCommitment("garrison"),"safe pass restored failed dependency wait");
    // Completed dependencies enable the named next operation; only explicit
    // stationary holds end with their preparation event.
    nullkiller3::CampaignState enabled;require(enabled.accept(garrisonPlan,garrisonWorld,reason),reason.c_str());
    auto prepared=garrisonWorld;prepared["towns"][0]["buildings"].Vector().emplace_back(10);
    enabled.review(prepared,false);
    require(enabled.statuses()["garrison"]["state"].String()=="ready","completed building did not enable operation");
    enabled.observeDecisionBasis(garrisonBasis,prepared);
    require(enabled.statuses()["garrison"]["state"].String()=="ready","successful dependency was marked failed");
    enabled.review(prepared,false);
    require(enabled.statuses()["garrison"]["state"].String()=="ready","enabled operation failed next safe review");
    auto construction=plan;construction["goals"].Vector().erase(construction["goals"].Vector().begin());
    construction["goals"].Vector().resize(1);construction["reserves"].Vector().clear();
    auto early=garrisonWorld;early["day"].Integer()=1;
    early["daily_income"]=parse("[0,0,0,0,0,0,1000]");
    early["towns"][0]["building_options"][0]["cost"]=parse("[0,0,0,0,0,0,15000]");
    nullkiller3::CampaignState constructionOwner;require(constructionOwner.accept(construction,early,reason),reason.c_str());
    constructionOwner.review(early,false);
    const auto initialProgress=constructionOwner.observeBuildingProgress(JsonNode(),early);
    auto expired=early;expired["day"].Integer()=8;expired["resources"][6].Integer()=17000;
    constructionOwner.review(expired,false);
    const auto expiredProgress=constructionOwner.observeBuildingProgress(initialProgress,expired);
    require(!expiredProgress["home:10"].isNull(),"expired unfinished building lost its history");
    require(expiredProgress["home:10"]["last_progress_day"].Integer()==1,"routine income reset building progress");
    auto extension=construction;extension["revision"].Integer()=2;
    extension["goals"][0]["id"].String()="renamed_build";extension["goals"][0]["deadline_day"].Integer()=10;
    expired["building_progress"]=expiredProgress;
    expired["accepted_decision_basis"]=parse(R"({"waits":[{"goal_id":"operation","purpose":"prepare","basis_goal_ids":["build"],"next_goal_id":null}],"town_choices":[]})");
    require(!constructionOwner.accept(extension,expired,reason) && reason=="preparation_extended_without_progress","expired unchanged building was extended through renamed ID");
    // New funding changes this event only while ordinary income still leaves
    // a real deficit: day 3 ordinary gold is 12000 against a 15000 cost.
    auto recoveredFunding=expired;recoveredFunding["day"].Integer()=3;recoveredFunding["resources"][6].Integer()=40000;
    recoveredFunding["building_progress"]=constructionOwner.observeBuildingProgress(initialProgress,recoveredFunding);
    require(recoveredFunding["building_progress"]["home:10"]["last_progress_day"].Integer()==3,"material funding did not restore preparation evidence");
    require(constructionOwner.accept(extension,recoveredFunding,reason),"material funded recovery could not continue preparation");
    // A lost source preserves history; a fresh owned source can justify a
    // continuation without manufacturing construction progress while lost.
    auto missingSource=expired;missingSource["towns"].Vector().clear();
    constructionOwner.review(missingSource,false);
    const auto lostProgress=constructionOwner.observeBuildingProgress(recoveredFunding["building_progress"],missingSource);
    require(!lostProgress["home:10"].isNull() && !lostProgress["home:10"]["support"]["owned"].Bool(),"lost source erased preparation history");
    auto recoveredSource=expired;recoveredSource["day"].Integer()=9;
    constructionOwner.review(recoveredSource,false);
    const auto foundProgress=constructionOwner.observeBuildingProgress(lostProgress,recoveredSource);
    require(foundProgress["home:10"]["last_progress_day"].Integer()==9,"recovered owned source did not provide new evidence");
    // A gold-only event cannot acquire progress from an unrelated wood pickup
    // or wood mine while ordinary gold income crosses its affordability floor.
    auto incomeStart=early;incomeStart["daily_income"][6].Integer()=2500;
    nullkiller3::CampaignState resourceOwner;require(resourceOwner.accept(construction,incomeStart,reason),reason.c_str());
    resourceOwner.review(incomeStart,false);
    const auto incomeProgress=resourceOwner.observeBuildingProgress(JsonNode(),incomeStart);
    auto ordinaryGold=incomeStart;ordinaryGold["day"].Integer()=3;
    ordinaryGold["resources"][6].Integer()=15000;ordinaryGold["resources"][0].Integer()=1;
    resourceOwner.review(ordinaryGold,false);
    ordinaryGold["building_progress"]=resourceOwner.observeBuildingProgress(incomeProgress,ordinaryGold);
    require(ordinaryGold["building_progress"]["home:10"]["last_progress_day"].Integer()==1,"unrelated wood pickup reset gold-only preparation");
    ordinaryGold["accepted_decision_basis"]=expired["accepted_decision_basis"];
    require(!resourceOwner.accept(extension,ordinaryGold,reason) && reason=="preparation_extended_without_progress","unrelated wood enabled cosmetic gold deadline extension");
    auto extraGold=ordinaryGold;extraGold["resources"][0].Integer()=0;extraGold["resources"][6].Integer()=15001;
    extraGold["building_progress"]=resourceOwner.observeBuildingProgress(incomeProgress,extraGold);
    require(extraGold["building_progress"]["home:10"]["last_progress_day"].Integer()==1,"unneeded extra gold reset preparation already funded by ordinary income");
    require(!resourceOwner.accept(extension,extraGold,reason) && reason=="preparation_extended_without_progress","unneeded extra gold enabled cosmetic deadline extension");
    auto woodIncome=ordinaryGold;woodIncome["daily_income"][0].Integer()=1;
    woodIncome["building_progress"]=resourceOwner.observeBuildingProgress(incomeProgress,woodIncome);
    require(woodIncome["building_progress"]["home:10"]["last_progress_day"].Integer()==1,"unrelated wood income reset gold-only preparation");
    require(!resourceOwner.accept(extension,woodIncome,reason) && reason=="preparation_extended_without_progress","unrelated wood income enabled cosmetic gold deadline extension");
    auto goldIncome=ordinaryGold;goldIncome["daily_income"][6].Integer()=3000;
    goldIncome["building_progress"]=resourceOwner.observeBuildingProgress(incomeProgress,goldIncome);
    require(goldIncome["building_progress"]["home:10"]["last_progress_day"].Integer()==3,"relevant gold income did not provide new source evidence");
    require(resourceOwner.accept(extension,goldIncome,reason),"relevant gold income could not support continuation");
    std::cout<<"Completed preparation releases exact hold; independent safety/delivery and save restore survive\n";
    return 0;
} catch(const std::exception & e) { std::cerr<<e.what()<<'\n';return 1; }
}
