#pragma once
#include "CampaignState.h"
#include "RequestArbiter.h"

namespace nullkiller3
{
inline bool intentFields(const JsonNode & value,std::initializer_list<const char *> fields)
{
    if(!value.isStruct() || value.Struct().size()!=fields.size()) return false;
    for(const auto * field:fields) if(!value.Struct().count(field)) return false;
    return true;
}
inline bool intentText(const JsonNode & value,size_t limit=640)
{ return value.isString() && !value.String().empty() && value.String().size()<=limit; }
inline bool intentInteger(const JsonNode & value,int64_t low,int64_t high)
{ return value.getType()==JsonNode::JsonType::DATA_INTEGER && value.Integer()>=low && value.Integer()<=high; }
inline const JsonNode & intentObject(const JsonNode & world,const JsonNode & ref)
{
    static const JsonNode missing;
    for(const auto * list:{"heroes","towns","objects","visible_objects"})
        for(const auto & object:world[list].Vector()) if(object["ref"]==ref) return object;
    for(const auto & object:world["map_overview"]["objects"].Vector()) if(object["ref"]==ref) return object;
    return missing;
}
inline const JsonNode & intentOwnedObject(const JsonNode & world,const char * list,const JsonNode & ref)
{
    static const JsonNode missing;
    for(const auto & object:world[list].Vector()) if(object["ref"]==ref) return object;
    return missing;
}
// Canonical JSON is a bounded collision-free predicate identity, including
// target, actor and value. It never includes model prose or operative deadlines.
inline std::string strategicPredicateFingerprint(const JsonNode & predicate)
{ return predicate.toCompactString(); }
inline const JsonNode & intentMilestone(const JsonNode & intent,const JsonNode & id)
{
    static const JsonNode missing;
    for(const auto & milestone:intent["milestones"].Vector()) if(milestone["id"]==id) return milestone;
    return missing;
}
inline bool validStrategicPredicate(const JsonNode & predicate)
{
    const std::set<std::string> predicates{"target_owned","building_present","army_at_least","site_visited","passage_explored"};
    if(!intentFields(predicate,{"kind","target_ref","actor_ref","value"}) || !intentText(predicate["kind"],120)
        || !predicates.count(predicate["kind"].String())) return false;
    const auto & kind=predicate["kind"].String();
    if(kind=="army_at_least")
    {
        if(!predicate["target_ref"].isNull() || !intentText(predicate["actor_ref"],160)
            || !intentInteger(predicate["value"],1,1000000000)) return false;
    }
    else
    {
        if(!intentText(predicate["target_ref"],160)) return false;
        if(kind=="site_visited" || kind=="passage_explored")
        {
            if(!intentText(predicate["actor_ref"],160) || !intentInteger(predicate["value"],0,0)) return false;
        }
        else if(!predicate["actor_ref"].isNull() || !intentInteger(predicate["value"],0,kind=="target_owned" ? 7 : 100000)) return false;
    }
    return true;
}
inline bool validIntentSelection(const JsonNode & selected,const JsonNode * world=nullptr,const JsonNode * evidence=nullptr)
{
    if(!intentFields(selected,{"objective","selection_reason","assumptions","milestones","reconsider_when"})
        || !intentText(selected["objective"]) || !intentText(selected["selection_reason"])
        || !selected["assumptions"].isVector() || selected["assumptions"].Vector().size()>8
        || !selected["milestones"].isVector() || selected["milestones"].Vector().size()<3 || selected["milestones"].Vector().size()>6
        || !selected["reconsider_when"].isVector() || selected["reconsider_when"].Vector().empty()
        || selected["reconsider_when"].Vector().size()>12) return false;
    for(const auto & assumption:selected["assumptions"].Vector())
    {
        if(!intentFields(assumption,{"text","evidence_refs","uncertainty"}) || !intentText(assumption["text"])
            || !intentText(assumption["uncertainty"]) || !assumption["evidence_refs"].isVector()
            || assumption["evidence_refs"].Vector().empty() || assumption["evidence_refs"].Vector().size()>8) return false;
        for(const auto & ref:assumption["evidence_refs"].Vector())
            if(!intentText(ref,160) || (evidence && std::find(evidence->Vector().begin(),evidence->Vector().end(),ref)==evidence->Vector().end())) return false;
    }
    std::map<std::string,const JsonNode *> milestones;
    for(const auto & milestone:selected["milestones"].Vector())
    {
        if(!intentFields(milestone,{"id","description","depends_on","complete_when"}) || !intentText(milestone["id"],120)
            || !intentText(milestone["description"]) || !milestone["depends_on"].isVector() || milestone["depends_on"].Vector().size()>5
            || !milestones.emplace(milestone["id"].String(),&milestone).second) return false;
        const auto & predicate=milestone["complete_when"];
        if(!validStrategicPredicate(predicate)) return false;
        const auto & kind=predicate["kind"].String();
        if(world)
        {
            if(!predicate["actor_ref"].isNull() && intentOwnedObject(*world,"heroes",predicate["actor_ref"]).isNull()) return false;
            if(!predicate["target_ref"].isNull())
            {
                const auto & object=intentObject(*world,predicate["target_ref"]);
                if(object.isNull() || (!object["visible"].isNull() && !object["visible"].Bool())) return false;
                const auto & objectKind=object["kind"].String();
                if(kind=="target_owned" && (predicate["value"]!=(*world)["player"]
                    || (objectKind!="town" && objectKind!="mine" && intentOwnedObject(*world,"towns",predicate["target_ref"]).isNull()))) return false;
                if(kind=="building_present" && objectKind!="town" && intentOwnedObject(*world,"towns",predicate["target_ref"]).isNull()) return false;
                if(kind=="passage_explored" && objectKind!="subterranean_gate") return false;
                if(kind=="site_visited" && objectKind!="artifact" && objectKind!="scholar" && objectKind!="treasure_chest" && objectKind!="obelisk"
                    && objectKind!="keymaster_tent" && objectKind!="border_guard" && objectKind!="border_gate") return false;
            }
        }
    }
    std::map<std::string,int> visit;
    std::function<bool(const std::string &)> acyclic=[&](const auto & id) {
        if(visit[id]==1) return false;
        if(visit[id]==2) return true;
        visit[id]=1;std::set<std::string> dependencies;
        for(const auto & ref:(*milestones.at(id))["depends_on"].Vector())
            if(!intentText(ref,120) || !milestones.count(ref.String()) || !dependencies.insert(ref.String()).second || !acyclic(ref.String())) return false;
        visit[id]=2;return true;
    };
    for(const auto & [id,milestone]:milestones) if(!acyclic(id)) return false;
    const std::set<std::string> conditions{"target_lost","actor_lost","base_threat","route_blocked","no_progress","milestone_completed"};
    for(const auto & condition:selected["reconsider_when"].Vector())
        if(!intentFields(condition,{"kind","milestone_id","reason"}) || !intentText(condition["kind"],120)
            || !conditions.count(condition["kind"].String()) || !intentText(condition["milestone_id"],120)
            || !milestones.count(condition["milestone_id"].String()) || !intentText(condition["reason"])) return false;
    return true;
}
inline bool strategicStateSatisfied(const JsonNode & predicate,const JsonNode & world)
{
    const auto & kind=predicate["kind"].String();
    if(kind=="army_at_least")
    {
        const auto & actor=intentOwnedObject(world,"heroes",predicate["actor_ref"]);
        return !actor.isNull() && actor["army_value"].Integer()>=predicate["value"].Integer();
    }
    const auto & town=intentOwnedObject(world,"towns",predicate["target_ref"]);
    if(kind=="building_present") return !town.isNull() && std::find(town["buildings"].Vector().begin(),town["buildings"].Vector().end(),predicate["value"])!=town["buildings"].Vector().end();
    if(kind=="target_owned")
    {
        const auto & object=intentObject(world,predicate["target_ref"]);
        return !town.isNull() || (!object.isNull() && object["visible"].Bool() && object["owner"]==predicate["value"] && predicate["value"]==world["player"]);
    }
    return false;
}
inline bool strategicReceiptMatches(const JsonNode & binding,const JsonNode & predicate,const JsonNode & receipt)
{
    const auto & goal=binding["goal"];
    if(!receipt.isStruct() || !CampaignState::sameGoal(receipt["goal"],goal)
        || !intentInteger(receipt["day"],1,goal["deadline_day"].Integer())
        || goal["target_ref"]!=predicate["target_ref"] || goal["actor_ref"]!=predicate["actor_ref"]
        || goal["complete_when"]["kind"]!=predicate["kind"] || goal["complete_when"]["value"]!=predicate["value"]) return false;
    if(predicate["kind"].String()=="site_visited")
        return goal["kind"].String()=="visit_site" && (receipt["artifact_visit"].isNull()
            || (artifactVisitConfirmed(receipt["artifact_visit"]) && receipt["artifact_visit"]["goal"]==goal
                && receipt["artifact_visit"]["day"]==receipt["day"]));
    if(predicate["kind"].String()=="passage_explored") return goal["kind"].String()=="explore_passage"
        && receipt["from"].isVector() && receipt["to"].isVector() && receipt["from"].Vector().size()==3 && receipt["to"].Vector().size()==3
        && receipt["from"][2]!=receipt["to"][2];
    return false;
}
inline void observeStrategicIntent(JsonNode & intent,const JsonNode & world)
{
    if(intent.isNull()) return;
    for(const auto & milestone:intent["milestones"].Vector())
    {
        const auto & id=milestone["id"].String();const auto & predicate=milestone["complete_when"];
        const auto fingerprint=strategicPredicateFingerprint(predicate);
        auto & progress=intent["progress"][id];
        if(progress["predicate_fingerprint"].String()!=fingerprint)
        {
            progress=JsonNode();progress["predicate_fingerprint"].String()=fingerprint;
            progress["state"].String()="needs_confirmation";
            progress["last_progress_day"]=intent["adopted_day"];
        }
        bool satisfied=strategicStateSatisfied(predicate,world);
        const auto & kind=predicate["kind"].String();
        if(kind=="site_visited" || kind=="passage_explored")
        {
            const auto * list=kind=="site_visited" ? "confirmed_site_visits" : "confirmed_passage_explorations";
            for(const auto & binding:intent["bindings"].Vector())
                if(binding["milestone_id"]==milestone["id"] && binding["predicate_fingerprint"].String()==fingerprint)
                    for(const auto & receipt:world[list].Vector())
                        if(strategicReceiptMatches(binding,predicate,receipt))
                        {
                            const auto & target=intentObject(world,predicate["target_ref"]);
                            const bool artifact=target["kind"].String()=="artifact" || progress["own_facts"]["target_kind"].String()=="artifact";
                            if(!artifact || (!receipt["artifact_visit"].isNull() && artifactVisitConfirmed(receipt["artifact_visit"]))) satisfied=true;
                        }
        }
        const bool hasStateView=kind=="army_at_least" ? world["heroes"].isVector()
            : (kind=="building_present" ? world["towns"].isVector()
                : (kind=="target_owned" ? world["towns"].isVector() && world["objects"].isVector() : true));
        if(hasStateView || progress["currently_satisfied"].isNull()) progress["currently_satisfied"].Bool()=satisfied;
        if(satisfied && progress["state"].String()!="completed")
        {
            progress["state"].String()="completed";progress["confirmed_day"]=world["day"];progress["last_progress_day"]=world["day"];
        }
        // Keep only native high-water facts relevant to this one predicate.
        // Army growth and actual approach can advance an unfinished milestone;
        // the daily clock and cosmetic operation replacement cannot do so.
        auto & facts=progress["own_facts"];facts.Struct();
        bool advanced=false;
        const auto & object=intentObject(world,predicate["target_ref"]);
        if(!object.isNull() && object["kind"].isString()) facts["target_kind"]=object["kind"];
        if(kind=="target_owned" && satisfied) facts["was_owned"].Bool()=true;
        if(kind=="building_present" && world["towns"].isVector())
        {
            const auto & town=intentOwnedObject(world,"towns",predicate["target_ref"]);
            if(!town.isNull() && (facts["building_count"].isNull() || int64_t(town["buildings"].Vector().size())>facts["building_count"].Integer()))
            { advanced=!facts["building_count"].isNull();facts["building_count"].Integer()=town["buildings"].Vector().size(); }
        }
        JsonNode actorRef=predicate["actor_ref"];
        if(actorRef.isNull()) for(const auto & binding:intent["bindings"].Vector())
            if(binding["milestone_id"]==milestone["id"] && binding["goal"]["actor_ref"].isString()) { actorRef=binding["goal"]["actor_ref"];break; }
        const auto & actor=intentOwnedObject(world,"heroes",actorRef);
        if(!actor.isNull())
        {
            if(kind=="army_at_least" && (facts["best_army_value"].isNull() || actor["army_value"].Integer()>facts["best_army_value"].Integer()))
            { advanced |= !facts["best_army_value"].isNull();facts["best_army_value"]=actor["army_value"]; }
            const auto & a=actor["position"], & b=object["position"];
            if(!object.isNull() && a.isVector() && b.isVector() && a.Vector().size()==3 && b.Vector().size()==3 && a[2]==b[2])
            {
                const auto distance=std::abs(a[0].Integer()-b[0].Integer())+std::abs(a[1].Integer()-b[1].Integer());
                if(facts["best_distance"].isNull() || distance<facts["best_distance"].Integer())
                { advanced |= !facts["best_distance"].isNull();facts["best_distance"].Integer()=distance; }
            }
        }
        if(advanced && progress["state"].String()!="completed") progress["last_progress_day"]=world["day"];
        progress["last_observed_day"]=world["day"];
    }
}
inline void bindStrategicOperation(JsonNode & intent,const JsonNode & focus,const JsonNode & plan,const JsonNode & pendingTask)
{
    if(intent.isNull()) return;
    JsonNode bindings;bindings.Vector();
    for(const auto & previous:intent["bindings"].Vector())
        if(!pendingTask.isNull() && previous["goal"]["id"]==pendingTask["action"]["goal_id"]
            && (pendingTask["action"]["goal"].isNull() || CampaignState::sameGoal(previous["goal"],pendingTask["action"]["goal"])))
            bindings.Vector().push_back(previous);
    for(const auto & binding:focus["bindings"].Vector())
        for(const auto & goal:plan["goals"].Vector()) if(goal["id"]==binding["goal_id"])
        {
            const auto & milestone=intentMilestone(intent,binding["milestone_id"]);
            if(milestone.isNull()) continue;
            JsonNode entry;entry["milestone_id"]=binding["milestone_id"];entry["predicate_fingerprint"].String()=strategicPredicateFingerprint(milestone["complete_when"]);
            entry["campaign_revision"]=plan["revision"];entry["goal"]=goal;
            if(std::find(bindings.Vector().begin(),bindings.Vector().end(),entry)==bindings.Vector().end()) bindings.Vector().push_back(entry);
        }
    intent["bindings"]=bindings;
}
inline bool validateStrategicIntentUpdate(const JsonNode & reply,const JsonNode & request,const JsonNode & freshWorld,
    const JsonNode & candidatePlan,const JsonNode & currentIntent,JsonNode & nextIntent,std::string & reason)
{
    auto reject=[&](const char * message) { reason=message;return false; };
    const auto & update=reply["strategy_update"];
    const int64_t revision=currentIntent.isNull() ? 0 : currentIntent["revision"].Integer();
    if(!intentFields(update,{"decision","base_revision","selected","change_reason"})
        || !intentInteger(update["base_revision"],0,2147483646) || update["base_revision"].Integer()!=revision
        || (request["strategic_intent"].isNull() ? 0 : request["strategic_intent"]["revision"].Integer())!=revision) return reject("invalid_or_stale_strategic_intent");
    JsonNode trial=currentIntent;
    if(update["decision"].String()=="keep")
    {
        if(currentIntent.isNull() || !update["selected"].isNull() || !update["change_reason"].isNull()) return reject("invalid_strategic_intent_keep");
    }
    else if(update["decision"].String()=="revise")
    {
        if(!intentText(update["change_reason"]) || (!validIntentSelection(update["selected"],&request["observation"],&request["evidence_refs"])
                || !validIntentSelection(update["selected"],&freshWorld,&request["evidence_refs"]))) return reject("invalid_strategic_intent_selection");
        trial=update["selected"];trial["version"].Integer()=1;trial["revision"].Integer()=revision+1;trial["adopted_day"]=freshWorld["day"];
        trial["progress"].Struct();trial["bindings"]=currentIntent["bindings"];
        if(trial["bindings"].isNull()) trial["bindings"].Vector();
        for(const auto & milestone:trial["milestones"].Vector())
        {
            const auto & previous=currentIntent["progress"][milestone["id"].String()];
            if(previous["predicate_fingerprint"].String()==strategicPredicateFingerprint(milestone["complete_when"])) trial["progress"][milestone["id"].String()]=previous;
        }
    }
    else return reject("invalid_strategic_intent_decision");
    const auto & focus=reply["operation_focus"];
    if(!intentFields(focus,{"revision","bindings"}) || focus["revision"]!=trial["revision"] || !focus["bindings"].isVector()
        || focus["bindings"].Vector().size()>12) return reject("invalid_strategic_operation_focus");
    std::set<std::string> goals;
    for(const auto & binding:focus["bindings"].Vector())
    {
        if(!intentFields(binding,{"goal_id","milestone_id"}) || !intentText(binding["goal_id"],120)
            || !intentText(binding["milestone_id"],120) || !goals.insert(binding["goal_id"].String()).second
            || intentMilestone(trial,binding["milestone_id"]).isNull()) return reject("unknown_strategic_operation_binding");
        bool found=false;
        for(const auto & goal:candidatePlan["goals"].Vector()) found |= goal["id"]==binding["goal_id"];
        if(!found) return reject("unknown_strategic_operation_goal");
    }
    observeStrategicIntent(trial,freshWorld);nextIntent=trial;reason.clear();return true;
}
inline bool validSavedStrategicIntent(const JsonNode & intent)
{
    if(intent.isNull()) return true;
    if(!intentFields(intent,{"version","revision","adopted_day","objective","selection_reason","assumptions","milestones","reconsider_when","progress","bindings"})
        || !intentInteger(intent["version"],1,1) || !intentInteger(intent["revision"],1,2147483647)
        || !intentInteger(intent["adopted_day"],1,2147483647) || !intent["progress"].isStruct()
        || intent["progress"].Struct().size()>6 || !intent["bindings"].isVector() || intent["bindings"].Vector().size()>32) return false;
    JsonNode selected;
    for(const auto * field:{"objective","selection_reason","assumptions","milestones","reconsider_when"}) selected[field]=intent[field];
    if(!validIntentSelection(selected)) return false;
    for(const auto & [id,progress]:intent["progress"].Struct())
    {
        const auto & milestone=intentMilestone(intent,JsonNode(id));
        if(milestone.isNull() || !progress.isStruct() || (progress.Struct().size()!=6 && progress.Struct().size()!=7)
            || progress["predicate_fingerprint"].String()!=strategicPredicateFingerprint(milestone["complete_when"])
            || !progress["own_facts"].isStruct() || progress["own_facts"].toCompactString().size()>2048
            || !progress["currently_satisfied"].isBool() || !intentInteger(progress["last_progress_day"],1,2147483647)
            || !intentInteger(progress["last_observed_day"],1,2147483647)) return false;
        if(progress["state"].String()=="completed")
        { if(!intentInteger(progress["confirmed_day"],1,2147483647)) return false; }
        else if(progress["state"].String()!="needs_confirmation" || !progress["confirmed_day"].isNull()) return false;
    }
    for(const auto & binding:intent["bindings"].Vector())
    {
        const auto & goal=binding["goal"];
        const std::set<std::string> kinds{"capture_target","secure_resource","develop_town","reinforce_hero","scout_frontier","scout_area",
            "visit_site","explore_passage","preserve_force","defend_area","prepare_garrison","intercept_hero","hire_helper"};
        if(!intentText(binding["predicate_fingerprint"],1024)) return false;
        const auto & encoded=binding["predicate_fingerprint"].String();
        JsonParsingSettings settings;settings.strict=true;settings.mode=JsonParsingSettings::JsonFormatMode::JSON;
        try
        {
            const JsonNode predicate(encoded.data(),encoded.size(),settings,"saved strategic predicate");
            if(!validStrategicPredicate(predicate) || predicate.toCompactString()!=encoded) return false;
        }
        catch(const std::exception &) { return false; }
        if(!intentFields(binding,{"milestone_id","predicate_fingerprint","campaign_revision","goal"})
            || !intentText(binding["milestone_id"],120) || !intentText(binding["predicate_fingerprint"],1024)
            || !intentInteger(binding["campaign_revision"],1,2147483647) || !goal.isStruct() || goal.toCompactString().size()>8192
            || !intentText(goal["id"],120) || !intentText(goal["kind"],120) || !kinds.count(goal["kind"].String()) || !intentInteger(goal["deadline_day"],1,2147483647)
            || !intentText(goal["target_ref"],160) || (!goal["actor_ref"].isNull() && !intentText(goal["actor_ref"],160))
            || !goal["complete_when"].isStruct()) return false;
    }
    return true;
}
inline std::set<std::string> strategicIntentTargetRefs(const JsonNode & intent)
{
    std::set<std::string> result;
    for(const auto & milestone:intent["milestones"].Vector())
        if(milestone["complete_when"]["target_ref"].isString()) result.insert(milestone["complete_when"]["target_ref"].String());
    return result;
}
inline std::vector<StrategicSignal> strategicIntentSignals(const JsonNode & intent,const JsonNode & world,bool actionable)
{
    if(intent.isNull()) return {{"initial_strategy","no_selected_course",true,true,actionable,false}};
    std::vector<StrategicSignal> result;
    for(const auto & condition:intent["reconsider_when"].Vector())
    {
        const auto & milestone=intentMilestone(intent,condition["milestone_id"]);const auto & predicate=milestone["complete_when"];
        const auto & progress=intent["progress"][condition["milestone_id"].String()];const auto & kind=condition["kind"].String();
        bool triggered=false;std::string evidence;
        if(kind=="milestone_completed") { triggered=progress["state"].String()=="completed";evidence=progress["confirmed_day"].toCompactString(); }
        if(kind=="actor_lost") triggered=predicate["actor_ref"].isString() && intentOwnedObject(world,"heroes",predicate["actor_ref"]).isNull();
        if(kind=="target_lost")
        {
            const auto & object=intentObject(world,predicate["target_ref"]);
            const auto & facts=progress["own_facts"];
            const bool ownedTownLost=facts["was_owned"].Bool() && facts["target_kind"].String()=="town"
                && world["towns"].isVector() && intentOwnedObject(world,"towns",predicate["target_ref"]).isNull();
            const bool confirmedGone=!object.isNull() && object["not_seen_at_last_position"].Bool() && !object["stale"].Bool();
            const bool capturedByEnemy=!object.isNull() && object["visible"].Bool() && object["owner"].isNumber()
                && object["owner"].Integer()<8 && object["owner"]!=world["player"] && facts["was_owned"].Bool();
            triggered=ownedTownLost || confirmedGone || capturedByEnemy;
            if(triggered) evidence=object["owner"].toCompactString();
        }
        if(kind=="no_progress")
        {
            triggered=progress["state"].String()!="completed" && world["day"].Integer()>=progress["last_progress_day"].Integer()+3;
            evidence=progress["own_facts"].toCompactString();
        }
        if(kind=="route_blocked")
            for(const auto & binding:intent["bindings"].Vector()) if(binding["milestone_id"]==condition["milestone_id"])
            {
                const auto & status=world["goal_statuses"][binding["goal"]["id"].String()];
                if(status["state"].String()=="blocked" && (status["reason"].String()=="route_not_established" || status["reason"].String()=="native_route_not_established"
                    || status["reason"].String()=="deadline_unreachable" || status["reason"].String()=="native_routes_filtered" || status["reason"].String()=="execution_blocked"))
                { triggered=true;evidence=status["reason"].String(); }
            }
        if(kind=="base_threat") for(const auto & defense:world["forecasts"]["defenses"].Vector())
            if(defense["status"].String()=="insufficient_current_force" || defense["status"].String()=="unbounded_opposition")
            {
                triggered=true;evidence+=defense["town_ref"].toCompactString()+":"+defense["status"].String();
                for(const auto & threat:defense["threats"].Vector()) evidence+=":"+threat["source_ref"].toCompactString()+":"+threat["army_interval"].toCompactString();
            }
        if(triggered) result.push_back({"strategy:"+kind+":"+condition["milestone_id"].String(),strategicPredicateFingerprint(predicate)+":"+evidence,true,true,actionable,kind=="actor_lost" || kind=="target_lost" || kind=="base_threat"});
    }
    return result;
}
}
