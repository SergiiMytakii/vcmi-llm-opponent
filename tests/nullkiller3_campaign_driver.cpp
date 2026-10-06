#include "Global.h"
#include "CampaignState.h"
#include "StrategicDecision.h"
#include "StrategicCandidates.h"
#include "Forecasts.h"
#include "NativePersistence.h"
#include "ResourceLedger.h"
#include "ReturnedHeroRecovery.h"
#include "../engine/ExternalAI/LocalState.h"
#include <iostream>
#include <stdexcept>
#include <iterator>
JsonNode json(const std::string & value)
{
    JsonParsingSettings parser;
    parser.strict = true;
    parser.mode = JsonParsingSettings::JsonFormatMode::JSON;
    return JsonNode(value.data(), value.size(), parser, "NK3 campaign proof");
}
void require(bool value, const char * message) { if(!value) throw std::runtime_error(message); }
int main(int argc,char ** argv)
{
    try
    {
        if(argc==2 && std::string(argv[1])=="--delivery")
        {
            auto world=json(R"({"day":1,"player":0,"resources":[10,0,10,0,0,0,10000],"capabilities":["land","build","transfer"],"heroes":[{"ref":"main","army_value":5000},{"ref":"courier","army_value":2000}],"towns":[{"ref":"home","buildings":[],"building_options":[{"id":0,"supported":true}]}],"objects":[]})");
            auto plan=json(R"({"version":3,"revision":1,"approach":"offense","horizon_days":5,"goals":[{"id":"deliver","kind":"reinforce_hero","actor_ref":"main","target_ref":"courier","deadline_day":6,"priority":80,"building_id":-1,"min_army_value":5500,"depends_on":[],"required_capabilities":["land","transfer"],"complete_when":{"kind":"army_at_least","value":5500}},{"id":"develop","kind":"develop_town","actor_ref":null,"target_ref":"home","deadline_day":6,"priority":50,"building_id":0,"min_army_value":0,"depends_on":["deliver"],"required_capabilities":["build"],"complete_when":{"kind":"building_present","value":0}}],"reserves":[],"policy":{"max_loss_ratio":0.2,"allow_route_repair":true,"allow_helper_replacement":false,"critical_towns":[]}})");
            std::string reason;
            nullkiller3::CampaignState campaign;
            require(campaign.accept(plan,world,reason),reason.c_str());
            require(campaign.review(world,false)["develop"]["reason"].String()=="dependency_unconfirmed","delivery dependency opened before receipt");
            require(campaign.exchangeForce("main",world)==5000 && campaign.exchangeForce("courier",world)==500,"exchange floors changed");
            auto grown=world;grown["heroes"][0]["army_value"].Integer()=5500;
            JsonNode receipt;receipt["goal"]=plan["goals"][0];receipt["source_ref"].String()="courier";
            receipt["day"].Integer()=1;receipt["recipient_after"].Integer()=5500;
            auto rejects=[&](const JsonNode & invalid) {
                nullkiller3::CampaignState trial;require(trial.accept(plan,world,reason),reason.c_str());
                auto observed=grown;observed["confirmed_deliveries"].Vector().push_back(invalid);
                trial.review(observed,false);
                require(trial.statuses()["deliver"]["state"].String()!="completed","invalid receipt completed delivery");
                require(trial.statuses()["develop"]["reason"].String()=="dependency_unconfirmed","invalid receipt unlocked dependency");
            };
            rejects(JsonNode()); // Army growth/recruitment is not a handoff.
            for(const auto * field:{"source_ref","day","recipient_after"})
            {auto bad=receipt;bad.Struct().erase(field);rejects(bad);bad=receipt;bad[field].String()="invalid";rejects(bad);}
            for(const auto value:{0,7}) {auto bad=receipt;bad["day"].Integer()=value;rejects(bad);}
            for(const auto value:{5499LL,1000000001LL}) {auto bad=receipt;bad["recipient_after"].Integer()=value;rejects(bad);}
            auto bad=receipt;bad["source_ref"].String()="other";rejects(bad);
            for(const auto * field:{"actor_ref","target_ref","required_capabilities","complete_when","priority"})
            {bad=receipt;bad["goal"][field]=JsonNode();rejects(bad);}
            bad=receipt;bad["goal"]["id"].String()="other";rejects(bad);
            auto observed=grown;observed["confirmed_deliveries"].Vector().push_back(receipt);
            campaign.review(observed,false);
            require(campaign.statuses()["deliver"]["state"].String()=="completed" && campaign.statuses()["develop"]["state"].String()=="ready","exact receipt did not complete delivery and open dependency");
            auto saved=json(campaign.save().toCompactString());
            nullkiller3::CampaignState restored(saved);
            require(restored.restoreReason().empty(),restored.restoreReason().c_str());
            require(restored.review(grown,false)["deliver"]["state"].String()=="completed","load repeated handoff");
            require(restored.statuses()["develop"]["state"].String()=="ready","load lost open dependency");
            require(restored.save()["delivery_completions"]["deliver"]==receipt,"load lost exact delivery receipt");
            auto revision=plan;revision["revision"].Integer()=2;
            require(restored.accept(revision,grown,reason),reason.c_str());
            require(restored.statuses()["deliver"]["state"].String()=="completed","same goal revision replayed delivery");
            for(const auto * field:{"source_ref","day","recipient_after","goal"})
            {auto forged=saved;forged["delivery_completions"]["deliver"].Struct().erase(field);require(!nullkiller3::CampaignState(forged).restoreReason().empty(),"invalid saved receipt restored");}
            plan["policy"]["allow_helper_replacement"].Bool()=true;
            nullkiller3::CampaignState replacement;require(replacement.accept(plan,world,reason),reason.c_str());
            observed["confirmed_deliveries"][0]["source_ref"].String()="replacement";
            require(replacement.review(observed,false)["deliver"]["state"].String()=="completed","policy-supported helper replacement rejected");
            std::cout<<"Exact delivery negatives, dependency, floors and restore passed\n";return 0;
        }
        if(argc==2 && std::string(argv[1])=="--returned-hero-newgame")
        {
            const auto untouched=nullkiller3::restoreOwnHeroReturns(nullkiller3::restoreNativeNamespace(JsonNode()),JsonNode());
            require(untouched.isNull(),"empty receipts manufactured saved namespace for a fresh game");
            const auto event=json(R"({"own_hero_type_id":42,"engine_object_id":73,"day":4,"won":false,"draw":false,"own_hero_return":"escape"})");
            const auto callback=nullkiller3::ownHeroReturnUpdate(event);
            const auto firstReturn=nullkiller3::restoreOwnHeroReturns(nullkiller3::restoreNativeNamespace(JsonNode()),callback["_namespaces"]);
            require(nullkiller3::isOwnReturnedHero(firstReturn["own_returned_heroes"],42,73),"return before first worker lost");
            require(firstReturn["request_arbiter"].isNull() && firstReturn["request_sequence"].isNull(),"fresh receipt changed default request budget");
            const auto invalid=nullkiller3::restoreNativeNamespace(json("1"));
            const auto retained=nullkiller3::restoreOwnHeroReturns(invalid,callback["_namespaces"]);
            require(retained["request_arbiter"]==invalid["request_arbiter"] && retained["request_arbiter"].String()=="invalid_saved_namespace",
                "receipt reset invalid consumed budget");
            std::cout << "returned hero newgame passed\n";return 0;
        }
        if(argc==2 && std::string(argv[1])=="--returned-hero-save")
        {
            auto settings=json(R"({"currentSelection":7,"_namespaces":{"Nullkiller3":{"object_ids":{},"native_campaign":{"revision":9,"reserves":[{"resources":[0,0,0,0,0,0,3000]}]},"memory":{"kept":true}},"ExternalAI":{"other":true}}})");
            const auto oldCampaign=settings["_namespaces"]["Nullkiller3"],oldOther=settings["_namespaces"]["ExternalAI"];
            const auto event=json(R"({"own_hero_type_id":42,"engine_object_id":73,"day":4,"won":false,"draw":false,"own_hero_return":"escape"})");
            auto enemyRetreat=event;enemyRetreat["won"].Bool()=true;
            require(nullkiller3::ownHeroReturnUpdate(enemyRetreat).isNull(),"enemy retreat published own return");
            auto notReturned=event;notReturned["own_hero_return"].String()="none";
            require(nullkiller3::ownHeroReturnUpdate(notReturned).isNull(),"non-return battle published return");
            require(externalai::applyLocalState(settings,nullkiller3::ownHeroReturnUpdate(event)),"callback return update rejected");
            require(settings["_namespaces"][nullkiller3::ownHeroReturnNamespace(42)].Struct().size()==6,"receipt contains mutable planner/resource fields");
            require(settings["_namespaces"]["Nullkiller3"]==oldCampaign && settings["_namespaces"]["ExternalAI"]==oldOther,
                "callback replaced unrelated planner state");
            externalai::applyLocalState(settings,json(R"({"currentSelection":8})"));
            const auto reload=json(settings.toCompactString());
            auto restored=nullkiller3::restoreOwnHeroReturns(reload["_namespaces"]["Nullkiller3"],reload["_namespaces"]);
            require(nullkiller3::isOwnReturnedHero(restored["own_returned_heroes"],42,73),"enemy-turn return lost before worker/save/reload");
            require(restored["native_campaign"]==oldCampaign["native_campaign"] && restored["memory"]==oldCampaign["memory"],"receipt merge erased planner state");
            auto normal=event;normal["own_hero_return"].String()="normal";
            externalai::applyLocalState(settings,nullkiller3::ownHeroReturnUpdate(normal));
            restored=nullkiller3::restoreOwnHeroReturns(restored,settings["_namespaces"]);
            require(!nullkiller3::isOwnReturnedHero(restored["own_returned_heroes"],42,73),"death receipt failed to clear return");
            externalai::applyLocalState(settings,nullkiller3::ownHeroReturnUpdate(event));
            restored=nullkiller3::restoreOwnHeroReturns(oldCampaign,settings["_namespaces"]);
            externalai::applyLocalState(settings,nullkiller3::consumedOwnHeroReturnUpdate(42));
            restored=nullkiller3::restoreOwnHeroReturns(restored,json(settings.toCompactString())["_namespaces"]);
            require(!nullkiller3::isOwnReturnedHero(restored["own_returned_heroes"],42,73),"successful hire tombstone replayed return");
            std::cout << "returned hero save passed\n";return 0;
        }
        if(argc==2 && std::string(argv[1])=="--returned-hero")
        {
            JsonNode markers;
            auto result=json(R"({"own_hero_type_id":42,"engine_object_id":73,"day":4,"won":false,"draw":false,"own_hero_return":"escape"})");
            nullkiller3::recordOwnHeroReturn(markers,result);
            require(nullkiller3::isOwnReturnedHero(markers,42,73),"own retreated hero not recoverable");
            require(!nullkiller3::isOwnReturnedHero(markers,42,74),"different offered instance treated as own");
            require(!nullkiller3::isOwnReturnedHero(markers,43,73),"random candidate treated as own");
            auto saved=json(markers.toCompactString());
            require(nullkiller3::restoreReturnedHeroes(saved)==markers,"return lost after save/reload");
            result["won"].Bool()=true;result["own_hero_type_id"].Integer()=43;
            nullkiller3::recordOwnHeroReturn(markers,result);
            require(!nullkiller3::isOwnReturnedHero(markers,43,73),"enemy retreat marked own winner");
            result["won"].Bool()=false;result["own_hero_type_id"].Integer()=42;result["own_hero_return"].String()="normal";
            nullkiller3::recordOwnHeroReturn(markers,result);
            require(!nullkiller3::isOwnReturnedHero(markers,42,73),"confirmed death retained recovery");
            result["own_hero_return"].String()="surrender";
            nullkiller3::recordOwnHeroReturn(markers,result);
            require(nullkiller3::isOwnReturnedHero(markers,42,73),"surrender not recoverable");
            markers["42"]["engine_object_id"].Integer()=-1;
            require(nullkiller3::restoreReturnedHeroes(markers).Struct().empty(),"malformed marker restored");
            const auto funds=json("[0,0,0,0,0,0,5000]"),locks=json("[0,0,0,0,0,0,1000]");
            require(!nullkiller3::recoveryFundsAvailable(funds,locks,json("[0,0,0,0,0,0,2000]"),2500),"recovery spent protected funds");
            require(nullkiller3::recoveryFundsAvailable(funds,locks,json("[0,0,0,0,0,0,1000]"),2500),"funded recovery blocked");
            std::cout << "returned hero recovery passed\n";return 0;
        }
        if(argc==2 && std::string(argv[1])=="--goal-risk")
        {
            auto world=json(R"({"day":4,"player":0,"resources":[0,0,0,0,0,0,10000],"capabilities":[],"heroes":[{"ref":"main","army_value":10000}],"towns":[],"objects":[{"ref":"enemy","kind":"hero","owner":1,"visible":true}],"enemy_players":[1]})");
            auto plan=json(R"({"version":3,"revision":1,"approach":"offense","horizon_days":3,"goals":[{"id":"decisive","kind":"intercept_hero","actor_ref":"main","target_ref":"enemy","deadline_day":7,"priority":90,"building_id":-1,"min_army_value":10000,"depends_on":[],"required_capabilities":[],"complete_when":{"kind":"enemy_engaged","value":0}}],"reserves":[],"policy":{"max_loss_ratio":0.25,"allow_route_repair":true,"allow_helper_replacement":true,"critical_towns":[]}})");
            nullkiller3::CampaignState legacy,grant;std::string reason;
            require(legacy.accept(plan,world,reason),reason.c_str());
            require(legacy.allowsLoss(std::string("decisive"),10000,2500),"legacy boundary rejected");
            require(!legacy.allowsLoss(std::string("decisive"),10000,5730),"legacy risk relaxed");
            auto completedWorld=world;
            JsonNode receipt;receipt["goal"]=plan["goals"][0];receipt["day"].Integer()=4;receipt["won"].Bool()=true;
            completedWorld["confirmed_interceptions"].Vector().push_back(receipt);
            legacy.review(completedWorld);
            require(legacy.statuses()["decisive"]["state"].String()=="completed","legacy receipt ignored");
            auto modern=plan;modern["revision"].Integer()=2;modern["goals"][0]["risk"]=JsonNode();
            completedWorld["objects"][0]["visible"].Bool()=false;
            require(legacy.accept(modern,completedWorld,reason),"explicit null discarded legacy receipt");
            require(legacy.statuses()["decisive"]["state"].String()=="completed","legacy completion reset");
            nullkiller3::CampaignState migrated(legacy.save());
            require(migrated.restoreReason().empty() && migrated.statuses()["decisive"]["state"].String()=="completed","modern-null receipt save failed");
            auto changed=modern;changed["revision"].Integer()=3;
            changed["goals"][0]["risk"]["max_loss_ratio"].Float()=.7;changed["goals"][0]["risk"]["reason"].String()="New risk operation";
            require(!legacy.accept(changed,completedWorld,reason),"different risk inherited hidden completion");
            auto & risk=plan["goals"][0]["risk"];risk["max_loss_ratio"].Float()=.7;
            risk["reason"].String()="Defeat the visible main force before securing its last base";
            require(grant.accept(plan,world,reason),reason.c_str());
            require(grant.allowsLoss(std::string("decisive"),10000,5730),"named grant ignored");
            for(const auto & id:{std::string(),std::string("other")})
                require(!grant.allowsLoss(id,10000,5730),"grant leaked to unrelated work");
            auto saved=grant.save();nullkiller3::CampaignState restored(saved);
            require(restored.restoreReason().empty(),"risk save restore failed");
            require(restored.allowsLoss(std::string("decisive"),10000,5730),"saved grant lost");
            plan["goals"][0]["risk"]["max_loss_ratio"].Float()=1;
            nullkiller3::CampaignState total;require(total.accept(plan,world,reason),reason.c_str());
            require(!total.allowsLoss(std::string("decisive"),10000,10000),"total destruction treated as victory");
            require(!total.allowsLoss(std::string("decisive"),10000,10001),"more than army accepted");
            for(const auto value:{-.1,1.1})
            {auto bad=plan;bad["goals"][0]["risk"]["max_loss_ratio"].Float()=value;nullkiller3::CampaignState rejected;
             require(!rejected.accept(bad,world,reason),"invalid grant accepted");}
            auto bad=plan;bad["goals"][0]["risk"]["reason"].String()="";
            nullkiller3::CampaignState rejected;require(!rejected.accept(bad,world,reason),"unjustified grant accepted");
            bad=plan;bad["policy"]["max_loss_ratio"].Float()=.7;
            require(!rejected.accept(bad,world,reason),"global ceiling raised");
            std::cout << "scoped goal risk and legacy save proof passed\n";return 0;
        }
        if(argc==2 && std::string(argv[1])=="--defense-exit")
        {
            auto world=json(R"({"day":4,"player":0,"resources":[0,0,0,0,0,0,10000],"capabilities":[],"heroes":[{"ref":"main","army_value":5000,"position":[1,1,0]}],"towns":[{"ref":"home","buildings":[],"position":[1,1,0]}],"objects":[]})");
            auto plan=json(R"({"version":3,"revision":1,"approach":"defense","horizon_days":3,"goals":[{"id":"hold","kind":"defend_area","actor_ref":"main","target_ref":"home","deadline_day":7,"priority":50,"building_id":-1,"min_army_value":5000,"depends_on":[],"required_capabilities":[],"complete_when":{"kind":"held_until","value":7}}],"reserves":[],"policy":{"max_loss_ratio":0.2,"allow_route_repair":true,"allow_helper_replacement":true,"critical_towns":[]}})");
            auto request=json(R"({"request_id":"fresh","identity":{"generation":"fresh"},"evidence_refs":["observation:day"],"campaign":null,"signals":[]})");
            auto reply=json(R"({"protocol":2,"request_id":"fresh","identity":{"generation":"fresh"},"decision":"revise","reason":"Wait for growth then reconsider offense","evidence_refs":["observation:day"],"victory_method":"Conquest","assignments":[{"hero_ref":"main","role":"defender"}],"alternatives":[{"approach":"defense","benefit":"Growth","cost":"Time","uncertainty":"Enemy"},{"approach":"offense","benefit":"Capture","cost":"Army","uncertainty":"Guard"}],"reconsider_when":[{"goal_id":"hold","kind":"deadline_missed"}],"plan":null,"usage":{"input_tokens":100,"output_tokens":20,"known":true}})");
            const auto exit=json(R"({"waiting_for":"Known next growth day","expected_gain":"Available troops after growth","next_step":"Reconsider the best supported route after growth"})");
            nullkiller3::CampaignState current,candidate;std::string reason;
            // The initial plan retains the ordinary closed response shape.
            reply["plan"]=plan;
            require(nullkiller3::validateStrategicDecision(reply,request,world,current,candidate,reason),reason.c_str());
            auto extra=reply;extra["defense_exit"]=exit;
            require(!nullkiller3::validateStrategicDecision(extra,request,world,current,candidate,reason),"unrequested exit shape accepted");
            for(const auto * kind:{"defend_area","preserve_force"})
                for(const auto * approach:{"defense","scouting","economy","expansion","offense"})
                    for(const auto * signal:{"campaign_exhausted","helper_hired:helper","battle_loss:helper",""})
                    {
                        auto previous=plan;previous["approach"].String()=approach;
                        previous["goals"][0]["kind"].String()=kind;
                        previous["goals"][0]["complete_when"]["kind"].String()=std::string(kind)=="preserve_force" ? "force_preserved_until" : "held_until";
                        current=nullkiller3::CampaignState();
                        require(current.accept(previous,world,reason),reason.c_str());
                        request["campaign"]=current.plan();request["signals"].Vector().clear();
                        if(*signal) { JsonNode event;event["question"].String()=signal;request["signals"].Vector().push_back(event); }
                        for(const auto * decision:{"revise","retain"})
                        {
                            reply["decision"].String()=decision;
                            reply["plan"]=std::string(decision)=="retain" ? JsonNode() : previous;
                            if(!reply["plan"].isNull()) reply["plan"]["revision"].Integer()=2;
                            reply.Struct().erase("defense_exit");
                            require(!nullkiller3::validateStrategicDecision(reply,request,world,current,candidate,reason)
                                && reason=="missing_defense_exit","previous hold accepted without concrete reconsideration");
                            reply["defense_exit"]=JsonNode();
                            require(!nullkiller3::validateStrategicDecision(reply,request,world,current,candidate,reason)
                                && reason=="missing_defense_exit","previous hold accepted null reconsideration");
                            reply["defense_exit"]=exit;
                            require(nullkiller3::validateStrategicDecision(reply,request,world,current,candidate,reason),reason.c_str());
                        }
                    }
            auto malformed=reply;malformed["defense_exit"]["next_step"].String()=std::string(641,'x');
            require(!nullkiller3::validateStrategicDecision(malformed,request,world,current,candidate,reason)
                && reason=="invalid_defense_exit","oversized exit accepted");
            malformed=reply;malformed["defense_exit"]["extra"].String()="unexpected";
            require(!nullkiller3::validateStrategicDecision(malformed,request,world,current,candidate,reason)
                && reason=="invalid_defense_exit","open exit shape accepted");
            malformed=reply;malformed["defense_exit"]["next_step"].String()="";
            require(!nullkiller3::validateStrategicDecision(malformed,request,world,current,candidate,reason)
                && reason=="invalid_defense_exit","empty exit step accepted");
            // Leaving the hold for movement is allowed with an explicit null.
            world["frontiers"].Vector().push_back(JsonNode(std::string("edge")));
            auto moving=plan;moving["revision"].Integer()=2;moving["approach"].String()="scouting";
            moving["goals"][0]["kind"].String()="scout_frontier";moving["goals"][0]["target_ref"].String()="edge";
            moving["goals"][0]["complete_when"]["kind"].String()="frontier_observed";moving["goals"][0]["complete_when"]["value"].Integer()=0;
            reply["decision"].String()="revise";reply["plan"]=moving;reply["defense_exit"]=JsonNode();
            require(nullkiller3::validateStrategicDecision(reply,request,world,current,candidate,reason),reason.c_str());
            reply.Struct().erase("defense_exit");
            require(!nullkiller3::validateStrategicDecision(reply,request,world,current,candidate,reason)
                && reason=="missing_defense_exit","moving revision omitted required nullable field");
            // A safe second-town hold still needs a concrete reason, even if the main hero moves.
            world["heroes"].Vector().push_back(json(R"({"ref":"helper","army_value":1000,"position":[2,2,0]})"));
            world["towns"].Vector().push_back(json(R"({"ref":"second","buildings":[],"position":[2,2,0]})"));
            auto mixed=moving;auto secondHold=plan["goals"][0];secondHold["id"].String()="second_hold";
            secondHold["actor_ref"].String()="helper";secondHold["target_ref"].String()="second";secondHold["min_army_value"].Integer()=1000;
            mixed["goals"].Vector().push_back(secondHold);
            reply["assignments"].Vector().push_back(json(R"({"hero_ref":"helper","role":"defender"})"));
            reply["plan"]=mixed;reply["defense_exit"]=JsonNode();
            require(!nullkiller3::validateStrategicDecision(reply,request,world,current,candidate,reason)
                && reason=="missing_defense_exit","safe second-town hold accepted null reconsideration");
            reply["defense_exit"]=exit;
            require(nullkiller3::validateStrategicDecision(reply,request,world,current,candidate,reason),reason.c_str());
            // A previous moving campaign does not introduce the exit field, including a new hold.
            current=nullkiller3::CampaignState();moving["revision"].Integer()=1;
            require(current.accept(moving,world,reason),reason.c_str());request["campaign"]=current.plan();
            reply.Struct().erase("defense_exit");reply["plan"]=plan;reply["plan"]["revision"].Integer()=2;
            require(nullkiller3::validateStrategicDecision(reply,request,world,current,candidate,reason),reason.c_str());
            reply["decision"].String()="retain";reply["plan"]=JsonNode();
            require(nullkiller3::validateStrategicDecision(reply,request,world,current,candidate,reason),reason.c_str());
            std::cout << "NK3 universal hold reconsideration, retain, safe multi-town, movement and initial-plan proof passed\n";return 0;
        }
        if(argc==2 && std::string(argv[1])=="--helper-hiring")
        {
            auto world=json(R"({"day":1,"player":0,"resources":[0,0,0,0,0,0,10000],"capabilities":["land"],"heroes":[{"ref":"main","army_value":5000,"hero_type_id":10}],"towns":[{"ref":"home","buildings":[],"hiring_options":[{"ref":"tavern:42","hero_type_id":42,"can_recruit":true,"cost":[0,0,0,0,0,0,2500]}]}],"objects":[{"ref":"gold","kind":"resource","visible":true,"owner":-1}],"frontiers":["edge"]})");
            auto plan=json(R"({"version":3,"revision":1,"approach":"economy","horizon_days":5,"goals":[{"id":"helper","kind":"hire_helper","actor_ref":null,"target_ref":"home","deadline_day":5,"priority":50,"building_id":-1,"min_army_value":0,"depends_on":[],"required_capabilities":[],"complete_when":{"kind":"helper_hired","value":0},"candidate_ref":"tavern:42","helper_role":"collector","job_ref":"gold"}],"reserves":[],"policy":{"max_loss_ratio":0.2,"allow_route_repair":true,"allow_helper_replacement":true,"critical_towns":[]}})");
            nullkiller3::CampaignState campaign;std::string reason;
            require(campaign.accept(plan,world,reason),reason.c_str());
            require(nullkiller3::requiredCandidateRefs(world,plan).count("gold"),"helper job screened out of strategic model copy");
            auto changed=plan;changed["goals"][0]["candidate_ref"].String()="tavern:99";
            require(!nullkiller3::CampaignState().accept(changed,world,reason),"unoffered candidate accepted");
            changed=plan;changed["goals"][0]["job_ref"].String()="hidden";
            require(!nullkiller3::CampaignState().accept(changed,world,reason),"unknown helper job accepted");
            changed=plan;changed["goals"][0]["helper_role"].String()="reinforcement";
            require(!nullkiller3::CampaignState().accept(changed,world,reason),"role incompatible with helper job accepted");
            auto poor=world;poor["resources"][6].Integer()=1000;
            require(!nullkiller3::CampaignState().accept(plan,poor,reason),"unfunded helper accepted");
            auto reserved=plan;reserved["reserves"].Vector().push_back(json(R"({"goal_id":"helper","resources":[0,0,0,0,0,0,2500],"force_value":0})"));
            require(nullkiller3::CampaignState().accept(reserved,world,reason),"hire own reserve not usable");
            auto unavailable=world;unavailable["towns"][0]["hiring_options"][0]["can_recruit"].Bool()=false;
            require(!nullkiller3::CampaignState().accept(plan,unavailable,reason),"currently unavailable hire accepted");
            changed=plan;changed["goals"].Vector().push_back(changed["goals"][0]);changed["goals"][1]["id"].String()="duplicate";
            require(!nullkiller3::CampaignState().accept(changed,world,reason),"same candidate pledged twice");
            world["heroes"].Vector().push_back(json(R"({"ref":"new","army_value":500,"hero_type_id":42})"));
            campaign.review(world);require(campaign.statuses()["helper"]["state"].String()!="completed","preexisting matching hero completed hire");
            JsonNode receipt;receipt["goal"]=plan["goals"][0];receipt["day"].Integer()=1;receipt["hero_ref"].String()="new";receipt["hero_type_id"].Integer()=99;
            world["confirmed_helper_hires"].Vector().push_back(receipt);campaign.review(world);
            require(campaign.statuses()["helper"]["state"].String()!="completed","wrong candidate receipt completed hire");
            receipt["hero_type_id"].Integer()=42;receipt["goal"]["job_ref"].String()="other";world["confirmed_helper_hires"].Vector().push_back(receipt);campaign.review(world);
            require(campaign.statuses()["helper"]["state"].String()!="completed","different job receipt completed hire");
            receipt["goal"]=plan["goals"][0];receipt["hero_ref"].String()="missing";world["confirmed_helper_hires"].Vector().push_back(receipt);campaign.review(world);
            require(campaign.statuses()["helper"]["state"].String()!="completed","unowned hired hero completed hire");
            receipt["hero_ref"].String()="new";world["confirmed_helper_hires"].Vector().push_back(receipt);campaign.review(world);
            require(campaign.statuses()["helper"]["state"].String()=="completed","exact observed own hire did not complete");
            const auto hiredSignals=nullkiller3::helperHiredSignals(campaign,world,true);
            require(hiredSignals.size()==1 && hiredSignals[0].question=="helper_hired:helper","actual helper hire did not request model planning");
            nullkiller3::RequestArbiter hireArbiter;hireArbiter.beginTurn(1,{280000,120000,40000});
            const auto hireRequest=hireArbiter.consider(hiredSignals);require(hireRequest.request,"post-hire planning was suppressed");
            hireArbiter.dispatched(hireRequest);hireArbiter.finished(100,100);
            require(!hireArbiter.consider(hiredSignals).request,"same receipt repeatedly requested model planning");
            require(!nullkiller3::RequestArbiter(hireArbiter.save()).consider(hiredSignals).request,"saved hire signal replayed review");
            nullkiller3::CampaignState restored(campaign.save());
            require(restored.restoreReason().empty() && restored.statuses()["helper"]["state"].String()=="completed","helper hire replayed after save/load");
            auto forged=campaign.save();forged.Struct().erase("helper_hire_completions");
            require(nullkiller3::CampaignState(forged).plan().isNull(),"saved helper completion without hire receipt accepted");
            auto lostWorld=world;lostWorld["heroes"].Vector().pop_back();restored.review(lostWorld);
            require(restored.statuses()["helper"]["state"].String()=="completed","lost hired hero resurrected old hire");
            require(nullkiller3::helperHiredSignals(restored,lostWorld,true).empty(),"lost helper requested planning as owned hero");
            auto wrongSaved=campaign.save();wrongSaved["helper_hire_completions"]["helper"]["hero_type_id"].Integer()=99;
            require(nullkiller3::CampaignState(wrongSaved).plan().isNull(),"mismatched saved candidate receipt accepted");
            auto revised=plan;revised["revision"].Integer()=2;world["towns"][0]["hiring_options"].Vector().clear();
            require(restored.accept(revised,world,reason) && restored.statuses()["helper"]["state"].String()=="completed","completed hire replayed when candidate left tavern");
            auto saved=json(R"({"object_ids":{}})");saved["helper_hire_receipts"]["helper"]=receipt;
            require(nullkiller3::restoreNativeNamespace(saved)["helper_hire_receipts"]["helper"]==receipt,"native hiring receipt lost on restore");
            saved["helper_hire_receipts"]["helper"]["day"].Integer()=0;
            require(nullkiller3::restoreNativeNamespace(saved)["helper_hire_receipts"].isNull(),"malformed native hire receipt accepted");
            std::cout << "NK3 exact candidate, useful job, funding, receipt and no-replay proof passed\n";return 0;
        }
        if(argc==2 && std::string(argv[1])=="--interception")
        {
            const auto input=json(std::string(std::istreambuf_iterator<char>(std::cin),{}));
            auto world=input["world"];const auto & goal=input["plan"]["goals"][0];
            nullkiller3::CampaignState campaign;std::string reason;
            require(campaign.accept(input["plan"],world,reason),reason.c_str());
            campaign.review(world,false);
            require(campaign.statuses()[goal["id"].String()]["state"].String()!="completed","visibility alone completed interception");
            JsonNode receipt;receipt["goal"]=goal;receipt["goal"]["target_ref"].String()="different-enemy";receipt["won"].Bool()=true;receipt["day"]=world["day"];
            world["confirmed_interceptions"].Vector().push_back(receipt);campaign.review(world,false);
            require(campaign.statuses()[goal["id"].String()]["state"].String()!="completed","different battle completed interception");
            receipt["goal"]=goal;receipt["won"].Bool()=false;world["confirmed_interceptions"].Vector().push_back(receipt);campaign.review(world,false);
            require(campaign.statuses()[goal["id"].String()]["state"].String()!="completed","lost battle completed interception");
            receipt["won"].Bool()=true;world["confirmed_interceptions"].Vector().push_back(receipt);campaign.review(world,false);
            require(campaign.statuses()[goal["id"].String()]["state"].String()=="completed","exact won engagement did not complete");
            auto renewed=input["plan"];renewed["revision"].Integer()++;
            world["day"].Integer()++;
            for(auto & object:world["objects"].Vector()) if(object["ref"]==goal["target_ref"]) object["visible"].Bool()=false;
            require(campaign.accept(renewed,world,reason),"acknowledged interception was lost on revision");
            nullkiller3::CampaignState restored(campaign.save());
            require(!restored.plan().isNull() && restored.statuses()[goal["id"].String()]["state"].String()=="completed","save lost exact engagement receipt");
            std::cout<<"Exact interception and save receipt passed\n";return 0;
        }
        if(argc==2 && std::string(argv[1])=="--garrison")
        {
            const auto input=json(std::string(std::istreambuf_iterator<char>(std::cin),{}));
            auto world=input["world"];
            nullkiller3::CampaignState campaign;
            std::string reason;
            require(campaign.accept(input["plan"],world,reason),reason.c_str());
            const auto & goal=input["plan"]["goals"][0];
            campaign.review(world,false);
            require(campaign.statuses()[goal["id"].String()]["state"].String()!="completed","main army was counted as separate garrison");
            const auto choices=nullkiller3::forecastTownChoices(world,campaign);
            require(choices.Vector().size()==1 && choices[0]["garrison_after_departure"].Integer()==0,"departure kept the main in two places");
            require(choices[0]["buy_garrison"]["additional_force"].Integer()==39052
                && choices[0]["buy_garrison"]["cost"][6].Integer()==24530,"owned day100 stock/funds quote changed");
            world["towns"][0]["army_holder_ref"]=world["towns"][0]["ref"];
            world["towns"][0]["defense_value"]=goal["complete_when"]["value"];
            world["heroes"][0]["army_value"].Integer()=goal["min_army_value"].Integer()-1;
            campaign.review(world,false);
            require(campaign.statuses()[goal["id"].String()]["state"].String()!="completed","garrison spent the main floor");
            world["heroes"][0]["army_value"]=goal["min_army_value"];
            campaign.review(world,false);
            require(campaign.statuses()[goal["id"].String()]["state"].String()=="completed","separate garrison did not release dependent attack");
            auto withAttack=input["plan"];
            auto attack=withAttack["goals"][0];
            attack["id"].String()="after-garrison";attack["kind"].String()="capture_target";
            attack.Struct().erase("garrison_mode");attack["target_ref"].String()="object:1";
            attack["min_army_value"].Integer()=510000;attack["depends_on"].Vector().push_back(goal["id"]);
            attack["complete_when"]["kind"].String()="target_owned";attack["complete_when"]["value"]=input["world"]["player"];
            withAttack["goals"].Vector().push_back(attack);
            nullkiller3::CampaignState protectedAttack;
            require(protectedAttack.accept(withAttack,input["world"],reason),reason.c_str());
            const auto protectedChoices=nullkiller3::forecastTownChoices(input["world"],protectedAttack);
            require(protectedChoices[0]["active_main_floor"].Integer()==510000
                && protectedChoices[0]["separable_surplus_under_current_plan"].Integer()==1587,
                "garrison quote omitted the dependent attack floor");
            std::cout<<"Separate garrison and main floor completion passed\n";
            return 0;
        }
        if(argc==2 && std::string(argv[1])=="--idle-sites")
        {
            const auto input=json(std::string(std::istreambuf_iterator<char>(std::cin),{}));
            auto world=input["world"];
            nullkiller3::CampaignState campaign;
            std::string reason;
            require(campaign.accept(input["plan"],world,reason),reason.c_str());
            const auto signals=nullkiller3::idleArmySignals(campaign,world,true);
            require(signals.size()==1,"fixture has no idle main army signal");
            nullkiller3::RequestArbiter arbiter;
            arbiter.beginTurn(world["day"].Integer(),{280000,120000,40000});
            const auto first=arbiter.consider(signals);
            require(first.request,"initial idle agenda was not offered");
            arbiter.dispatched(first);arbiter.finished(1000,1000);
            require(!arbiter.consider(signals).request,"unchanged idle agenda retried");
            auto consumed=world;
            bool found=false;
            for(auto & site:consumed["objects"].Vector()) if(site["ref"]==input["site_ref"])
            {require(site["visible"].Bool() && !site["visited"].Bool(),"fixture site not visible and unvisited");site["visited"].Bool()=true;found=true;}
            require(found,"fixture has no consumed site");
            const auto changed=nullkiller3::idleArmySignals(campaign,consumed,true);
            require(arbiter.consider(changed).request,"a confirmed useful site visit was suppressed as an unchanged idle agenda");
            auto reordered=world;std::reverse(reordered["objects"].Vector().begin(),reordered["objects"].Vector().end());
            std::reverse(reordered["forecasts"]["routes"].Vector().begin(),reordered["forecasts"]["routes"].Vector().end());
            require(!arbiter.consider(nullkiller3::idleArmySignals(campaign,reordered,true)).request,"object or quote order retried idle review");
            auto tomorrow=world;tomorrow["day"].Integer()++;
            for(auto & route:tomorrow["forecasts"]["routes"].Vector()) for(auto & arrival:route["own_arrivals"].Vector()) arrival["day"].Integer()++;
            require(!arbiter.consider(nullkiller3::idleArmySignals(campaign,tomorrow,true)).request,"calendar or quote day alone retried idle review");
            auto hidden=consumed;
            for(auto & site:hidden["objects"].Vector()) if(site["ref"]==input["site_ref"])
            {site["visible"].Bool()=false;site["visited"].Bool()=false;}
            require(nullkiller3::idleArmySignals(campaign,hidden,true)[0].facts==changed[0].facts,"hidden sites altered idle agenda");
            auto unsafe=world;
            for(auto & route:unsafe["forecasts"]["routes"].Vector()) if(route["target_ref"]==input["site_ref"])
                for(auto & arrival:route["own_arrivals"].Vector()) arrival["army_loss_estimate"].Integer()=1;
            require(nullkiller3::idleArmySignals(campaign,unsafe,true)[0].facts==changed[0].facts,"unsafe visits were offered as safe useful sites");
            nullkiller3::RequestArbiter restored(arbiter.save());
            require(restored.consider(changed).request && !restored.consider(signals).request,"save/load lost changed-agenda or unchanged-agenda identity");
            std::cout<<"Idle useful-site agenda change and deduplication proof passed\n";
            return 0;
        }
        if(argc==2 && std::string(argv[1])=="--visit-site")
        {
            const auto input=json(std::string(std::istreambuf_iterator<char>(std::cin),{}));
            const auto world=input["world"],plan=input["plan"],goal=plan["goals"][0];
            const auto id=goal["id"].String();
            std::string reason;
            for(const auto * field:{"actor_ref","target_ref"})
            {
                auto forged=input["receipt"];
                bool changed=false;
                for(const auto & item:world[std::string(field)=="actor_ref" ? "heroes" : "objects"].Vector())
                    if(item["ref"]!=goal[field]) {forged["goal"][field]=item["ref"];changed=true;break;}
                require(changed,"fixture has no different actor or target");
                nullkiller3::CampaignState state;
                require(state.accept(plan,world,reason),reason.c_str());
                auto observed=world;observed["confirmed_site_visits"].Vector().push_back(forged);
                state.review(observed);
                require(state.statuses()[id]["state"].String()!="completed","another actor or target completed the site goal");
            }
            nullkiller3::CampaignState state;
            require(state.accept(plan,world,reason),reason.c_str());
            auto observed=world;observed["confirmed_site_visits"].Vector().push_back(input["receipt"]);
            state.review(observed);
            require(state.statuses()[id]["state"].String()=="completed","exact site visit did not complete its goal");
            nullkiller3::CampaignState restored(state.save());
            require(restored.restoreReason().empty(),"completed site goal failed save/load");
            auto forgedSave=state.save();forgedSave.Struct().erase("site_completions");
            require(!nullkiller3::CampaignState(forgedSave).restoreReason().empty(),"completed site without a receipt survived load");
            auto later=input["later_world"],next=plan,newGoal=goal;
            // Consumed sites need the saved receipt when fresh world no longer
            // repeats it. Modern null risk is the same legacy completed goal.
            later.Struct().erase("confirmed_site_visits");
            next["goals"][0]["risk"]=JsonNode();
            next["revision"].Integer()++;
            newGoal["id"].String()="next-site";
            newGoal["deadline_day"].Integer()=later["day"].Integer()+2;
            newGoal["depends_on"].Vector().push_back(goal["id"]);
            bool found=false;
            for(const auto & item:later["objects"].Vector())
                if(item["kind"].String()=="treasure_chest" && item["visible"].Bool() && !item["visited"].Bool())
                {newGoal["target_ref"]=item["ref"];found=true;break;}
            require(found,"fixture has no next visible unvisited site");
            next["goals"].Vector().push_back(newGoal);
            require(restored.accept(next,later,reason),reason.c_str());
            require(restored.statuses()[id]["completed_day"]==input["receipt"]["day"],"retaining a consumed site lost its completion day");
            require(restored.statuses()["next-site"]["state"].String()!="completed","a different site inherited completion");
            const auto carried=restored.save();
            require(carried["validation_world"]["confirmed_site_visits"].Vector().size()==1
                && carried["validation_world"]["confirmed_site_visits"][0]==input["receipt"],
                "carried site receipt was duplicated or its identity changed");
            nullkiller3::CampaignState retained(carried);
            require(retained.restoreReason().empty(),"retained consumed site dependency failed save/load");
            auto malformed=carried;malformed["site_completions"][id]["goal"]["target_ref"].String()="different-site";
            require(!nullkiller3::CampaignState(malformed).restoreReason().empty(),"malformed carried site receipt survived load");
            auto changed=plan;changed["revision"].Integer()++;
            changed["goals"][0]["id"].String()="renamed-consumed-site";
            nullkiller3::CampaignState fresh;
            require(!fresh.accept(changed,later,reason),"renamed goal admitted an invisible consumed site");
            std::cout<<"Site visit actor/target receipt and retained dependency proof passed\n";
            return 0;
        }
        if(argc==2 && std::string(argv[1])=="--scout-area")
        {
            const auto input=json(std::string(std::istreambuf_iterator<char>(std::cin),{}));
            auto world=input["world"],plan=input["plan"];
            const auto goal=plan["goals"][0];
            const auto & id=goal["id"].String();
            std::string reason;
            for(bool changeRadius:{false,true})
            {
                nullkiller3::CampaignState state;
                require(state.accept(plan,world,reason),reason.c_str());
                auto next=plan;next["revision"].Integer()++;
                auto stale=world;
                // A goal label by itself is never evidence of an observed area.
                stale["observed_scout_areas"].Vector().push_back(goal["id"]);
                JsonNode priorArea;priorArea["target_ref"]=goal["target_ref"];priorArea["sight_radius"]=goal["complete_when"]["value"];
                stale["observed_scout_areas"].Vector().push_back(priorArea);
                if(changeRadius)
                {
                    const auto radius=goal["complete_when"]["value"].Integer()+1;
                    next["goals"][0]["complete_when"]["value"].Integer()=radius;
                    for(auto & hero:stale["heroes"].Vector()) if(hero["ref"]==goal["actor_ref"]) hero["sight_radius"].Integer()=radius;
                    for(auto & area:stale["scouting_options"].Vector()) for(auto & route:area["own_arrivals"].Vector())
                        if(route["hero_ref"]==goal["actor_ref"]) route["sight_radius"].Integer()=radius;
                }
                else
                {
                    bool found=false;
                    for(const auto & area:stale["scouting_options"].Vector())
                        if(area["ref"]!=goal["target_ref"]) for(const auto & route:area["own_arrivals"].Vector())
                            if(route["hero_ref"]==goal["actor_ref"] && route["sight_radius"]==goal["complete_when"]["value"])
                            {next["goals"][0]["target_ref"]=area["ref"];found=true;break;}
                    require(found,"fixture has no different own observation area");
                }
                require(state.accept(next,stale,reason),reason.c_str());
                require(state.statuses()[id]["state"].String()!="completed","reused goal ID completed a different target or radius");
            }
            nullkiller3::CampaignState state;
            require(state.accept(plan,world,reason),reason.c_str());
            JsonNode observed;observed["target_ref"]=goal["target_ref"];observed["sight_radius"]=goal["complete_when"]["value"];
            world["observed_scout_areas"].Vector().push_back(observed);
            state.review(world);
            require(state.statuses()[id]["state"].String()=="completed","matching area facts did not complete scouting");
            std::cout<<"Scouting completion target/radius identity proof passed\n";
            return 0;
        }
        auto namespaceState=json(R"({"object_ids":{"0":0,"17":1},"native_campaign":{"version":3},"request_arbiter":{"tokens":0},"experience_id":"retained"})");
        nullkiller3::ResourceLedger finances;
        finances.begin(json("[0,0,0,0,0,0,1000]"));
        finances.received(json("[0,0,0,0,0,0,3000]"));
        finances.received(json("[0,0,0,0,0,0,500]"));
        const auto expense=finances.receipt(json("[0,0,0,0,0,0,500]"));
        require(expense["debits"][6].Integer()==2500,"task expenses were reduced by a prior resource pickup");
        require(expense["credits"][6].Integer()==2000 && expense["coverage"].String()=="complete",
            "acknowledged income was not separated from task expense");
        require(finances.receipt(json("[0,0,0,0,0,0,400]"))["debits"].isNull(),
            "an unobserved final balance fabricated a complete expense receipt");
        finances.begin(json("[10,0,0,0,0,0,500]"));
        finances.received(json("[0,0,0,0,0,0,1000]"));
        const auto traded=finances.receipt(json("[0,0,0,0,0,0,1000]"));
        require(traded["debits"][0].Integer()==10 && traded["credits"][6].Integer()==500
            && traded["debits"][6].Integer()==0,"a new task retained old spending or netted a trade across resources");
        const auto march=json(R"({"kind":"capture_mine","actor_ref":"object:0","target_ref":"object:2"})");
        auto marchFacts=json(R"({"object:0":{"position":[1,1,0],"army_value":1000,"in_boat":false},"route_cost":5})");
        auto marchClock=nullkiller3::operationProgress(JsonNode(),march,marchFacts,1);
        marchClock["last_no_change_day"].Integer()=2;
        marchFacts["object:0"]["position"][1].Integer()=2;
        const auto lateral=nullkiller3::operationProgress(marchClock,march,marchFacts,2);
        require(lateral["last_progress_day"].Integer()==1 && nullkiller3::operationStalled(lateral,JsonNode(),"mine",3),
            "movement without approaching the objective refreshed the progress clock");
        marchFacts["route_cost"].Integer()=4;
        const auto closer=nullkiller3::operationProgress(marchClock,march,marchFacts,2);
        require(closer["last_progress_day"].Integer()==2 && !nullkiller3::operationStalled(closer,JsonNode(),"mine",3),
            "a supported approach to the objective was treated as stagnation");
        auto retreatFacts=marchFacts;retreatFacts["route_cost"].Integer()=6;
        auto retreat=nullkiller3::operationProgress(closer,march,retreatFacts,3);
        retreat["last_no_change_day"].Integer()=3;
        const auto revisit=nullkiller3::operationProgress(retreat,march,marchFacts,4);
        require(revisit["last_progress_day"].Integer()==2 && nullkiller3::operationStalled(revisit,JsonNode(),"mine",4),
            "revisiting the same best route position erased an unproductive movement loop");
        auto replacementFacts=marchFacts;
        replacementFacts["object:3"]=json(R"({"position":[8,8,0],"army_value":1000})");
        replacementFacts["route_subject"]=json(R"({"traveler":"object:3","destination":"object:0"})");
        replacementFacts["route_cost"].Integer()=8;
        const auto replacementClock=nullkiller3::operationProgress(closer,march,replacementFacts,3);
        require(replacementClock["best_route_cost"].Integer()==8,"a replacement courier inherited the lost source's shortest route");
        replacementFacts["route_cost"].Integer()=7;
        replacementFacts["object:3"]["position"][0].Integer()=7;
        require(nullkiller3::operationProgress(replacementClock,march,replacementFacts,4)["last_progress_day"].Integer()==4,
            "a replacement courier approaching the recipient was marked stalled");
        auto recipientClock=nullkiller3::operationProgress(replacementClock,march,replacementFacts,4);
        replacementFacts["object:0"]["position"][0].Integer()=2;
        replacementFacts["route_cost"].Integer()=6;
        require(nullkiller3::operationProgress(recipientClock,march,replacementFacts,5)["last_progress_day"].Integer()==5,
            "the recipient approaching its courier was treated as stagnation");
        auto refillFacts=marchFacts;refillFacts["route_cost"].Integer()=3;
        require(nullkiller3::operationProgress(closer,march,refillFacts,3)["last_progress_day"].Integer()==2,
            "daily movement refill without actual travel was counted as objective progress");
        auto savedMarch=namespaceState;savedMarch["operation_progress"]["mine"]=revisit;
        require(nullkiller3::restoreNativeNamespace(savedMarch)["operation_progress"]["mine"]["best_route_cost"].Integer()==4,
            "loading forgot the previous best objective position");
        savedMarch["operation_progress"]["mine"]["best_route_cost"].String()="invalid";
        require(nullkiller3::restoreNativeNamespace(savedMarch)["native_campaign"].isNull(),
            "malformed saved route progress retained executable intent");
        auto budget=namespaceState["request_arbiter"];
        require(nullkiller3::validNativeAliases(namespaceState["object_ids"]),"canonical aliases rejected");
        for(const auto & aliases:{json(R"({"bad":0})"),json(R"({"0":"bad"})"),json(R"({"0":0,"17":0})"),json(R"({"9999999999999999":0})"),json(R"({"01":0})")})
        {
            auto malformed=namespaceState;malformed["object_ids"]=aliases;
            const auto restored=nullkiller3::restoreNativeNamespace(malformed);
            require(restored["native_campaign"].isNull(),"invalid alias namespace retained executable intent");
            require(restored["request_arbiter"]==budget,"intent reset refunded spent budget");
            require(restored["experience_id"]==namespaceState["experience_id"],"intent reset changed experience owner");
        }
        for(const auto * field:{"strategy_metadata","local_repairs","delivery_receipts","goal_blockers","memory","pending_native_task","building_progress","operation_progress","checkpoint_baseline"})
        {
            auto malformed=namespaceState;malformed[field].String()="invalid";
            const auto restored=nullkiller3::restoreNativeNamespace(malformed);
            require(restored["native_campaign"].isNull(),"malformed saved namespace retained intent");
            require(restored["request_arbiter"]==budget,"malformed state refunded spent budget");
        }
        require(nullkiller3::restoreNativeNamespace(json("1"))["request_arbiter"].isString(),"invalid root granted fresh model budget");
        auto checkpointNamespace=namespaceState;
        checkpointNamespace["checkpoint_baseline"]=json(R"({"day":4,"facts":"funded-allocation"})");
        require(nullkiller3::restoreNativeNamespace(checkpointNamespace)["checkpoint_baseline"]==checkpointNamespace["checkpoint_baseline"],
            "checkpoint decision baseline did not survive load");
        checkpointNamespace["checkpoint_baseline"]["day"].Integer()=-1;
        const auto invalidCheckpoint=nullkiller3::restoreNativeNamespace(checkpointNamespace);
        require(invalidCheckpoint["checkpoint_baseline"].isNull() && invalidCheckpoint["native_campaign"].isNull()
            && invalidCheckpoint["request_arbiter"]==budget,"malformed checkpoint refunded budget or retained executable intent");
        auto progressNamespace=namespaceState;
        progressNamespace["building_progress"]=json(R"({"object:1:3":{"remaining":[2,3],"last_progress_day":2}})");
        require(nullkiller3::restoreNativeNamespace(progressNamespace)["building_progress"]==progressNamespace["building_progress"],
            "own building progress clock did not survive save/load");
        progressNamespace["building_progress"]["object:1:3"]["last_progress_day"].Integer()=-1;
        const auto invalidProgress=nullkiller3::restoreNativeNamespace(progressNamespace);
        require(invalidProgress["building_progress"].isNull() && invalidProgress["native_campaign"].isNull()
            && invalidProgress["request_arbiter"]==budget,"invalid progress retained intentions or refunded budget");
        auto operationNamespace=namespaceState;
        operationNamespace["operation_progress"]=json(R"({"deliver":{"objective":{"kind":"reinforce_hero"},"facts":{},"last_progress_day":1,"last_no_change_day":2}})");
        require(nullkiller3::restoreNativeNamespace(operationNamespace)["operation_progress"]==operationNamespace["operation_progress"],
            "own operation progress did not survive save/load");
        operationNamespace["operation_progress"]["deliver"]["last_no_change_day"].String()="invalid";
        const auto invalidOperation=nullkiller3::restoreNativeNamespace(operationNamespace);
        require(invalidOperation["operation_progress"].isNull() && invalidOperation["native_campaign"].isNull()
            && invalidOperation["request_arbiter"]==budget,"invalid operation clock retained intent or refunded budget");
        auto lateNamespace=namespaceState;
        lateNamespace["goal_blockers"]=json(R"({"supply":{"revision":1,"reason":"deadline_unreachable","route_turns":2}})");
        require(nullkiller3::restoreNativeNamespace(lateNamespace)["goal_blockers"]==lateNamespace["goal_blockers"],
            "supported route timing did not survive save/load");
        lateNamespace["goal_blockers"]["supply"]["route_turns"].String()="invalid";
        const auto invalidTiming=nullkiller3::restoreNativeNamespace(lateNamespace);
        require(invalidTiming["goal_blockers"].isNull() && invalidTiming["request_arbiter"]==budget,
            "invalid route timing retained intent or refunded budget");
        auto pendingNamespace=namespaceState;
        pendingNamespace["pending_native_task"]=json(R"({"version":1,"action":{"kind":"native_task","goal_id":"","native_goal_type":1},"before":{"day":1,"player":0,"resources":[0,0,0,0,0,0,0],"heroes":[],"towns":[]}})");
        require(nullkiller3::restoreNativeNamespace(pendingNamespace)["pending_native_task"]==pendingNamespace["pending_native_task"],"a value-only pending result was lost before reconciliation");
        pendingNamespace["pending_native_task"]["action"]["kind"].String()="end_turn";
        auto rejectedPending=nullkiller3::restoreNativeNamespace(pendingNamespace);
        require(rejectedPending["pending_native_task"].isNull() && rejectedPending["native_campaign"].isNull(),"unsupported pending result became executable saved context");
        require(rejectedPending["request_arbiter"]==budget,"rejecting pending context refunded model budget");
        auto world = json(R"({"day":1,"player":0,"resources":[10,0,10,0,0,0,10000],"capabilities":["land","build","transfer"],"heroes":[{"ref":"object:0","army_value":5000},{"ref":"object:1","army_value":1000}],"towns":[{"ref":"object:2","buildings":[10],"building_options":[{"id":11,"supported":true}]}],"objects":[{"ref":"object:3","kind":"town","owner":1,"visible":true}]})");
        auto proposal = json(R"({"version":3,"revision":1,"approach":"expansion","horizon_days":5,"goals":[{"id":"develop","kind":"develop_town","actor_ref":null,"target_ref":"object:2","deadline_day":4,"priority":50,"building_id":11,"min_army_value":0,"depends_on":[],"required_capabilities":["build"],"complete_when":{"kind":"building_present","value":11}},{"id":"attack","kind":"capture_target","actor_ref":"object:0","target_ref":"object:3","deadline_day":6,"priority":80,"building_id":-1,"min_army_value":4500,"depends_on":["develop"],"required_capabilities":["land"],"complete_when":{"kind":"target_owned","value":0}}],"reserves":[{"goal_id":"develop","resources":[5,0,0,0,0,0,2000],"force_value":0}],"policy":{"max_loss_ratio":0.2,"allow_route_repair":true,"allow_helper_replacement":true,"critical_towns":["object:2"]}})");
        nullkiller3::CampaignState campaign;
        std::string reason;
        require(campaign.accept(proposal, world, reason), reason.c_str());
        auto defendedWorld=world;
        defendedWorld["day"].Integer()=13;
        defendedWorld["heroes"][0]["army_value"].Integer()=22666;
        defendedWorld["heroes"][0]["position"]=json("[5,11,0]");
        defendedWorld["towns"][0]["position"]=json("[5,11,0]");
        defendedWorld["towns"][0]["defense_value"].Integer()=5679;
        defendedWorld["towns"][0]["army_holder_ref"].String()="object:2";
        defendedWorld["towns"][0]["visiting_hero_ref"].String()="object:0";
        auto defensePlan=proposal;
        defensePlan["goals"].Vector().resize(1);
        defensePlan["reserves"].Vector().clear();
        auto & duty=defensePlan["goals"][0];
        duty["id"].String()="hold-home";duty["kind"].String()="defend_area";
        duty["actor_ref"].String()="object:0";duty["building_id"].Integer()=-1;
        duty["deadline_day"].Integer()=13;duty["min_army_value"].Integer()=22666;
        duty["required_capabilities"]=json("[\"land\"]");
        duty["complete_when"]=json(R"({"kind":"held_until","value":13})");
        nullkiller3::CampaignState defended;
        require(defended.accept(defensePlan,defendedWorld,reason),reason.c_str());
        require(defended.statuses()["hold-home"]["state"].String()=="completed",
            "own visiting defender at its town was omitted from completed defense force");
        auto elsewhere=defendedWorld;
        elsewhere["heroes"][0]["position"]=json("[6,11,0]");
        nullkiller3::CampaignState notStationed;
        require(notStationed.accept(defensePlan,elsewhere,reason),reason.c_str());
        require(notStationed.statuses()["hold-home"]["state"].String()=="ready",
            "a nearby hero was counted as already stationed in the town");
        auto unknownVisitor=defendedWorld;
        unknownVisitor["towns"][0]["visiting_hero_ref"].String()="object:99";
        nullkiller3::CampaignState notOwned;
        require(notOwned.accept(defensePlan,unknownVisitor,reason),reason.c_str());
        require(notOwned.statuses()["hold-home"]["state"].String()=="ready",
            "an unobserved foreign visitor supplied own town defense");
        auto onePool=defendedWorld;
        onePool["towns"][0]["army_holder_ref"].String()="object:0";
        onePool["towns"][0]["defense_value"].Integer()=22666;
        auto largerDefense=defensePlan;largerDefense["goals"][0]["min_army_value"].Integer()=30000;
        nullkiller3::CampaignState aliasedDefense;
        require(aliasedDefense.accept(largerDefense,onePool,reason),reason.c_str());
        require(aliasedDefense.statuses()["hold-home"]["state"].String()=="ready",
            "town and visitor aliases counted one physical army twice");
        auto departed=defendedWorld;departed["day"].Integer()=14;departed["heroes"][0]["position"]=json("[6,11,0]");
        nullkiller3::CampaignState restoredDefense(defended.save());
        require(restoredDefense.review(departed)["hold-home"]["state"].String()=="completed",
            "load erased an acknowledged defense completed before departure");
        auto cancelledSave=campaign.save();
        cancelledSave["statuses"]["develop"]["state"].String()="cancelled";
        cancelledSave["statuses"]["develop"]["reason"].String()="strategy_cancelled";
        nullkiller3::CampaignState cancelled(cancelledSave);
        require(!cancelled.plan().isNull(),"a valid cancelled saved intention was discarded");
        const auto cancelledReview=cancelled.review(world);
        require(cancelledReview["develop"]["state"].String()=="cancelled","load reactivated a cancelled commitment");
        require(cancelledReview["attack"]["reason"].String()=="dependency_failed","dependent operation waited on a cancelled prerequisite");
        require(cancelled.reservedResources()[6].Integer()==0 && cancelled.participantGoals("object:0").empty(),
            "cancelled intentions retained live resources or dependent actors");
        auto battleMemory=json(R"({"recent_results":[{"sequence":1,"day":1,"outcome":"battle_won","action":{"kind":"battle","source":"own_battle_result","campaign_revision":1,"actor_ref":"object:0","army_value_before":5000,"army_loss_value":1001}}]})");
        auto lossSignals=nullkiller3::battleLossSignals(proposal,battleMemory,true);
        require(lossSignals.size()==1 && lossSignals[0].critical,"unexpected acknowledged combat loss did not request review");
        nullkiller3::RequestArbiter lossArbiter;lossArbiter.beginTurn(1,{1000,1000,0});
        auto lossReview=lossArbiter.consider(lossSignals);lossArbiter.dispatched(lossReview);lossArbiter.finished(10,10);
        require(!lossArbiter.consider(lossSignals).request,"unchanged combat evidence retried the model");
        auto laterBattle=battleMemory["recent_results"][0];laterBattle["sequence"].Integer()=2;
        battleMemory["recent_results"].Vector().push_back(laterBattle);
        auto nextLoss=nullkiller3::battleLossSignals(proposal,battleMemory,true);
        require(nextLoss.size()==1,"old and new battles became competing facts for one question");
        auto nextReview=lossArbiter.consider(nextLoss);require(nextReview.request,"independent combat loss was suppressed");
        lossArbiter.dispatched(nextReview);lossArbiter.finished(10,10);
        require(!lossArbiter.consider(nullkiller3::battleLossSignals(proposal,battleMemory,true)).request,"earlier battle retried after the latest review");
        battleMemory["recent_results"].Vector().pop_back();
        auto safeBattle=battleMemory;safeBattle["recent_results"][0]["action"]["army_loss_value"].Integer()=1000;
        require(nullkiller3::battleLossSignals(proposal,safeBattle,true).empty(),"allowed casualties requested strategic review");
        safeBattle["recent_results"][0]["outcome"].String()="battle_lost";
        require(nullkiller3::battleLossSignals(proposal,safeBattle,true).size()==1,"confirmed own defeat did not request review");
        for(const auto * field:{"source","kind"})
        {
            auto unknown=battleMemory;unknown["recent_results"][0]["action"][field].String()="native_task";
            require(nullkiller3::battleLossSignals(proposal,unknown,true).empty(),"task net change became combat evidence");
        }
        auto oldBattle=battleMemory;oldBattle["recent_results"][0]["action"]["campaign_revision"].Integer()=0;
        require(nullkiller3::battleLossSignals(proposal,oldBattle,true).empty(),"replacement strategy retried a past battle");
        auto expired=campaign;auto lateWorld=world;lateWorld["day"].Integer()=8;
        expired.review(lateWorld);
        require(expired.reservedResources()[6].Integer()==0,"expired obligations froze native fallback funds");
        require(expired.participantGoals("object:0").empty(),"expired actor could not continue native play");
        lateWorld["towns"][0]["buildings"].Vector().push_back(JsonNode(int64_t(11)));
        require(expired.review(lateWorld)["develop"]["reason"].String()=="deadline_missed","an overdue building falsely completed the expired commitment");
        auto lostTown=campaign;auto lostWorld=world;lostWorld["towns"].Vector().clear();
        auto townLoss=nullkiller3::criticalTownLossSignals(proposal,lostWorld,true);
        require(townLoss.size()==1 && townLoss[0].question=="critical_town_lost:object:2" && townLoss[0].critical,
            "policy critical town loss did not request review");
        require(nullkiller3::criticalTownLossSignals(proposal,world,true).empty(),"owned critical town reported as lost");
        auto missingOwnList=lostWorld;missingOwnList.Struct().erase("towns");
        require(nullkiller3::criticalTownLossSignals(proposal,missingOwnList,true).empty(),"missing complete own list proved town loss");
        lostTown.review(lostWorld);
        require(lostTown.statuses()["develop"]["reason"].String()=="target_no_longer_owned","own town loss was not a strategic failure");
        require(lostTown.reservedResources()[6].Integer()==0,"lost town kept unusable economic reserves");
        auto blockers=json(R"({"attack":{"revision":1,"reason":"route_not_established"}})");
        auto basis=nullkiller3::repairQuestionFacts(proposal,blockers,campaign.statuses());
        auto renumbered=proposal;renumbered["revision"].Integer()=2;
        renumbered["goals"][1]["id"].String()="renamed";renumbered["goals"][1]["deadline_day"].Integer()=7;
        auto renamedBlockers=json(R"({"renamed":{"revision":2,"reason":"route_not_established"}})");
        require(nullkiller3::repairQuestionFacts(renumbered,renamedBlockers,campaign.statuses())==basis,"renumbered unchanged blocker retried the model");
        renumbered["goals"][1]["target_ref"].String()="object:4";
        require(nullkiller3::repairQuestionFacts(renumbered,renamedBlockers,campaign.statuses())!=basis,"independent target problem was suppressed");
        blockers["attack"]["reason"].String()="deadline_unreachable";
        blockers["attack"]["route_turns"].Integer()=2;
        const auto lateBasis=nullkiller3::repairQuestionFacts(proposal,blockers,campaign.statuses());
        blockers["attack"]["route_turns"].Integer()=3;
        require(nullkiller3::repairQuestionFacts(proposal,blockers,campaign.statuses())!=lateBasis,
            "a materially changed owned route duration was suppressed");
        auto request = json(R"({"request_id":"fresh","identity":{"generation":"fresh"},"evidence_refs":["observation:day"]})");
        auto reply = json(R"({"protocol":2,"request_id":"fresh","identity":{"generation":"fresh"},"decision":"revise","reason":"Develop then capture","evidence_refs":["observation:day"],"victory_method":"Conquest","assignments":[{"hero_ref":"object:0","role":"main"}],"alternatives":[{"approach":"economy","benefit":"Income","cost":"Building","uncertainty":"Unknown threats"},{"approach":"offense","benefit":"Capture","cost":"Army","uncertainty":"Guard estimate"}],"reconsider_when":[{"goal_id":"attack","kind":"executor_lost"}],"plan":null,"usage":{"input_tokens":100,"output_tokens":20,"known":true}})");
        reply["plan"] = proposal;
        nullkiller3::CampaignState initial, modelCandidate;
        require(nullkiller3::validateStrategicDecision(reply, request, world, initial, modelCandidate, reason), reason.c_str());
        require(modelCandidate.plan()["revision"].Integer() == 1, "model intention was not installed");
        auto stale = reply; stale["identity"]["generation"].String() = "old";
        require(!nullkiller3::validateStrategicDecision(stale, request, world, initial, modelCandidate, reason), "stale generation accepted");
        auto inconsistent = reply; inconsistent["assignments"].Vector().clear();
        require(!nullkiller3::validateStrategicDecision(inconsistent, request, world, initial, modelCandidate, reason), "model actor without role accepted");
        require(campaign.review(world)["attack"]["state"].String() == "waiting", "dependency bypassed");
        require(campaign.reservedResources()[6].Integer() == 2000, "commitment not reserved");
        auto bad = proposal;
        bad["revision"].Integer() = 2;
        auto second = bad["goals"][1]; second["id"].String() = "competing";
        bad["goals"].Vector().push_back(second);
        require(!campaign.accept(bad, world, reason), "conflicting hero accepted");
        require(campaign.plan()["revision"].Integer() == 1, "invalid strategy partially applied");
        bad = proposal; bad["revision"].Integer() = 2;
        bad["goals"][0]["building_id"].Integer() = 26;
        bad["goals"][0]["complete_when"]["value"].Integer() = 26;
        require(!campaign.accept(bad, world, reason), "unsupported Grail building accepted");
        bad = proposal; bad["revision"].Integer() = 2;
        bad["goals"][0]["required_capabilities"].Vector().push_back(JsonNode("fly"));
        require(!campaign.accept(bad, world, reason), "unsupported capability accepted");
        world["towns"][0]["buildings"].Vector().push_back(JsonNode(11));
        auto statuses = campaign.review(world);
        require(statuses["develop"]["state"].String() == "completed", "building fact not recognized");
        require(statuses["attack"]["state"].String() == "ready", "dependent goal did not unlock");
        require(campaign.reservedResources()[6].Integer() == 0, "completed reserve retained");
        // Unflaggable resources use VCMI's -2 owner, distinct from neutral -1.
        auto saved = json(campaign.save().toCompactString());
        saved["validation_world"]["objects"].Vector().push_back(json(R"({"ref":"object:4","kind":"resource","owner":-2,"visible":true})"));
        nullkiller3::CampaignState restored(saved);
        require(restored.review(world)["develop"]["state"].String() == "completed", "load replayed building");
        for(const char * field : {"version", "statuses", "accepted_day", "validation_world"})
        {
            auto malformed = saved;
            malformed[field].String() = "invalid";
            require(nullkiller3::CampaignState(malformed).plan().isNull(), "malformed save kept executable intent");
        }
        for(const auto * list:{"frontiers","observed_frontiers","confirmed_resource_pickups"})
        {
            auto invalid=saved; invalid["validation_world"][list].String()="wrong";
            require(nullkiller3::CampaignState(invalid).plan().isNull(),"malformed world list became executable state");
        }
        auto malformed = saved;
        malformed["statuses"]["develop"]["state"].Integer() = 1;
        require(nullkiller3::CampaignState(malformed).plan().isNull(), "malformed status replayed plan");
        world["objects"][0]["owner"].Integer() = 0;
        require(restored.review(world)["attack"]["state"].String() == "completed", "ownership result ignored");
        require(!nullkiller3::validateStrategicDecision(reply,request,world,initial,modelCandidate,reason), "already completed revision creates a review loop");
        auto preservation = proposal;
        preservation["goals"].Vector().clear();
        auto hold = json(R"({"id":"hold","kind":"preserve_force","actor_ref":"object:1","target_ref":"object:2","deadline_day":6,"priority":40,"building_id":-1,"min_army_value":1000,"depends_on":[],"required_capabilities":["land"],"complete_when":{"kind":"force_preserved_until","value":6}})");
        preservation["goals"].Vector().push_back(hold);
        preservation["reserves"].Vector().clear();
        nullkiller3::CampaignState guard;
        world["heroes"][1]["position"] = json("[6,12,0]");
        world["towns"][0]["position"] = json("[5,11,0]");
        require(guard.accept(preservation, world, reason), reason.c_str());
        require(guard.review(world)["hold"]["reason"].String() == "holding_preserved_force", "safe courier repeats rendezvous");
        nullkiller3::CampaignState uncertain(guard.save());
        uncertain.unconfirmedExecution(2);
        auto uncertainWorld=world;uncertainWorld["day"].Integer()=6;
        require(uncertain.review(uncertainWorld)["hold"]["reason"].String()=="force_continuity_unconfirmed",
            "an unknown saved execution falsely confirmed uninterrupted preservation");
        nullkiller3::CampaignState reloadedUncertain(uncertain.save());
        require(reloadedUncertain.restoreReason().empty(),"unconfirmed force interval did not survive serialization");
        require(reloadedUncertain.review(uncertainWorld)["hold"]["state"].String()!="completed",
            "a reloaded endpoint erased the unknown interval");
        auto refugeWorld=world;refugeWorld["day"].Integer()=2;
        refugeWorld["heroes"][1]["position"]=json("[10,12,0]");
        auto refugeGuard=guard;refugeGuard.unconfirmedExecution(2);
        require(refugeGuard.review(refugeWorld)["hold"]["stabilized_day"].isNull(),
            "an unsafe saved endpoint claimed stabilization");
        require(refugeGuard.requiresStabilization("hold"),"unknown unsafe endpoint skipped safe return");
        refugeWorld["day"].Integer()=3;
        refugeWorld["heroes"][1]["position"]=json("[6,12,0]");
        require(refugeGuard.review(refugeWorld)["hold"]["stabilized_day"].Integer()==3,
            "an observed safe return did not discharge repeated stabilization");
        refugeGuard=nullkiller3::CampaignState(refugeGuard.save());
        require(refugeGuard.restoreReason().empty(),"safe-return evidence did not restore");
        require(!refugeGuard.requiresStabilization("hold"),"the saved safe return remained urgent");
        refugeWorld["day"].Integer()=4;
        refugeWorld["heroes"][1]["position"]=json("[10,12,0]");
        require(refugeGuard.review(refugeWorld)["hold"]["stabilized_day"].Integer()==3
            && refugeGuard.statuses()["hold"]["reason"].String()=="force_continuity_unconfirmed",
            "later delivery erased the safe return or invented historical force continuity");
        auto malformedRefuge=refugeGuard.save();
        malformedRefuge["statuses"]["hold"]["stabilized_day"].Integer()=7;
        require(nullkiller3::CampaignState(malformedRefuge).plan().isNull(),"an invalid stabilization date restored");
        refugeGuard.unconfirmedExecution(4);
        require(refugeGuard.review(refugeWorld)["hold"]["stabilized_day"].isNull(),
            "a new unknown execution retained an earlier stabilization");
        require(refugeGuard.requiresStabilization("hold"),"a new missing interval did not rearm safe return");
        refugeGuard.observeForceMinimum("object:1",4,900);
        require(refugeGuard.requiresStabilization("hold"),"an actual force loss skipped stabilization");
        uncertainWorld["day"].Integer()=7;
        const auto expiredUncertain=reloadedUncertain.review(uncertainWorld)["hold"];
        require(expiredUncertain["reason"].String()=="deadline_missed"
            && expiredUncertain["failure_reason"].String()=="force_continuity_unconfirmed"
            && reloadedUncertain.reservedForce("object:1",uncertainWorld)==0,
            "an expired unknown interval retained a live force reservation");
        auto malformedUncertain=uncertain.save();
        malformedUncertain["statuses"]["hold"]["unconfirmed_since_day"].Integer()=7;
        require(nullkiller3::CampaignState(malformedUncertain).plan().isNull(),"an out-of-interval unknown marker was accepted");

        require(guard.review(world)["hold"]["state"].String() == "waiting", "holding prematurely counted as complete");
        auto packetGuard=guard;
        require(packetGuard.observeForceMinimum("object:1",2,900),"a real below-floor packet was ignored");
        require(!packetGuard.observeForceMinimum("object:1",2,1000),"later recruitment erased a previous packet loss");
        packetGuard=nullkiller3::CampaignState(packetGuard.save());
        auto recoveredWorld=world;recoveredWorld["day"].Integer()=6;
        require(packetGuard.review(recoveredWorld)["hold"]["reason"].String()=="force_floor_breached",
            "saved packet history falsely completed an uninterrupted force obligation");
        auto expiredGuard=packetGuard;auto expiredWorld=recoveredWorld;expiredWorld["day"].Integer()=7;
        require(expiredGuard.review(expiredWorld)["hold"]["reason"].String()=="deadline_missed",
            "expired failed preservation kept a surviving hero committed forever");
        require(expiredGuard.reservedForce("object:1",expiredWorld)==0
            && expiredGuard.participantGoals("object:1",{},expiredWorld).empty(),
            "an expired failed preservation retained a live force or role reservation");
        expiredGuard=nullkiller3::CampaignState(expiredGuard.save());
        require(expiredGuard.review(expiredWorld)["hold"]["observed_army_value"].Integer()==900,
            "releasing an expired commitment erased the confirmed historical force dip");
        auto damagedGuard=guard;auto damagedWorld=world;
        damagedWorld["day"].Integer()=2;damagedWorld["heroes"][1]["army_value"].Integer()=900;
        require(damagedGuard.review(damagedWorld)["hold"]["reason"].String()=="force_floor_breached","an observed preservation breach was silently forgotten");
        damagedGuard=nullkiller3::CampaignState(damagedGuard.save());
        damagedWorld["day"].Integer()=6;damagedWorld["heroes"][1]["army_value"].Integer()=1000;
        require(damagedGuard.review(damagedWorld)["hold"]["state"].String()!="completed","later recruitment falsely proved uninterrupted preservation");
        auto displacedGuard=guard;auto displacedWorld=world;displacedWorld["towns"].Vector().clear();
        displacedGuard.review(displacedWorld);
        require(displacedGuard.reservedForce("object:1",displacedWorld)>=1000,"lost safe town released the surviving courier's preservation floor");
        world["day"].Integer() = 6;
        require(guard.review(world)["hold"]["state"].String() == "completed", "preservation deadline not observed");
        world["day"].Integer() = 1;
        world["objects"].Vector().push_back(json(R"({"ref":"object:4","kind":"resource","owner":-2,"visible":true})"));
        auto resourcePlan = preservation;
        resourcePlan["goals"].Vector().clear();
        resourcePlan["goals"].Vector().push_back(json(R"({"id":"supply","kind":"secure_resource","actor_ref":"object:0","target_ref":"object:4","deadline_day":6,"priority":60,"building_id":-1,"min_army_value":0,"depends_on":[],"required_capabilities":["land"],"complete_when":{"kind":"reserve_at_least","value":1000}})"));
        nullkiller3::CampaignState supply;
        require(supply.accept(resourcePlan,world,reason),reason.c_str());
        require(supply.review(world)["supply"]["state"].String() == "ready","existing gold falsely proves a resource pickup");
        world["confirmed_resource_pickups"].Vector().push_back(JsonNode("object:4"));
        require(supply.review(world)["supply"]["state"].String() == "completed","confirmed pickup and funds did not complete supply");
        auto economyWorld = json(R"({"day":1,"days_in_week":7,"resources":[0,0,0,0,0,0,2000],"daily_income":[0,0,0,0,0,0,500],"towns":[{"ref":"home","building_options":[{"id":10,"supported":true,"availability":"allowed_now","cost":[0,0,0,0,0,0,2000],"income_delta":[0,0,0,0,0,0,500]}],"recruitment_options":[{"creature":0,"available":20,"weekly_growth":10,"unit_value":100,"unit_cost":[0,0,0,0,0,0,100]}]}]})");
        auto forecast = nullkiller3::forecastBranches(economyWorld,json("[0,0,0,0,0,0,1000]"));
        require(forecast["alternatives"].Vector().size() >= 2,"economy and early army not distinguished");
        const auto & development = forecast["alternatives"][0];
        require(development["approach"].String() == "economy","development forecast missing");
        require(development["build_day"].Integer() == 3,"forecast spent an unrelated reserve");
        const auto & army = forecast["alternatives"][1];
        require(army["approach"].String() == "offense" && army["army_purchased_value"].Integer() == 1000,"early army affordability incorrect");
        require(army["resources_at_deadline"][6].Integer() >= 1000,"army forecast consumed protected funds");
        auto choiceWorld=economyWorld;
        choiceWorld["towns"][0]["ref"].String()="object:2";
        choiceWorld["daily_income"]=json("[0,0,0,0,0,0,0]");
        choiceWorld["day"].Integer()=4;
        auto choiceBaseline=json(R"({"day":1,"facts":""})");
        const auto choices=nullkiller3::allocationCheckpointFacts(guard,choiceWorld);
        require(!choices.empty(),"mutually exclusive funded income/army choices missing from checkpoint");
        require(nullkiller3::allocationCheckpointSignals(guard,choiceWorld,choiceBaseline,true).size()==1,
            "three-day strategic allocation checkpoint missing before horizon expiry");
        choiceBaseline["facts"].String()=choices;
        choiceWorld["resources"][6].Integer()=2200;
        require(nullkiller3::allocationCheckpointSignals(guard,choiceWorld,choiceBaseline,true).empty(),
            "routine cash inside the same allocation choice repeated a review");
        choiceWorld["resources"][6].Integer()=1100;
        require(nullkiller3::allocationCheckpointSignals(guard,choiceWorld,choiceBaseline,true).empty(),
            "an unfunded investment requested a choice");
        choiceWorld["resources"][6].Integer()=4000;
        require(nullkiller3::allocationCheckpointSignals(guard,choiceWorld,choiceBaseline,true).empty(),
            "jointly affordable ordinary purchases requested a conflict review");
        choiceWorld["resources"][6].Integer()=3000;
        choiceWorld["day"].Integer()=7;choiceBaseline["day"].Integer()=5;choiceBaseline["facts"].String()="";
        require(nullkiller3::allocationCheckpointSignals(guard,choiceWorld,choiceBaseline,true).size()==1,
            "pre-growth strategic allocation checkpoint missing before three days");
        choiceWorld["day"].Integer()=6;
        require(nullkiller3::allocationCheckpointSignals(guard,choiceWorld,choiceBaseline,true).empty(),
            "ordinary daily review ignored its planned checkpoint window");
        auto scheduledPlan=guard.plan();auto & scheduledGoal=scheduledPlan["goals"][0];
        scheduledGoal["kind"].String()="develop_town";scheduledGoal["actor_ref"]=JsonNode();
        scheduledGoal["building_id"].Integer()=10;scheduledGoal["min_army_value"].Integer()=0;
        scheduledGoal["required_capabilities"]=json(R"(["build"])");
        scheduledGoal["complete_when"]=json(R"({"kind":"building_present","value":10})");
        auto scheduledWorld=choiceWorld;scheduledWorld["capabilities"]=json(R"(["build"])");
        scheduledWorld["player"].Integer()=0;scheduledWorld["towns"][0]["buildings"].Vector();
        nullkiller3::CampaignState scheduledCampaign;
        require(scheduledCampaign.accept(scheduledPlan,scheduledWorld,reason),reason.c_str());
        require(nullkiller3::allocationCheckpointFacts(scheduledCampaign,scheduledWorld).empty(),
            "an accepted supported investment became a new allocation question");
        economyWorld["towns"][0]["building_options"][0]["availability"].String()="missing_prerequisites";
        economyWorld["towns"][0]["building_options"][0]["requirements"]=json(R"(["allOf",5])");
        economyWorld["towns"][0]["building_options"].Vector().push_back(json(R"({"id":5,"supported":true,"availability":"allowed_now","cost":[0,0,0,0,0,0,900],"income_delta":[0,0,0,0,0,0,0],"requirements":["allOf"]})"));
        forecast=nullkiller3::forecastBranches(economyWorld,json("[0,0,0,0,0,0,1000]"));
        require(forecast["alternatives"][0]["build_day"].Integer()==5,"prerequisite cost or daily construction slot omitted");
        economyWorld["day"].Integer() = 7;
        forecast = nullkiller3::forecastBranches(economyWorld,json("[0,0,0,0,0,0,1000]"));
        require(forecast["weekly_growth_day"].Integer() == 8,"growth calendar skipped week boundary");
        auto defenseWorld=json(R"({"day":1,"heroes":[{"ref":"courier","army_value":1000}],"towns":[{"ref":"town_a","army_holder_ref":"town_a","defense_value":200},{"ref":"town_b","army_holder_ref":"town_b","defense_value":200}],"forecasts":{"threats":[{"town_ref":"town_a","source_ref":"enemy_a","advance_scenario_day":1,"army_interval":{"upper":1000}},{"town_ref":"town_b","source_ref":"enemy_b","advance_scenario_day":1,"army_interval":{"upper":1000}}],"routes":[{"target_ref":"town_a","own_arrivals":[{"hero_ref":"courier","day":1,"army_value":1000,"army_loss_estimate":0}]},{"target_ref":"town_b","own_arrivals":[{"hero_ref":"courier","day":1,"army_value":1000,"army_loss_estimate":0}]}]}})");
        auto defenses=nullkiller3::forecastDefenses(defenseWorld,initial);
        require(defenses[0]["conditional_force_value"].Integer()==1200 && defenses[1]["conditional_force_value"].Integer()==200,"one mobile army was promised to simultaneous fronts twice");
        defenseWorld["forecasts"]["routes"][0]["own_arrivals"][0]["day"].Integer()=2;
        defenses=nullkiller3::forecastDefenses(defenseWorld,initial);
        require(defenses[0]["status"].String()=="insufficient_current_force" && defenses[1]["status"].String()=="conditional_force_available","late arrival was counted as timely defense");
        defenseWorld["towns"][0]["army_holder_ref"].String()="courier";
        defenseWorld["towns"][0]["defense_value"].Integer()=1000;
        defenses=nullkiller3::forecastDefenses(defenseWorld,initial);
        require(defenses[0]["conditional_force_value"].Integer()==1000 && defenses[1]["conditional_force_value"].Integer()==200,"a garrison alias also defended another town");
        auto deliveryPlan=proposal;
        deliveryPlan["goals"].Vector().clear(); deliveryPlan["reserves"].Vector().clear();
        deliveryPlan["goals"].Vector().push_back(json(R"({"id":"deliver","kind":"reinforce_hero","actor_ref":"object:0","target_ref":"object:1","deadline_day":6,"priority":80,"building_id":-1,"min_army_value":5500,"depends_on":[],"required_capabilities":["land","transfer"],"complete_when":{"kind":"army_at_least","value":5500}})"));
        auto deliveryReply=reply; deliveryReply["plan"]=deliveryPlan;
        deliveryReply["assignments"]=json(R"([{"hero_ref":"object:0","role":"main"},{"hero_ref":"object:1","role":"reinforcement"}])");
        deliveryReply["reconsider_when"]=json(R"([{"goal_id":"deliver","kind":"deadline_missed"}])");
        require(nullkiller3::validateStrategicDecision(deliveryReply,request,world,initial,modelCandidate,reason),"courier role cannot bind to its delivery operation");
        require(modelCandidate.participantGoals("object:1").count("deliver"),"source courier is not committed to delivery");
        require(modelCandidate.reservedForce("object:1",world) == 500,"promised reinforcement can be donated elsewhere");
        require(modelCandidate.reservedForce("object:1",world,{},"deliver") == 0,"delivery cannot spend its own pledged army");
        require(modelCandidate.reservedForce("object:0",world) == 5000,"recipient contribution can be sent backwards");
        deliveryPlan["goals"].Vector().push_back(hold);
        nullkiller3::CampaignState guardedDelivery;
        require(guardedDelivery.accept(deliveryPlan,world,reason),reason.c_str());
        require(guardedDelivery.reservedForce("object:1",world) == 1500,"delivery pledge consumed the preservation floor");
        require(guardedDelivery.reservedForce("object:1",world,{},"deliver") == 1000,"handoff released a different goal's force floor");
        auto garrisonWorld=world;
        garrisonWorld["towns"][0]["army_holder_ref"].String()="object:1";
        auto townDelivery=deliveryPlan;townDelivery["goals"][0]["target_ref"].String()="object:2";
        nullkiller3::CampaignState sharedPool;
        require(sharedPool.accept(townDelivery,garrisonWorld,reason),reason.c_str());
        require(sharedPool.reservedForce("object:1",garrisonWorld)==1500,"town-source pledge did not protect its garrison hero's army");
        require(sharedPool.reservedForce("object:2",garrisonWorld)==1500,"one garrison army has different reserves under its two aliases");
        require(sharedPool.reservedForce("object:1",garrisonWorld,{},"deliver")==1000,"town-source handoff spent the garrison hero's preservation floor");
        auto doublePledge=townDelivery;doublePledge["revision"].Integer()=2;
        auto otherDelivery=doublePledge["goals"][0];otherDelivery["id"].String()="other_delivery";
        otherDelivery["actor_ref"].String()="object:5";otherDelivery["target_ref"].String()="object:1";
        doublePledge["goals"].Vector().push_back(otherDelivery);
        garrisonWorld["heroes"].Vector().push_back(json(R"({"ref":"object:5","army_value":1000})"));
        require(!sharedPool.accept(doublePledge,garrisonWorld,reason),"town and garrison aliases pledged the same army to independent recipients");
        const std::map<std::string,std::string> replacement{{"deliver","object:4"}};
        require(guardedDelivery.participantGoals("object:4",replacement).count("deliver"),"replacement is not committed to the same delivery");
        require(guardedDelivery.reservedForce("object:4",world,replacement) == 500,"replacement did not inherit the delivery pledge");
        world["heroes"][0]["army_value"].Integer()=5500;
        guardedDelivery.review(world);
        require(guardedDelivery.statuses()["deliver"]["state"].String()=="ready","recruitment alone falsely completed a named delivery");
        JsonNode receipt;
        receipt["goal"]=deliveryPlan["goals"][0]; receipt["day"]=world["day"];
        receipt["source_ref"].String()="object:1"; receipt["recipient_after"].Integer()=5500;
        world["confirmed_deliveries"].Vector().push_back(receipt);
        guardedDelivery.review(world);
        require(guardedDelivery.reservedForce("object:1",world) == 1000,"completed delivery retained its force pledge");
        nullkiller3::CampaignState restoredDelivery(guardedDelivery.save());
        require(restoredDelivery.statuses()["deliver"]["state"].String()=="completed","confirmed handoff was lost on load");
        auto forgedDelivery=guardedDelivery.save(); forgedDelivery.Struct().erase("delivery_completions");
        require(nullkiller3::CampaignState(forgedDelivery).plan().isNull(),"saved delivery completion without a handoff was replayed");
        std::cout << "NK3 dependency, conflict, reserves and save/load proof passed\n";
        return 0;
    }
    catch(const std::exception & error) { std::cerr << error.what() << '\n'; return 1; }
}
