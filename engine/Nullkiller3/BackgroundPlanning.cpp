#include "Global.h"
#include "BackgroundPlanning.h"

namespace nullkiller3
{
namespace
{
const JsonNode & find(const JsonNode & world,const char * list,const JsonNode & ref)
{
    static const JsonNode missing;
    for(const auto & item:world[list].Vector()) if(item["ref"]==ref) return item;
    return missing;
}
bool contains(const JsonNode & list,const JsonNode & item)
{ return std::find(list.Vector().begin(),list.Vector().end(),item)!=list.Vector().end(); }
void add(JsonNode & list,const JsonNode & item)
{ if(!contains(list,item)) list.Vector().push_back(item); }
bool completeVisibility(const JsonNode & world)
{
    const auto & size=world["map_size"], & counts=world["visible_tile_counts"];
    if(size.Vector().size()!=3 || !counts.isVector() || size[2].Integer()<=0
        || counts.Vector().size()!=size[2].Integer() || size[0].Integer()<=0 || size[1].Integer()<=0) return false;
    const auto cells=size[0].Integer()*size[1].Integer();
    return std::all_of(counts.Vector().begin(),counts.Vector().end(),[&](const auto & count){return count.isNumber() && count.Integer()==cells;});
}
bool safeExposure(const JsonNode & exposure,const JsonNode & world)
{
    if(exposure["status"].String()!="conditional_unchanged_route"
        || !exposure["omitted_visible_enemy_count"].isNumber() || exposure["omitted_visible_enemy_count"].Integer()!=0)
        return false;
    // An empty observed threat list under fog is not a positive assessment.
    // Complete current native visibility, or the per-front evidence below,
    // supplies a conditional basis; live admission still rechecks it.
    if(!exposure["visible_threats"].isVector()
        || (exposure["visible_threats"].Vector().empty() && !completeVisibility(world))) return false;
    for(const auto & threat:exposure["visible_threats"].Vector())
    {
        const auto & approach=threat["known_land_approach"];
        // Unknown connectivity/timing never grants background safety. A known
        // neutral barrier is conditional protection, not a new enemy ETA.
        if(approach["status"].String()!="neutral_encounter_required_on_known_land_connections") return false;
    }
    return true;
}
bool safeTown(const JsonNode & world,const JsonNode & ref)
{
    for(const auto & defense:world["forecasts"]["defenses"].Vector()) if(defense["town_ref"]==ref)
    {
        bool guarded=!defense["unconfirmed_threats"].Vector().empty();
        for(const auto & threat:defense["unconfirmed_threats"].Vector())
            guarded &= threat["assessment"].String()=="guarded_approach"
                && threat["neutral_screen"]["status"].String()=="neutral_encounter_required_on_known_land_connections";
        if(!defense["unconfirmed_threats"].Vector().empty() && !guarded) return false;
        if(defense["status"].String()=="no_observed_front")
            return defense["threats"].isVector() && defense["threats"].Vector().empty() && (guarded || completeVisibility(world));
        // A current stationary garrison covering the native visible upper
        // bound does not rely on diverting a commander or future purchases.
        return defense["status"].String()=="conditional_force_available"
            && defense["opposing_upper_sum"].isNumber() && defense["opposing_upper_sum"].Integer()>0
            && defense["garrison_value"].isNumber() && defense["garrison_value"].Integer()>=defense["opposing_upper_sum"].Integer()
            && defense["scenario_deadline_day"].isNumber();
    }
    return false;
}
bool safeRoute(const JsonNode & world,const JsonNode & actor,const JsonNode & target)
{
    for(const auto & entry:world["forecasts"]["routes"].Vector()) if(entry["target_ref"]==target)
        for(const auto & route:entry["own_arrivals"].Vector())
            if(route["hero_ref"]==actor && route["army_value"].isNumber() && route["army_value"].Integer()>0
                && route["army_loss_estimate"].isNumber() && route["army_loss_estimate"].Integer()==0
                && safeExposure(route["end_turn_exposure"],world)) return true;
    return false;
}
bool safeGoal(const JsonNode & goal,const JsonNode & request,const JsonNode & world)
{
    if(!contains(request["allowed_target_refs"],goal["target_ref"])) return false;
    const auto & kind=goal["kind"].String();
    if(kind=="develop_town" || kind=="hire_helper") return safeTown(world,goal["target_ref"]);
    if(!contains(request["allowed_actor_refs"],goal["actor_ref"])) return false;
    const auto & actor=find(world,"heroes",goal["actor_ref"]);
    if(actor.isNull() || actor["movement"].Integer()<=100) return false;
    if(kind=="prepare_garrison") return safeTown(world,goal["target_ref"]) && safeRoute(world,goal["actor_ref"],goal["target_ref"]);
    if(kind=="reinforce_hero") return safeRoute(world,goal["actor_ref"],goal["target_ref"]);
    if(kind!="secure_resource" && kind!="visit_site" && kind!="capture_target") return false;
    return safeRoute(world,goal["actor_ref"],goal["target_ref"]);
}
JsonNode strategicBasis(const JsonNode & world)
{
    JsonNode result;
    for(const auto * key:{"player","enemy_players","victory","rules","daily_income","confirmed_deliveries",
        "confirmed_interceptions","confirmed_site_visits","observed_passages"}) result[key]=world[key];
    for(auto hero:world["heroes"].Vector())
    {
        // Verify calendar refill independently, then exclude it from basis.
        hero.Struct().erase("movement");hero.Struct().erase("mana");
        result["heroes"][hero["ref"].String()]=hero;
    }
    for(auto town:world["towns"].Vector())
    {
        for(auto & option:town["building_options"].Vector())
            for(const auto * field:{"state","availability"}) option.Struct().erase(field);
        for(auto & option:town["hiring_options"].Vector())
            for(const auto * field:{"funds_available","can_recruit","availability"}) option.Struct().erase(field);
        town.Struct().erase("recruitment_options");
        result["towns"][town["ref"].String()]=town;
    }
    for(auto object:world["objects"].Vector())
    {
        for(const auto * field:{"last_seen_day","age_days"}) object.Struct().erase(field);
        if(object["kind"].String()=="hero" && contains(world["enemy_players"],object["owner"]))
            object.Struct().erase("position"); // Approach question below owns material movement.
        result["objects"][object["ref"].String()]=object;
    }
    for(const auto & defense:world["forecasts"]["defenses"].Vector())
        result["fronts"][defense["town_ref"].String()].String()=defenseSignal(defense,true).facts;
    return result;
}
}
JsonNode preparationScope(const JsonNode & world,const CampaignState & campaign)
{
    JsonNode scope;scope["actors"].Vector();scope["targets"].Vector();scope["needs"].Vector();
    for(const auto & route:world["forecasts"]["routes"].Vector())
        for(const auto & arrival:route["own_arrivals"].Vector())
            if(arrival["army_loss_estimate"].isNumber() && arrival["army_loss_estimate"].Integer()==0
                && arrival["army_value"].Integer()>0 && safeExposure(arrival["end_turn_exposure"],world))
            { add(scope["actors"],arrival["hero_ref"]);add(scope["targets"],route["target_ref"]); }
    for(const auto & town:world["towns"].Vector()) if(safeTown(world,town["ref"])) add(scope["targets"],town["ref"]);
    for(const auto * list:{"heroes","towns"}) for(const auto & actor:world[list].Vector())
    {
        const bool hero=std::string(list)=="heroes";
        if(!(hero ? contains(scope["actors"],actor["ref"]) && actor["movement_per_day"].Integer()>100
            : contains(scope["targets"],actor["ref"]) && safeTown(world,actor["ref"]))) continue;
        bool assigned=false;
        for(const auto & goal:campaign.plan()["goals"].Vector()) if(campaign.holdsCommitment(goal["id"].String()))
            assigned |= hero ? goal["actor_ref"]==actor["ref"] || goal["target_ref"]==actor["ref"] : goal["target_ref"]==actor["ref"];
        bool useful=hero;
        if(!hero) for(const auto & option:actor["building_options"].Vector())
            useful |= option["supported"].Bool() && !contains(actor["buildings"],option["id"]);
        if(!assigned && useful) { JsonNode need;need["ref"]=actor["ref"];need["kind"].String()=hero ? "hero" : "town";scope["needs"].Vector().push_back(need); }
    }
    return scope;
}
bool preparationStrategyFresh(const JsonNode & observed,const JsonNode & fresh)
{
    if(fresh["day"].Integer()!=observed["day"].Integer()+1 || strategicBasis(observed)!=strategicBasis(fresh)) return false;
    for(const auto & hero:observed["heroes"].Vector())
    {
        const auto & current=find(fresh,"heroes",hero["ref"]);
        if(!current["movement"].isNumber() || current["movement"]!=current["movement_per_day"])
            return false;
        // Mana recovery has no complete quote here; uncertainty rejects review.
        if(current["mana"]!=hero["mana"]) return false;
    }
    if(observed["resources"].Vector().size()!=7 || fresh["resources"].Vector().size()!=7) return false;
    const auto income=forecastDailyIncome(observed,fresh["day"].Integer(),observed["daily_income"]);
    for(int i=0;i<7;++i) if(fresh["resources"][i].Integer()!=observed["resources"][i].Integer()+income[i].Integer()) return false;
    for(const auto & town:observed["towns"].Vector())
    {
        const auto & current=find(fresh,"towns",town["ref"]);
        if(town["recruitment_options"].Vector().size()!=current["recruitment_options"].Vector().size()) return false;
        for(auto unit:town["recruitment_options"].Vector())
        {
            const auto at=std::find_if(current["recruitment_options"].Vector().begin(),current["recruitment_options"].Vector().end(),[&](const auto & value){return value["creature"]==unit["creature"];});
            if(at==current["recruitment_options"].Vector().end()) return false;
            if((fresh["day"].Integer()-1)%7==0) unit["available"].Integer()+=unit["weekly_growth"].Integer();
            if(unit!=*at) return false;
        }
    }
    return true;
}
bool admitPreparation(const JsonNode & reply,const JsonNode & request,const JsonNode & observed,const JsonNode & fresh,
    const CampaignState & current,const JsonNode & intent,const JsonNode & pending,
    CampaignState & candidate,JsonNode & nextIntent,JsonNode & derived,JsonNode & groups,std::string & reason)
{
    auto reject=[&](const char * why){reason=why;return false;};
    if(request["mode"].String()!="prepare_next_turn" || request["execution_day"]!=fresh["day"]
        || request["identity"]["day"]!=request["observation"]["day"]
        || request["identity"]["revision"]!=current.plan()["revision"]
        || request["intent_revision"]!=intent["revision"]) return reject("stale_preparation");
    // Validate the unmodified wire decision against its original facts and
    // future deadline contract before considering any native-derived subset.
    CampaignState checked;JsonNode checkedIntent;
    if(!validateStrategicDecision(reply,request,request["observation"],current,checked,reason,&checkedIntent,&intent)) return false;
    const bool revise=reply["strategy_update"]["decision"].String()=="revise";
    if(!revise && (reply["assignments"]!=request["observation"]["strategy_assignments"]
        || (!reply["plan"].isNull() && reply["plan"]["policy"]!=current.plan()["policy"])))
        return reject("keep_changed_global_contract");
    const bool strategyFresh=request["strategic_review"].Bool() && preparationStrategyFresh(observed,fresh);
    if(revise && !strategyFresh) return reject("changed_strategic_basis");
    if(reply["decision"].String()=="retain")
    {
        for(const auto & goal:current.plan()["goals"].Vector())
            if(goal["deadline_day"].Integer()<fresh["day"].Integer()
                || current.statuses()[goal["id"].String()]["state"].String()=="blocked")
                return reject("invalid_retained_commitment");
        if(!strategyFresh) return reject("retained_preparation_without_fresh_strategy");
        derived=reply;
        return validateStrategicDecision(derived,request,fresh,current,candidate,reason,&nextIntent,&intent);
    }
    derived=reply;
    auto & plan=derived["plan"];
    std::map<std::string,JsonNode> carried;
    if(!revise)
    {
        plan["policy"]=current.plan()["policy"];
        derived["assignments"]=request["observation"]["strategy_assignments"];
        for(const auto & goal:current.plan()["goals"].Vector())
        {
            const auto state=current.statuses()[goal["id"].String()]["state"].String();
            if(state=="completed")
            {
                for(const auto & dependent:current.plan()["goals"].Vector())
                    if(contains(dependent["depends_on"],goal["id"])) return reject("completed_prerequisite_requires_review");
                continue;
            }
            if(state=="cancelled" || goal["deadline_day"].Integer()<fresh["day"].Integer()
                || !current.holdsCommitment(goal["id"].String())) return reject("invalid_carried_commitment");
            carried[goal["id"].String()]=goal;
        }
    }
    if(!pending.isNull())
    {
        bool preserved=false;
        for(const auto & goal:plan["goals"].Vector())
            preserved |= CampaignState::sameGoal(goal,pending["action"]["goal"]);
        if(revise && !preserved) return reject("pending_command_changed");
    }
    std::vector<JsonNode> proposals;
    for(const auto & goal:plan["goals"].Vector())
    {
        const auto id=goal["id"].String();
        if(carried.count(id)) { if(!CampaignState::sameGoal(goal,carried.at(id))) return reject("changed_carried_goal");continue; }
        bool completed=false;
        for(const auto & old:current.plan()["goals"].Vector()) if(old["id"]==goal["id"])
            completed=current.statuses()[id]["state"].String()=="completed" && CampaignState::sameGoal(old,goal);
        if(!completed) proposals.push_back(goal);
    }
    // Dependencies and physical participants form atomic groups. A shared
    // treasury or intersecting route does not join independent operations.
    std::vector<size_t> parent(proposals.size());for(size_t i=0;i<parent.size();++i) parent[i]=i;
    auto root=[&](size_t i){while(parent[i]!=i)i=parent[i];return i;};
    auto pools=[&](const JsonNode & goal) {
        std::set<std::string> refs;
        if(goal["actor_ref"].isString()) refs.insert(CampaignState::armyPool(goal["actor_ref"].String(),fresh));
        if(goal["kind"].String()=="reinforce_hero" || goal["kind"].String()=="prepare_garrison" || goal["kind"].String()=="hire_helper")
            refs.insert(CampaignState::armyPool(goal["target_ref"].String(),fresh));
        if(goal["job_ref"].isString()) refs.insert(CampaignState::armyPool(goal["job_ref"].String(),fresh));
        return refs;
    };
    for(size_t i=0;i<proposals.size();++i) for(size_t j=0;j<i;++j)
    {
        const auto a=pools(proposals[i]),b=pools(proposals[j]);
        bool linked=contains(proposals[i]["depends_on"],proposals[j]["id"]) || contains(proposals[j]["depends_on"],proposals[i]["id"]);
        for(const auto & ref:a) linked |= b.count(ref)>0;
        if(linked) parent[root(i)]=root(j);
    }
    std::vector<std::vector<JsonNode>> ordered;
    std::map<size_t,size_t> positions;
    for(size_t i=0;i<proposals.size();++i)
    {
        auto [at,inserted]=positions.emplace(root(i),ordered.size());
        if(inserted) ordered.emplace_back();
        ordered[at->second].push_back(proposals[i]);
    }
    JsonNode selected=plan;selected["goals"].Vector().clear();selected["reserves"].Vector().clear();
    for(const auto & old:current.plan()["goals"].Vector()) if(carried.count(old["id"].String())) selected["goals"].Vector().push_back(old);
    for(const auto & reserve:current.plan()["reserves"].Vector()) if(carried.count(reserve["goal_id"].String())) selected["reserves"].Vector().push_back(reserve);
    for(const auto & group:ordered)
    {
        JsonNode receipt;receipt["goal_ids"].Vector();bool safe=true;
        for(const auto & goal:group)
        { receipt["goal_ids"].Vector().push_back(goal["id"]);safe &= safeGoal(goal,request,fresh); }
        auto trial=selected;
        for(const auto & goal:group) trial["goals"].Vector().push_back(goal);
        for(const auto & reserve:plan["reserves"].Vector()) if(contains(receipt["goal_ids"],reserve["goal_id"])) trial["reserves"].Vector().push_back(reserve);
        CampaignState value=current;std::string failure;
        bool accepted=safe && trial["goals"].Vector().size()<=12 && value.accept(trial,fresh,failure);
        if(accepted) for(const auto & goal:group)
        {
            const auto & status=value.statuses()[goal["id"].String()];
            if(status["state"].String()=="completed" || status["state"].String()=="blocked") {accepted=false;failure="goal_not_live_ready";break;}
        }
        receipt["accepted"].Bool()=accepted;
        receipt["reason"].String()=accepted ? "live_admission" : !safe ? "unsafe_or_unknown_route" : failure.empty() ? "goal_capacity" : failure;
        groups.Vector().push_back(receipt);
        if(!accepted && revise) return reject("revised_group_rejected");
        if(accepted) selected=trial;
    }
    if(selected["goals"].Vector().empty()) return reject("no_admitted_goals");
    plan=selected;
    auto hasGoal=[&](const JsonNode & id){for(const auto & goal:plan["goals"].Vector()) if(goal["id"]==id)return true;return false;};
    std::erase_if(derived["reconsider_when"].Vector(),[&](const auto & item){return !hasGoal(item["goal_id"]);});
    std::erase_if(derived["operation_focus"]["bindings"].Vector(),[&](const auto & binding){return !hasGoal(binding["goal_id"]);});
    if(!revise) for(const auto & binding:intent["bindings"].Vector())
        if(hasGoal(binding["goal"]["id"]) && carried.count(binding["goal"]["id"].String()))
        {
            // Keep existing semantic milestone bindings; never reinterpret them.
            for(const auto & proposed:derived["operation_focus"]["bindings"].Vector())
                if(proposed["goal_id"]==binding["goal"]["id"] && proposed["milestone_id"]!=binding["milestone_id"])
                    return reject("changed_carried_focus");
            JsonNode retained;retained["goal_id"]=binding["goal"]["id"];retained["milestone_id"]=binding["milestone_id"];
            add(derived["operation_focus"]["bindings"],retained);
        }
    if(derived["reconsider_when"].Vector().empty()) return reject("no_admitted_reconsideration");
    return validateStrategicDecision(derived,request,fresh,current,candidate,reason,&nextIntent,&intent);
}
}
