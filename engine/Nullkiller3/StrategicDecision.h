#pragma once
#include "CampaignState.h"
#include "RequestArbiter.h"
#include "Forecasts.h"
#include "OffensivePreparation.h"
#include <cmath>

namespace nullkiller3
{
// Policy changes alone do not create new enemy evidence. Both callers use
// this same identity; new enemy refs or strength intervals still trigger review.
inline StrategicSignal defenseSignal(const JsonNode & defense,bool actionable)
{
    std::string facts=defense["status"].String()+":";
    for(const auto & threat:defense["threats"].Vector())
    {
        facts+=threat["source_ref"].String()+":"+threat["army_interval"].toCompactString()+";";
        if(!threat["neutral_screen"].isNull())
            facts+=threat["neutral_screen"]["status"].String()+":"+threat["neutral_screen"]["example_guard_refs"].toCompactString()+";";
    }
    return {"defense:"+defense["town_ref"].String(),facts,true,true,actionable,true};
}
inline std::vector<StrategicSignal> allocationCheckpointSignals(const CampaignState & campaign,
    const JsonNode & world,const JsonNode & baseline,bool actionable)
{
    if(campaign.plan().isNull() || baseline.isNull()) return {};
    const auto day=world["day"].Integer();
    const auto week=std::max<int64_t>(1,world["days_in_week"].Integer());
    if(day<baseline["day"].Integer()+3 && day%week!=0) return {};
    const auto facts=allocationCheckpointFacts(campaign,world);
    if(facts.empty() || facts==baseline["facts"].String()) return {};
    return {{"checkpoint:allocation",facts,true,true,actionable,false}};
}
inline std::vector<StrategicSignal> offensiveCheckpointSignals(const JsonNode & world,const JsonNode & baseline,bool actionable)
{
    const auto & previous=baseline["offense"];
    const auto now=offensiveCheckpoint(world["offensive_preparation"]);
    if(!previous.isNull() && previous["hero_ref"]==now["hero_ref"] && previous["army_value"].Integer()>0
        && now["army_value"].Integer()>=previous["army_value"].Integer()*1.25)
        if(!world["offensive_preparation"]["targets"].Vector().empty())
            return {{"checkpoint:offense",now.toCompactString(),true,true,actionable,false}};
    return {};
}
inline JsonNode operationIdentity(const JsonNode & goal)
{
    JsonNode result;
    for(const auto * field:{"kind","actor_ref","target_ref","min_army_value","required_capabilities","complete_when"}) result[field]=goal[field];
    return result;
}
inline JsonNode mainArmyIdle(const CampaignState & campaign,const JsonNode & world)
{
    const auto & preparation=world["offensive_preparation"];
    JsonNode result;result["hero_ref"]=preparation["hero_ref"];result["army_value"]=preparation["army_value"];
    result["movement"]=preparation["movement"];result["reason"].String()="movement_spent";
    const JsonNode * hero=nullptr;
    for(const auto & own:world["heroes"].Vector()) if(own["ref"]==result["hero_ref"]) hero=&own;
    if(!hero || (*hero)["movement"].Integer()<std::max<int64_t>(500,(*hero)["movement_per_day"].Integer()/2)) return result;
    result["reason"].String()="no_task";
    bool assigned=false,ready=false,routeBlocked=false,preparing=false;
    for(const auto & goal:campaign.plan()["goals"].Vector())
    {
        if(goal["actor_ref"]!=result["hero_ref"] || !campaign.holdsCommitment(goal["id"].String())) continue;
        assigned=true;
        const auto & status=world["goal_statuses"][goal["id"].String()];
        ready |= status["state"].String()=="ready";
        const auto & why=status["reason"].String();
        routeBlocked |= why=="no_supported_route" || why=="route_not_established" || why=="deadline_unreachable";
        preparing |= why=="dependency_unconfirmed";
        if(goal["kind"].String()=="reinforce_hero" && supportedDeliveryWait(world["forecasts"],goal,world["day"].Integer()))
        { result["reason"].String()="waiting_delivery";result["goal_id"]=goal["id"];return result; }
        if(goal["kind"].String()=="preserve_force" && why=="holding_preserved_force")
        { result["reason"].String()="defense";result["goal_id"]=goal["id"];return result; }
        if((goal["kind"].String()=="defend_area" || goal["kind"].String()=="preserve_force")
            && status["state"].String()=="ready")
            for(const auto & town:world["towns"].Vector())
                if(town["ref"]==goal["target_ref"] && town["position"]==(*hero)["position"])
                { result["reason"].String()="defense";result["goal_id"]=goal["id"];return result; }
    }
    if(assigned) result["reason"].String()=ready ? "operation_pending" : preparing ? "waiting_preparation" : routeBlocked ? "no_safe_route" : "operation_pending";
    return result;
}
inline std::vector<StrategicSignal> idleArmySignals(const CampaignState & campaign,const JsonNode & world,bool actionable)
{
    const auto idle=mainArmyIdle(campaign,world);
    if(idle["reason"].String()!="no_task") return {};
    JsonNode facts=offensiveCheckpoint(world["offensive_preparation"]);facts["safe_targets"].Vector();
    std::set<std::string> refs;
    for(const auto & target:world["offensive_preparation"]["targets"].Vector())
        if(target["earliest_current_safe_day"].isNumber()) refs.insert(target["target_ref"].String());
    for(const auto & ref:refs) facts["safe_targets"].Vector().emplace_back(ref);
    auto basis=facts.toCompactString();if(basis.size()>8192) basis=offensiveCheckpoint(world["offensive_preparation"]).toCompactString();
    return {{"idle_army:"+idle["hero_ref"].String(),basis,true,true,actionable,false}};
}
// Only the operation's own participants, not routine treasury changes or
// unrelated construction, establish whether an acknowledged task progressed.
inline JsonNode operationOwnFacts(const JsonNode & goal,const JsonNode & own,const std::string & source)
{
    JsonNode result;result.Struct();
    for(const auto & hero:own["heroes"].Vector())
        if(hero["ref"]==goal["actor_ref"] || (goal["kind"].String()=="reinforce_hero" && hero["ref"].String()==source))
        {
            auto & item=result[hero["ref"].String()];
            for(const auto * field:{"position","army_value","in_boat"}) item[field]=hero[field];
        }
    if(goal["kind"].String()=="reinforce_hero")
        for(const auto & town:own["towns"].Vector()) if(town["ref"].String()==source)
        {
            auto & item=result[source];item["army_holder_ref"]=town["army_holder_ref"];
            item["army_value"]=town["army_value"].isNull() ? town["defense_value"] : town["army_value"];
        }
    bool heroSource=false;
    for(const auto & hero:own["heroes"].Vector()) heroSource |= hero["ref"].String()==source;
    const bool courier=goal["kind"].String()=="reinforce_hero" && heroSource;
    const auto traveler=courier ? JsonNode(source) : goal["actor_ref"];
    const auto destination=courier ? goal["actor_ref"]
        : goal["kind"].String()=="reinforce_hero" ? JsonNode(source) : goal["target_ref"];
    result["route_subject"]["traveler"]=traveler;
    result["route_subject"]["destination"]=destination;
    auto route=[&](const JsonNode & arrivals) {
        for(const auto & arrival:arrivals.Vector())
            if(arrival["hero_ref"]==traveler && arrival["movement_cost"].isNumber())
            {
                const auto cost=arrival["movement_cost"].Float();
                if(std::isfinite(cost) && cost>=0 && cost<=2000)
                {
                    const auto measured=std::llround(cost*1000000);
                    if(result["route_cost"].isNull() || measured<result["route_cost"].Integer()) result["route_cost"].Integer()=measured;
                    result["route_subject"]["measure"].String()="native_travel_cost";
                }
            }
    };
    for(const auto & target:own["forecasts"]["routes"].Vector()) if(target["target_ref"]==destination) route(target["own_arrivals"]);
    for(const auto & target:own["frontier_options"].Vector()) if(target["ref"]==destination) route(target["own_arrivals"]);
    if(result["route_cost"].isNull())
    {
        JsonNode from,to;
        for(const auto * list:{"heroes","towns","visible_objects","frontier_options"})
            for(const auto & object:own[list].Vector())
            {
                if(object["ref"]==traveler) from=object["position"];
                if(object["ref"]==destination) to=object["position"];
            }
        if(from.isVector() && to.isVector() && from.Vector().size()==3 && to.Vector().size()==3 && from[2]==to[2])
        {
            result["route_cost"].Integer()=(std::abs(from[0].Integer()-to[0].Integer())+std::abs(from[1].Integer()-to[1].Integer()))*1000000;
            // Matches the existing frontier-repair heuristic. This measures
            // approach to a known target, never an ETA through unknown terrain.
            result["route_subject"]["measure"].String()="known_target_proximity";
        }
    }
    return result;
}
inline bool operationStalled(const JsonNode & progress,const JsonNode & forecasts,const std::string & id,int64_t day)
{
    if(progress.isNull() || day<progress["last_progress_day"].Integer()+2
        || progress["last_no_change_day"].isNull()
        || progress["last_no_change_day"].Integer()<progress["last_progress_day"].Integer()+1) return false;
    for(const auto & delivery:forecasts["deliveries"].Vector())
        if(delivery["goal_id"].String()==id && delivery["status"].String()=="conditional")
            for(const auto & purchase:delivery["recruitment_schedule"].Vector())
                if(purchase["day"].Integer()>=day) return false;
    return true;
}
inline JsonNode operationProgress(const JsonNode & previous,const JsonNode & objective,const JsonNode & facts,int64_t day)
{
    auto forceFacts=[](JsonNode value) {
        value.Struct().erase("route_cost");
        for(auto & [ref,item]:value.Struct()) if(item.isStruct())
        {
            item.Struct().erase("position");item.Struct().erase("in_boat");
        }
        return value;
    };
    JsonNode progress=previous;
    const bool newIntent=progress.isNull() || previous["objective"]!=objective;
    bool advanced=newIntent || forceFacts(previous["facts"])!=forceFacts(facts);
    if(newIntent) progress=JsonNode();
    if(previous["facts"]["route_subject"]!=facts["route_subject"])
        progress.Struct().erase("best_route_cost");
    if(facts["route_cost"].isNumber()
        && (progress["best_route_cost"].isNull() || facts["route_cost"].Integer()<progress["best_route_cost"].Integer()))
    {
        progress["best_route_cost"]=facts["route_cost"];
        const auto traveler=facts["route_subject"]["traveler"].isString()
            ? facts["route_subject"]["traveler"].String() : objective["actor_ref"].String();
        const auto destination=facts["route_subject"]["destination"].String();
        advanced |= facts[traveler]["position"]!=previous["facts"][traveler]["position"]
            || (!destination.empty() && facts[destination]["position"]!=previous["facts"][destination]["position"]);
    }
    // A smaller supported route cost advances only with actual movement. Daily
    // refill alone can improve the baseline, never the progress clock.
    // A lateral step, retreat or return to a previous best cannot keep
    // an otherwise ineffective operation alive forever.
    if(advanced) { progress["last_progress_day"].Integer()=day;progress.Struct().erase("last_no_change_day"); }
    progress["objective"]=objective;progress["facts"]=facts;
    return progress;
}
inline std::vector<StrategicSignal> criticalTownLossSignals(const JsonNode & plan,const JsonNode & world,bool actionable)
{
    std::vector<StrategicSignal> result;
    if(plan.isNull() || !world["towns"].isVector()) return result;
    for(const auto & ref:plan["policy"]["critical_towns"].Vector())
    {
        bool owned=false;
        for(const auto & town:world["towns"].Vector()) owned |= town["ref"]==ref;
        if(!owned) result.push_back({"critical_town_lost:"+ref.String(),"no_longer_owned",true,true,actionable,true});
    }
    return result;
}
// A battle's acknowledged own casualties can disprove the accepted risk
// estimate even if no preservation goal names that hero. Net army changes,
// transfers and unknown saved commands are not combat evidence.
inline std::vector<StrategicSignal> battleLossSignals(const JsonNode & plan, const JsonNode & memory, bool actionable)
{
    std::vector<StrategicSignal> result;
    if(plan.isNull()) return result;
    std::map<std::string,std::pair<int64_t,StrategicSignal>> latest;
    for(const auto & event:memory["recent_results"].Vector())
    {
        const auto & action=event["action"];
        if(action["kind"].String()!="battle" || action["source"].String()!="own_battle_result"
            || action["campaign_revision"]!=plan["revision"] || !action["actor_ref"].isString()
            || action["army_value_before"].getType()!=JsonNode::JsonType::DATA_INTEGER
            || action["army_loss_value"].getType()!=JsonNode::JsonType::DATA_INTEGER
            || action["army_value_before"].Integer()<=0 || action["army_loss_value"].Integer()<0
            || (event["outcome"].String()!="battle_won" && event["outcome"].String()!="battle_lost"
                && event["outcome"].String()!="battle_draw")) continue;
        if(event["outcome"].String()!="battle_lost"
            && action["army_loss_value"].Integer()<=action["army_value_before"].Integer()*plan["policy"]["max_loss_ratio"].Float()) continue;
        const auto facts=std::to_string(event["sequence"].Integer())+":"+event["outcome"].String()+":"
            +std::to_string(action["army_value_before"].Integer())+":"+std::to_string(action["army_loss_value"].Integer());
        const auto question="battle_loss:"+action["actor_ref"].String();
        const auto sequence=event["sequence"].Integer();
        if(!latest.count(question) || latest.at(question).first<sequence)
            latest[question]={sequence,{question,facts,true,true,actionable,true}};
    }
    for(const auto & [question,entry]:latest) result.push_back(entry.second);
    return result;
}
// A newly numbered plan is not a newly observed problem. Aggregate semantic
// blockers independently of goal IDs, deadlines, prose and revision numbers.
inline std::string repairQuestionFacts(const JsonNode & plan, const JsonNode & blockers, const JsonNode & statuses)
{
    std::set<std::string> problems;
    for(const auto & goal:plan["goals"].Vector())
    {
        const auto & blocker=blockers[goal["id"].String()];
        if(blocker["revision"]!=plan["revision"] || statuses[goal["id"].String()]["state"].String()=="completed") continue;
        JsonNode problem;
        for(const auto * field:{"kind","actor_ref","target_ref","min_army_value","required_capabilities","complete_when"}) problem[field]=goal[field];
        for(const auto * field:{"max_loss_ratio","allow_route_repair","allow_helper_replacement"}) problem["policy"][field]=plan["policy"][field];
        problem["reason"]=blocker["reason"];
        // A changed supported route duration is material; daily clock ticks,
        // model renumbering and a new deadline alone are not new route facts.
        if(blocker["reason"].String()=="deadline_unreachable" && !blocker["route_turns"].isNull())
            problem["route_turns"]=blocker["route_turns"];
        problems.insert(problem.toCompactString());
    }
    if(problems.empty()) return {};
    std::string facts;
    for(const auto & problem:problems) { facts+=problem;facts+='\n'; }
    return facts;
}
// Only this value contract can install model policy. The caller supplies a
// fresh world and matching identity after reacquiring the game-state lock.
inline bool validateStrategicDecision(const JsonNode & reply, const JsonNode & request,
    const JsonNode & freshWorld, const CampaignState & current, CampaignState & candidate, std::string & reason)
{
    auto reject = [&](const char * why) { reason = why; return false; };
    auto shape = [](const JsonNode & value, std::initializer_list<const char *> fields) {
        if(!value.isStruct() || value.Struct().size() != fields.size()) return false;
        for(const auto * field : fields) if(!value.Struct().count(field)) return false;
        return true;
    };
    auto text = [](const JsonNode & value, size_t limit = 160) {
        return value.isString() && !value.String().empty() && value.String().size() <= limit;
    };
    auto number = [](const JsonNode & value, int64_t low, int64_t high) {
        return value.getType() == JsonNode::JsonType::DATA_INTEGER && value.Integer() >= low && value.Integer() <= high;
    };
    if(!shape(reply, {"protocol", "request_id", "identity", "decision", "reason", "evidence_refs", "victory_method",
        "assignments", "alternatives", "reconsider_when", "plan", "usage"})
        || !number(reply["protocol"], 2, 2) || reply["request_id"] != request["request_id"]
        || reply["identity"] != request["identity"] || !text(reply["decision"]) || !text(reply["reason"],640)
        || !text(reply["victory_method"],640)) return reject("invalid_or_stale_strategic_identity");
    const auto & usage = reply["usage"];
    if(!shape(usage, {"input_tokens", "output_tokens", "known"}) || !usage["known"].isBool()
        || !number(usage["input_tokens"], 0, 1000000000) || !number(usage["output_tokens"], 0, 1000000000))
        return reject("invalid_strategic_usage");
    if(!reply["evidence_refs"].isVector() || reply["evidence_refs"].Vector().empty() || reply["evidence_refs"].Vector().size() > 8)
        return reject("missing_strategic_evidence");
    for(const auto & ref : reply["evidence_refs"].Vector())
        if(!text(ref) || std::find(request["evidence_refs"].Vector().begin(), request["evidence_refs"].Vector().end(), ref)
            == request["evidence_refs"].Vector().end()) return reject("unknown_strategic_evidence");
    CampaignState trial = current;
    if(reply["decision"].String() == "revise")
    {
        if(!trial.accept(reply["plan"], freshWorld, reason)) return false;
        bool unfinished=false;
        for(const auto & [id,status]:trial.statuses().Struct())
            unfinished |= status["state"].String()!="completed";
        if(!unfinished) return reject("revision_contains_only_observed_completed_goals");
    }
    else if(reply["decision"].String() != "retain" || !reply["plan"].isNull() || current.plan().isNull())
        return reject("invalid_strategic_retention");
    trial.review(freshWorld);
    std::map<std::string, const JsonNode *> goals;
    for(const auto & goal : trial.plan()["goals"].Vector()) goals[goal["id"].String()] = &goal;
    const auto & assignments = reply["assignments"];
    if(!assignments.isVector() || assignments.Vector().size() > 16) return reject("invalid_strategic_assignments");
    std::map<std::string, const JsonNode *> roles;
    int mainCount = 0;
    const std::set<std::string> allowedRoles{"main", "defender", "scout", "collector", "reinforcement"};
    for(const auto & assignment : assignments.Vector())
    {
        if(!shape(assignment, {"hero_ref", "role"}) || !text(assignment["hero_ref"])
            || !text(assignment["role"]) || !allowedRoles.count(assignment["role"].String())
            || !roles.emplace(assignment["hero_ref"].String(), &assignment).second) return reject("conflicting_strategic_roles");
        bool owned = false;
        for(const auto & hero : freshWorld["heroes"].Vector()) owned |= hero["ref"] == assignment["hero_ref"];
        if(!owned) return reject("strategic_role_not_owned");
        mainCount += assignment["role"].String() == "main";
    }
    if(mainCount > 1) return reject("competing_main_heroes");
    const JsonNode * strongest=nullptr;
    for(const auto & hero:freshWorld["heroes"].Vector())
        if(!strongest || hero["army_value"].Integer()>(*strongest)["army_value"].Integer()) strongest=&hero;
    for(const auto & assignment:assignments.Vector())
        if(strongest && assignment["role"].String()=="main" && assignment["hero_ref"]!=(*strongest)["ref"])
        {
            bool supported=false;
            for(const auto & [id,goal]:goals)
                if((*goal)["actor_ref"]==assignment["hero_ref"] && ((*goal)["kind"].String()=="capture_target" || (*goal)["kind"].String()=="secure_resource")
                    && trial.statuses()[id]["state"].String()=="ready") supported=true;
            if(!supported) return reject("weaker_main_without_supported_offense");
        }
    for(const auto & [id, goal] : goals)
        if((*goal)["actor_ref"].isString())
        {
            const auto actor = (*goal)["actor_ref"].String();
            if(!roles.count(actor)) return reject("goal_actor_has_no_role");
        }
    const auto & alternatives = reply["alternatives"];
    if(!alternatives.isVector() || alternatives.Vector().size() < 2 || alternatives.Vector().size() > 3)
        return reject("missing_strategic_alternatives");
    const std::set<std::string> approaches{"economy", "expansion", "offense", "defense", "scouting"};
    std::set<std::string> compared;
    for(const auto & alternative : alternatives.Vector())
        if(!shape(alternative, {"approach", "benefit", "cost", "uncertainty"}) || !text(alternative["approach"])
            || !approaches.count(alternative["approach"].String()) || !compared.insert(alternative.toCompactString()).second
            || !text(alternative["benefit"],640) || !text(alternative["cost"],640) || !text(alternative["uncertainty"],640))
            return reject("invalid_strategic_alternative");
    const auto & conditions = reply["reconsider_when"];
    if(!conditions.isVector() || conditions.Vector().empty() || conditions.Vector().size() > 12)
        return reject("missing_reconsideration_conditions");
    const std::set<std::string> predicates{"executor_lost", "deadline_missed", "route_not_established"};
    for(const auto & condition : conditions.Vector())
        if(!shape(condition, {"goal_id", "kind"}) || !text(condition["goal_id"],120) || !goals.count(condition["goal_id"].String())
            || !text(condition["kind"]) || !predicates.count(condition["kind"].String())) return reject("unknown_reconsideration_condition");
    candidate = trial;
    reason.clear();
    return true;
}
}
