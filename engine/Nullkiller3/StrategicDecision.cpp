#include "Global.h"
#include "StrategicDecision.h"

namespace nullkiller3
{
std::vector<StrategicSignal> helperHiredSignals(const CampaignState & campaign,const JsonNode & world,bool actionable)
{
    std::vector<StrategicSignal> result;
    for(const auto & receipt:world["confirmed_helper_hires"].Vector())
        for(const auto & goal:campaign.plan()["goals"].Vector())
            if(goal["kind"].String()=="hire_helper" && receipt["goal"]==goal
                && campaign.statuses()[goal["id"].String()]["state"].String()=="completed"
                && receipt["hero_type_id"].getType()==JsonNode::JsonType::DATA_INTEGER
                && goal["candidate_ref"].String()=="tavern:"+std::to_string(receipt["hero_type_id"].Integer()))
                for(const auto & hero:world["heroes"].Vector())
                    if(hero["ref"]==receipt["hero_ref"] && hero["hero_type_id"]==receipt["hero_type_id"])
                        result.push_back({"helper_hired:"+goal["id"].String(),receipt.toCompactString(),true,true,actionable,false});
    return result;
}

void retainDefenseExecutionBlockers(CampaignState & campaign, JsonNode & world, const JsonNode & blockers)
{
    for(const auto & goal:campaign.plan()["goals"].Vector())
    {
        const auto & id=goal["id"].String();
        const auto & blocker=blockers[id];
        if(blocker["revision"]==campaign.plan()["revision"]
            && blocker["reason"].String()=="hero_required_for_defense"
            && world["goal_statuses"][id]["state"].String()=="ready")
            campaign.blocked(id,"hero_required_for_defense");
    }
    world["goal_statuses"]=campaign.statuses();
}

JsonNode mainArmyIdle(const CampaignState & campaign,const JsonNode & world)
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
        if(why=="hero_required_for_defense")
        { result["reason"].String()="execution_blocked";result["goal_id"]=goal["id"];return result; }
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

std::vector<StrategicSignal> idleArmySignals(const CampaignState & campaign,const JsonNode & world,bool actionable)
{
    const auto idle=mainArmyIdle(campaign,world);
    if(!idleArmyNeedsReview(idle)) return {};
    JsonNode facts=offensiveCheckpoint(world["offensive_preparation"]);facts["safe_targets"].Vector();
    facts["reason"]=idle["reason"];facts["blocked_operations"].Vector();
    std::set<std::string> operations;
    for(const auto & goal:campaign.plan()["goals"].Vector())
        if(goal["actor_ref"]==idle["hero_ref"] && world["goal_statuses"][goal["id"].String()]["state"].String()=="blocked")
        {
            auto problem=operationIdentity(goal);
            problem["reason"]=world["goal_statuses"][goal["id"].String()]["reason"];
            problem["route_facts"].String()=campaign.routeFeedbackFacts(goal,world);
            operations.insert(problem.toCompactString());
        }
    for(const auto & operation:operations) facts["blocked_operations"].Vector().emplace_back(operation);
    std::set<std::string> refs;
    for(const auto & target:world["offensive_preparation"]["targets"].Vector())
        if(target["earliest_current_safe_day"].isNumber()) refs.insert(target["target_ref"].String());
    for(const auto & ref:refs) facts["safe_targets"].Vector().emplace_back(ref);
    // A consumed site changes the idle army's remaining useful agenda even
    // when it changes neither army strength nor known conquest routes.
    std::set<std::string> sites;
    for(const auto & site:world["objects"].Vector())
    {
        const auto & kind=site["kind"].String();
        if(!site["visible"].Bool() || !site["visited"].isBool() || site["visited"].Bool()
            || (kind!="scholar" && kind!="treasure_chest" && kind!="obelisk")) continue;
        for(const auto & route:world["forecasts"]["routes"].Vector()) if(route["target_ref"]==site["ref"])
            for(const auto & arrival:route["own_arrivals"].Vector())
                if(arrival["hero_ref"]==idle["hero_ref"] && arrival["army_loss_estimate"].isNumber()
                    && arrival["army_loss_estimate"].Float()==0 && arrival["day"].isNumber()
                    && arrival["day"].Integer()>=world["day"].Integer()
                    && arrival["day"].Integer()<=world["day"].Integer()+3)
                    sites.insert(site["ref"].String());
    }
    facts["safe_sites"].Vector();
    for(const auto & ref:sites) facts["safe_sites"].Vector().emplace_back(ref);
    auto basis=facts.toCompactString();if(basis.size()>8192) basis=offensiveCheckpoint(world["offensive_preparation"]).toCompactString();
    return {{"idle_army:"+idle["hero_ref"].String(),basis,true,true,actionable,false}};
}

JsonNode operationOwnFacts(const JsonNode & goal,const JsonNode & own,const std::string & source)
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
    for(const auto & target:own["scouting_options"].Vector()) if(target["ref"]==destination) route(target["own_arrivals"]);
    if(result["route_cost"].isNull())
    {
        JsonNode from,to;
        for(const auto * list:{"heroes","towns","visible_objects","frontier_options","scouting_options"})
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

JsonNode operationProgress(const JsonNode & previous,const JsonNode & objective,const JsonNode & facts,int64_t day)
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

std::vector<StrategicSignal> criticalTownLossSignals(const JsonNode & plan,const JsonNode & world,bool actionable)
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

std::vector<StrategicSignal> battleLossSignals(const JsonNode & plan, const JsonNode & memory, bool actionable)
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

std::vector<StrategicSignal> operationTransferSignals(const CampaignState & campaign,const JsonNode & world,const JsonNode & memory,bool actionable)
{
    std::map<std::string,std::string> latest;
    for(const auto & result:memory["recent_results"].Vector())
    {
        const auto & action=result["action"];
        if(action["kind"].String()!="army_transfer") continue;
        for(const auto & operation:action["affected_operations"].Vector())
            for(const auto & goal:campaign.plan()["goals"].Vector())
                if(campaign.holdsCommitment(goal["id"].String()) && operationIdentity(goal)==operation
                    && std::any_of(world["heroes"].Vector().begin(),world["heroes"].Vector().end(),[&](const auto & hero) {
                        return hero["ref"]==goal["actor_ref"] && hero["army_value"].Integer()<goal["min_army_value"].Integer();
                    }))
                {
                    JsonNode facts;facts["operation"]=operation;facts["recipient_ref"]=action["recipient_ref"];
                    facts["recipient_after"]=action["recipient_after"];facts["source_after"]=action["source_after"];
                    latest["operation_transfer:"+goal["target_ref"].String()]=facts.toCompactString();
                }
    }
    std::vector<StrategicSignal> signals;
    for(const auto & [question,facts]:latest) signals.push_back({question,facts,true,true,actionable,false});
    return signals;
}

std::string repairQuestionFacts(const JsonNode & plan, const JsonNode & blockers, const JsonNode & statuses)
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

bool validateStrategicDecision(const JsonNode & reply, const JsonNode & request,
    const JsonNode & freshWorld, const CampaignState & current, CampaignState & candidate, std::string & reason,
    JsonNode * nextIntentOut, const JsonNode * currentIntent)
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
    if(!reply.isStruct()) return reject("invalid_or_stale_strategic_identity");
    const bool previousHold=std::any_of(request["campaign"]["goals"].Vector().begin(),
        request["campaign"]["goals"].Vector().end(),[](const auto & goal) {
            return goal["kind"].String()=="defend_area" || goal["kind"].String()=="preserve_force";
        });
    const bool background=request["mode"].String()=="prepare_next_turn";
    const bool routine=background && !request["strategic_review"].Bool();
    auto replyShape=reply;
    if(background)
    {
        for(const auto * key:{"mode","execution_day","intent_revision"})
        {
            if(reply[key]!=request[key]) return reject("invalid_preparation_identity");
            replyShape.Struct().erase(key);
        }
        if(reply["identity"]["revision"]!=current.plan()["revision"]
            || request["intent_revision"]!=request["strategic_intent"]["revision"])
            return reject("stale_preparation_revision");
        if(routine && (reply["strategy_update"]["decision"].String()!="keep"
            || reply["assignments"]!=request["observation"]["strategy_assignments"]
            || (!reply["plan"].isNull() && reply["plan"]["policy"]!=current.plan()["policy"])))
            return reject("routine_changed_global_contract");
    }
    if(previousHold)
    {
        if(!replyShape.Struct().count("defense_exit")) return reject("missing_defense_exit");
        replyShape.Struct().erase("defense_exit");
        const auto & exit=reply["defense_exit"];
        if(!exit.isNull() && (!shape(exit,{"waiting_for","expected_gain","next_step"})
            || !text(exit["waiting_for"],640) || !text(exit["expected_gain"],640) || !text(exit["next_step"],640)))
            return reject("invalid_defense_exit");
    }
    if(!shape(replyShape, {"protocol", "request_id", "identity", "decision", "reason", "evidence_refs", "victory_method",
        "assignments", "alternatives", "reconsider_when", "plan", "usage", "strategy_update", "operation_focus", "decision_basis"})
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
        if(!trial.accept(reply["plan"], freshWorld, reason,background ? request["execution_day"].Integer() : 0)) return false;
        bool unfinished=false;
        for(const auto & [id,status]:trial.statuses().Struct())
            unfinished |= status["state"].String()!="completed";
        if(!unfinished) return reject("revision_contains_only_observed_completed_goals");
    }
    else if(reply["decision"].String() != "retain" || !reply["plan"].isNull() || current.plan().isNull())
        return reject("invalid_strategic_retention");
    trial.review(freshWorld);
    if(!trial.validateTownlessRecovery(freshWorld,reason)) return false;
    if(previousHold && reply["defense_exit"].isNull())
        for(const auto & goal:trial.plan()["goals"].Vector())
            if(goal["kind"].String()=="defend_area" || goal["kind"].String()=="preserve_force") return reject("missing_defense_exit");
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
                if((*goal)["actor_ref"]==assignment["hero_ref"] && ((*goal)["kind"].String()=="capture_target" || (*goal)["kind"].String()=="intercept_hero" || (*goal)["kind"].String()=="secure_resource")
                    && trial.statuses()[id]["state"].String()=="ready") supported=true;
            if(!supported)
            {
                const auto preparation=forecastCommitments(freshWorld,trial);
                for(const auto & [id,goal]:goals)
                    if((*goal)["actor_ref"]==assignment["hero_ref"] && (*goal)["kind"].String()=="reinforce_hero"
                        && trial.statuses()[id]["state"].String()=="ready")
                        for(const auto & delivery:preparation["deliveries"].Vector())
                            if(delivery["goal_id"].String()==id && delivery["status"].String()=="conditional") supported=true;
            }
            if(!supported) return reject("weaker_main_without_supported_offense");
        }
    for(const auto & [id, goal] : goals)
        if((*goal)["actor_ref"].isString())
        {
            const auto actor = (*goal)["actor_ref"].String();
            if(!roles.count(actor)) return reject("goal_actor_has_no_role");
        }
    const auto & alternatives = reply["alternatives"];
    if(!alternatives.isVector() || alternatives.Vector().size() < (routine ? 0 : 2) || alternatives.Vector().size() > (routine ? 0 : 4))
        return reject("missing_strategic_alternatives");
    const std::set<std::string> approaches{"economy", "expansion", "offense", "defense", "scouting"};
    std::set<std::string> compared;
    for(const auto & alternative : alternatives.Vector())
        if(!shape(alternative, {"approach", "benefit", "cost", "uncertainty"}) || !text(alternative["approach"])
            || !approaches.count(alternative["approach"].String()) || !compared.insert(alternative.toCompactString()).second
            || !text(alternative["benefit"],640) || !text(alternative["cost"],640) || !text(alternative["uncertainty"],640))
            return reject("invalid_strategic_alternative");
    bool defenseCompared=false;
    for(const auto & alternative:alternatives.Vector()) defenseCompared |= alternative["approach"].String()=="defense";
    for(const auto & defense:freshWorld["forecasts"]["defenses"].Vector())
        if(!routine && !defense["threats"].Vector().empty() && !defenseCompared
            && (defense["status"].String()=="insufficient_current_force" || defense["status"].String()=="unbounded_opposition"
                || defense["status"].String()=="observed_threat_timing_unknown"))
            return reject("exposed_town_without_defense_comparison");
    const auto & conditions = reply["reconsider_when"];
    if(!conditions.isVector() || conditions.Vector().empty() || conditions.Vector().size() > 12)
        return reject("missing_reconsideration_conditions");
    const std::set<std::string> predicates{"executor_lost", "deadline_missed", "route_not_established"};
    for(const auto & condition : conditions.Vector())
        if(!shape(condition, {"goal_id", "kind"}) || !text(condition["goal_id"],120) || !goals.count(condition["goal_id"].String())
            || !text(condition["kind"]) || !predicates.count(condition["kind"].String())) return reject("unknown_reconsideration_condition");
    // A direct hero handoff protects the recipient's current contribution:
    // native reserved exchange can merge or fill a slot, never swap it away.
    // Reject a proven incompatible handoff before it replaces the live plan.
    // Explicit preparation dependencies and town recruitment remain separate.
    for(const auto & [id,goal]:goals)
    {
        if(!trial.holdsCommitment(id) || (*goal)["kind"].String()!="reinforce_hero"
            || !(*goal)["depends_on"].Vector().empty()) continue;
        const JsonNode * donor=nullptr,* recipient=nullptr;
        for(const auto & hero:freshWorld["heroes"].Vector())
        {
            if(hero["ref"]==(*goal)["target_ref"]) donor=&hero;
            if(hero["ref"]==(*goal)["actor_ref"]) recipient=&hero;
        }
        if(!donor || !recipient || (*recipient)["army_value"].Integer()<=0
            || (*goal)["complete_when"]["value"].Integer()<=(*recipient)["army_value"].Integer()) continue;
        const auto & source=(*donor)["army_units"], & destination=(*recipient)["army_units"];
        if(!source.isVector() || source.Vector().empty() || !destination.isVector() || destination.Vector().size()!=7) continue;
        std::set<int64_t> types;
        bool known=true,matching=false;
        for(const auto & unit:destination.Vector())
        {
            known &= unit["creature"].isNumber() && unit["count"].Integer()>0;
            types.insert(unit["creature"].Integer());
        }
        for(const auto & unit:source.Vector())
        {
            known &= unit["creature"].isNumber() && unit["count"].Integer()>0;
            matching |= types.count(unit["creature"].Integer());
        }
        if(known && !matching)
        { reason="reinforcement_source_has_no_compatible_stack:"+id;return false; }
    }
    JsonNode nextIntent;
    if(!validateStrategicIntentUpdate(reply,request,freshWorld,trial.plan(),currentIntent ? *currentIntent : request["strategic_intent"],nextIntent,reason)) return false;
    if(!validateDecisionBasis(reply["decision_basis"],reply["operation_focus"],nextIntent,trial,freshWorld,reason)) return false;
    if(nextIntentOut) *nextIntentOut=nextIntent;
    candidate = trial;
    reason.clear();
    return true;
}
}
