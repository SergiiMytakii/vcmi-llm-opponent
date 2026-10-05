#include "Global.h"
#include "StrategicDecision.h"
#include <iostream>
#include <stdexcept>
JsonNode json(const std::string & value)
{
    JsonParsingSettings parser;parser.strict=true;parser.mode=JsonParsingSettings::JsonFormatMode::JSON;
    return JsonNode(value.data(),value.size(),parser,"NK3 idle route proof");
}
void require(bool value,const char * message) { if(!value) throw std::runtime_error(message); }
void lastCreatureDelivery()
{
    auto world=json(R"({"day":6,"days_in_week":7,"player":1,"resources":[0,0,0,0,0,0,0],"daily_income":[0,0,0,0,0,0,0],"capabilities":["land","transfer"],"heroes":[{"ref":"main","army_value":8190,"army_units":[{"creature":14,"count":1,"unit_value":8190}]},{"ref":"courier","army_value":107,"minimum_retained_army_value":107,"army_units":[{"creature":14,"count":1,"unit_value":107}]}],"towns":[{"ref":"home","army_holder_ref":"courier","defense_value":107}],"forecasts":{"routes":[{"target_ref":"main","own_arrivals":[{"hero_ref":"courier","day":7,"army_value":107,"army_loss_estimate":0}]}]}})");
    auto plan=json(R"({"version":3,"revision":1,"approach":"economy","horizon_days":3,"goals":[{"id":"deliver","kind":"reinforce_hero","actor_ref":"main","target_ref":"courier","deadline_day":7,"priority":100,"building_id":-1,"min_army_value":8297,"depends_on":[],"required_capabilities":["land","transfer"],"complete_when":{"kind":"army_at_least","value":8297}}],"reserves":[],"policy":{"max_loss_ratio":0.25,"allow_route_repair":true,"allow_helper_replacement":true,"critical_towns":[]}})");
    nullkiller3::CampaignState campaign;std::string reason;
    require(campaign.accept(plan,world,reason),reason.c_str());
    auto logistics=nullkiller3::forecastCommitments(world,campaign);
    require(logistics["deliveries"][0]["source_floor"].Integer()==107
        && logistics["deliveries"][0]["recipient_possible_value"].Integer()==8190,
        "forecast promised the courier's last creature as reinforcement");
    require(!nullkiller3::supportedDeliveryWait(logistics,plan["goals"][0],6),
        "impossible last-creature delivery suppressed idle-army review");
    world["forecasts"]["army_pools"]=logistics["army_pools"];
    require(nullkiller3::reinforcementSources(JsonNode("main"),world).Vector().empty(),
        "last-creature hero or its town alias offered nonexistent surplus");
    world["heroes"][1]["army_value"].Integer()=214;
    world["heroes"][1]["army_units"][0]["count"].Integer()=2;
    logistics=nullkiller3::forecastCommitments(world,campaign);
    require(logistics["deliveries"][0]["recipient_possible_value"].Integer()==8297
        && nullkiller3::supportedDeliveryWait(logistics,plan["goals"][0],6),
        "retaining one creature prevented delivery of a genuine surplus");
}
void wholeCreatureDelivery()
{
    auto world=json(R"({"day":6,"days_in_week":7,"player":1,"resources":[0,0,0,0,0,0,0],"daily_income":[0,0,0,0,0,0,0],"capabilities":["land","transfer"],"heroes":[{"ref":"main","army_value":25576,"army_units":[{"creature":14,"count":1,"unit_value":25576}]},{"ref":"courier","army_value":1596,"minimum_retained_army_value":532,"army_units":[{"creature":22,"count":3,"unit_value":532}]}],"towns":[{"ref":"home","army_holder_ref":"courier","defense_value":1596}],"forecasts":{"routes":[{"target_ref":"main","own_arrivals":[{"hero_ref":"courier","day":7,"army_value":1596,"army_loss_estimate":0}]},{"target_ref":"home","own_arrivals":[{"hero_ref":"main","day":7,"army_value":25576,"army_loss_estimate":0}]}]}})");
    auto plan=json(R"({"version":3,"revision":1,"approach":"economy","horizon_days":3,"goals":[{"id":"deliver","kind":"reinforce_hero","actor_ref":"main","target_ref":"courier","deadline_day":7,"priority":100,"building_id":-1,"min_army_value":25744,"depends_on":[],"required_capabilities":["land","transfer"],"complete_when":{"kind":"army_at_least","value":25744}},{"id":"hold","kind":"preserve_force","actor_ref":"courier","target_ref":"home","deadline_day":7,"priority":90,"building_id":-1,"min_army_value":1428,"depends_on":[],"required_capabilities":["land"],"complete_when":{"kind":"force_preserved_until","value":7}}],"reserves":[{"goal_id":"hold","resources":[0,0,0,0,0,0,0],"force_value":1428}],"policy":{"max_loss_ratio":0.25,"allow_route_repair":true,"allow_helper_replacement":true,"critical_towns":[]}})");
    std::string reason;
    for(const auto & source:{"courier","home"})
    {
        plan["goals"][0]["target_ref"].String()=source;
        nullkiller3::CampaignState campaign;
        require(campaign.accept(plan,world,reason),reason.c_str());
        auto logistics=nullkiller3::forecastCommitments(world,campaign);
        require(logistics["deliveries"][0]["recipient_possible_value"].Integer()==25576
            && !nullkiller3::supportedDeliveryWait(logistics,plan["goals"][0],6),
            "three pegasi promised an impossible 168-value fractional donation");
        world["forecasts"]["army_pools"]=logistics["army_pools"];
        require(nullkiller3::reinforcementSources(JsonNode("main"),world).Vector().empty(),
            "hero or town alias offered a fractional creature as surplus");
    }
    plan["goals"][0]["target_ref"].String()="courier";
    plan["goals"][1]["min_army_value"].Integer()=1000;
    plan["reserves"][0]["force_value"].Integer()=1000;
    nullkiller3::CampaignState affordable;
    require(affordable.accept(plan,world,reason),reason.c_str());
    auto logistics=nullkiller3::forecastCommitments(world,affordable);
    require(logistics["deliveries"][0]["recipient_possible_value"].Integer()==26108
        && nullkiller3::supportedDeliveryWait(logistics,plan["goals"][0],6),
        "a legal whole-pegasus donation was lost or rounded upward");
}
void reservedPackingDelivery()
{
    auto world=json(R"({"day":19,"days_in_week":7,"player":1,"resources":[0,0,0,0,0,0,0],"daily_income":[0,0,0,0,0,0,0],"capabilities":["land","transfer"],"heroes":[{"ref":"main","army_value":28762,"army_units":[{"creature":14,"count":102,"unit_value":107},{"creature":18,"count":22,"unit_value":241},{"creature":16,"count":29,"unit_value":135},{"creature":28,"count":16,"unit_value":46},{"creature":30,"count":2,"unit_value":177},{"creature":19,"count":13,"unit_value":335},{"creature":24,"count":2,"unit_value":1593}]},{"ref":"courier","army_value":4006,"minimum_retained_army_value":482,"army_units":[{"creature":20,"count":5,"unit_value":482},{"creature":22,"count":3,"unit_value":532}]}],"towns":[{"ref":"home","army_holder_ref":"courier","defense_value":4006}],"forecasts":{"routes":[{"target_ref":"main","own_arrivals":[{"hero_ref":"courier","day":20,"army_value":4006,"army_loss_estimate":0}]}]}})");
    auto plan=json(R"({"version":3,"revision":1,"approach":"economy","horizon_days":3,"goals":[{"id":"deliver","kind":"reinforce_hero","actor_ref":"main","target_ref":"courier","deadline_day":20,"priority":100,"building_id":-1,"min_army_value":31322,"depends_on":[],"required_capabilities":["land","transfer"],"complete_when":{"kind":"army_at_least","value":31322}},{"id":"hold","kind":"preserve_force","actor_ref":"courier","target_ref":"home","deadline_day":21,"priority":90,"building_id":-1,"min_army_value":1428,"depends_on":[],"required_capabilities":["land"],"complete_when":{"kind":"force_preserved_until","value":21}}],"reserves":[{"goal_id":"hold","resources":[0,0,0,0,0,0,0],"force_value":1428}],"policy":{"max_loss_ratio":0.25,"allow_route_repair":true,"allow_helper_replacement":true,"critical_towns":[]}})");
    nullkiller3::CampaignState campaign;std::string reason;
    require(campaign.accept(plan,world,reason),reason.c_str());
    const auto logistics=nullkiller3::forecastCommitments(world,campaign);
    require(logistics["deliveries"][0]["recipient_possible_value"].Integer()==28762
        && !nullkiller3::supportedDeliveryWait(logistics,plan["goals"][0],19),
        "reserved delivery promised two new creature types into seven occupied recipient slots");
    world["forecasts"]["army_pools"]=logistics["army_pools"];
    require(nullkiller3::reinforcementSources(JsonNode("main"),world).Vector().empty(),
        "full recipient was offered incompatible reserved donor stacks");
    // One free slot: native tries source slot20 before22, so five dendroids
    // (2410), not a different 2560-valued selection, fit this exchange.
    world["heroes"][0]["army_units"].Vector().pop_back();
    world["heroes"][0]["army_value"].Integer()=25576;
    plan["goals"][0]["min_army_value"].Integer()=27986;
    plan["goals"][0]["complete_when"]["value"].Integer()=27986;
    nullkiller3::CampaignState freeSlot;
    require(freeSlot.accept(plan,world,reason),reason.c_str());
    const auto fitting=nullkiller3::forecastCommitments(world,freeSlot);
    require(fitting["deliveries"][0]["recipient_possible_value"].Integer()==27986
        && nullkiller3::supportedDeliveryWait(fitting,plan["goals"][0],19),
        "one free slot failed to receive the native first whole stack");
    // A full army can still merge the donor's Pegasus into its Pegasus slot.
    world["heroes"][0]["army_units"].Vector().push_back(json(R"({"creature":22,"count":2,"unit_value":532})"));
    world["heroes"][0]["army_value"].Integer()=26640;
    nullkiller3::CampaignState matching;
    require(matching.accept(plan,world,reason),reason.c_str());
    const auto merged=nullkiller3::forecastCommitments(world,matching);
    require(merged["deliveries"][0]["recipient_possible_value"].Integer()==28236
        && nullkiller3::supportedDeliveryWait(merged,plan["goals"][0],19),
        "full recipient could not merge an existing creature type");
}
void blockedScoutingReview()
{
    auto world=json(R"({"day":22,"player":1,"resources":[23,14,27,0,7,10,20285],"capabilities":["land"],"heroes":[{"ref":"main","army_value":19605,"movement":1500,"movement_per_day":1500,"position":[0,0,0]}],"towns":[],"objects":[],"frontiers":["south","west"],"frontier_options":[{"ref":"south","own_arrivals":[{"hero_ref":"main","day":24,"army_value":19605,"army_loss_estimate":11785}]},{"ref":"west","own_arrivals":[{"hero_ref":"main","day":24,"army_value":19605,"army_loss_estimate":5028}]}]})");
    auto plan=json(R"({"version":3,"revision":1,"approach":"scouting","horizon_days":3,"goals":[{"id":"scout","kind":"scout_frontier","actor_ref":"main","target_ref":"south","deadline_day":24,"priority":100,"building_id":-1,"min_army_value":19605,"depends_on":[],"required_capabilities":["land"],"complete_when":{"kind":"frontier_observed","value":0}}],"reserves":[],"policy":{"max_loss_ratio":0.28,"allow_route_repair":true,"allow_helper_replacement":true,"critical_towns":[]}})");
    world["heroes"].Vector().push_back(json(R"({"ref":"defender","army_value":5000,"movement":1500,"movement_per_day":1500,"position":[5,5,0]})"));
    world["towns"].Vector().push_back(json(R"({"ref":"home","position":[5,5,0],"army_holder_ref":"defender","defense_value":5000,"buildings":[],"building_options":[{"id":11,"supported":true}]})"));
    world["capabilities"].Vector().emplace_back("build");
    plan["goals"].Vector().push_back(json(R"({"id":"hold","kind":"defend_area","actor_ref":"defender","target_ref":"home","deadline_day":24,"priority":70,"building_id":-1,"min_army_value":4000,"depends_on":[],"required_capabilities":["land"],"complete_when":{"kind":"held_until","value":24}})"));
    plan["goals"].Vector().push_back(json(R"({"id":"develop","kind":"develop_town","actor_ref":null,"target_ref":"home","deadline_day":24,"priority":60,"building_id":11,"min_army_value":0,"depends_on":[],"required_capabilities":["build"],"complete_when":{"kind":"building_present","value":11}})"));
    nullkiller3::CampaignState campaign;std::string reason;
    require(campaign.accept(plan,world,reason),reason.c_str());
    world["goal_statuses"]=campaign.review(world);
    world["offensive_preparation"]=nullkiller3::offensivePreparation(campaign,world);
    require(nullkiller3::mainArmyIdle(campaign,world)["reason"].String()=="no_safe_route","unsafe scouting was not identified");
    require(nullkiller3::idleArmyNeedsReview(nullkiller3::mainArmyIdle(campaign,world)),"turn-end review ignored the blocked route");
    nullkiller3::RequestArbiter arbiter;arbiter.beginTurn(22,{280000,120000,40000});
    const auto signals=nullkiller3::idleArmySignals(campaign,world,true);
    const auto decision=arbiter.consider(signals);
    require(decision.request,"blocked scouting ended the turn without corrective review");
    require(campaign.statuses()["hold"]["state"].String()=="ready"
        && campaign.statuses()["develop"]["state"].String()=="ready","blocked scouting cancelled independent defense or development");
    arbiter.dispatched(decision);arbiter.finished(24000,44000);
    require(!arbiter.consider(signals).request,"identical idle failure was retried");
    auto renamed=plan;renamed["revision"].Integer()=2;renamed["goals"][0]["id"].String()="renamed";
    require(campaign.accept(renamed,world,reason),reason.c_str());
    world["goal_statuses"]=campaign.review(world);world["offensive_preparation"]=nullkiller3::offensivePreparation(campaign,world);
    require(!arbiter.consider(nullkiller3::idleArmySignals(campaign,world,true)).request,"renaming the same blocked scout created new idle evidence");
    const auto preparation=nullkiller3::offensivePreparation(campaign,world);
    const auto & unsafe=preparation["frontiers"][0]["route_feedback"][0];
    require(unsafe["actor_ref"].String()=="main" && !unsafe["supported"].Bool(),"frontier advice omitted the unsafe executor");
    require(unsafe["assigned_routes"][0]["estimated_loss_percent"].Float()>60
        && std::abs(unsafe["assigned_routes"][0]["allowed_loss_percent"].Float()-28)<0.001
        && unsafe["assigned_routes"][0]["issues"][0].String()=="loss_exceeds_policy",
        "frontier advice hid the 60 percent loss-policy failure");
    require(preparation["frontiers"][1]["route_feedback"][0]["supported"].Bool(),"frontier advice omitted the safe alternative");
    require(preparation["frontiers"][0]["route_feedback"].Vector().size()==2
        && preparation["frontiers"][0]["route_feedback"][1]["actor_ref"].String()=="defender"
        && !preparation["frontiers"][0]["route_feedback"][1]["supported"].Bool(),"frontier advice invented a missing helper route");
    renamed["revision"].Integer()=3;renamed["goals"][0]["target_ref"].String()="west";
    require(campaign.accept(renamed,world,reason),reason.c_str());
    require(campaign.statuses()["renamed"]["state"].String()=="ready","corrected 25.6 percent route remained blocked");
    world["goal_statuses"]=campaign.statuses();world["offensive_preparation"]=nullkiller3::offensivePreparation(campaign,world);
    require(nullkiller3::idleArmySignals(campaign,world,true).empty(),"ready operation requested another idle correction");
    campaign.blocked("renamed","hero_required_for_defense");world["goal_statuses"]=campaign.statuses();
    const auto refused=nullkiller3::mainArmyIdle(campaign,world);
    require(refused["reason"].String()=="execution_blocked" && nullkiller3::idleArmyNeedsReview(refused)
        && arbiter.consider(nullkiller3::idleArmySignals(campaign,world,true)).request,"native execution refusal did not create corrective evidence");
    auto spent=world;spent["heroes"][0]["movement"].Integer()=0;
    spent["offensive_preparation"]=nullkiller3::offensivePreparation(campaign,spent);
    require(nullkiller3::idleArmySignals(campaign,spent,true).empty(),"spent movement requested idle correction");

    auto holding=plan;holding["revision"].Integer()=4;holding["goals"].Vector().resize(1);
    holding["goals"][0]=plan["goals"][1];holding["goals"][0]["actor_ref"].String()="main";
    auto stationed=world;stationed["heroes"][0]["position"]=stationed["towns"][0]["position"];
    require(campaign.accept(holding,stationed,reason),reason.c_str());
    stationed["goal_statuses"]=campaign.review(stationed);stationed["offensive_preparation"]=nullkiller3::offensivePreparation(campaign,stationed);
    require(nullkiller3::mainArmyIdle(campaign,stationed)["reason"].String()=="defense"
        && nullkiller3::idleArmySignals(campaign,stationed,true).empty(),"concrete defense was treated as unexplained idle");
    holding["revision"].Integer()=5;
    auto & delivery=holding["goals"][0];delivery["id"].String()="supply";delivery["kind"].String()="reinforce_hero";
    delivery["min_army_value"].Integer()=25000;delivery["complete_when"]=json(R"({"kind":"army_at_least","value":25000})");
    stationed["forecasts"]["deliveries"].Vector().push_back(json(R"({"goal_id":"supply","status":"conditional","arrival_day":23})"));
    require(campaign.accept(holding,stationed,reason),reason.c_str());
    stationed["goal_statuses"]=campaign.review(stationed);stationed["offensive_preparation"]=nullkiller3::offensivePreparation(campaign,stationed);
    require(nullkiller3::mainArmyIdle(campaign,stationed)["reason"].String()=="waiting_delivery"
        && nullkiller3::idleArmySignals(campaign,stationed,true).empty(),"supported reinforcement wait requested idle correction");
}
int main()
{
    try { lastCreatureDelivery();wholeCreatureDelivery();reservedPackingDelivery();blockedScoutingReview();std::cout<<"Blocked scouting corrected; repeat suppressed; frontier constraints exposed\n"; }
    catch(const std::exception & error) { std::cerr<<error.what()<<"\n";return 1; }
}
