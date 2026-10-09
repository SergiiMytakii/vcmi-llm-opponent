#include "Global.h"
#include "CampaignState.h"

namespace nullkiller3
{
bool CampaignState::atPreservationRefuge(const JsonNode & goal,const JsonNode & world) const
{
    const auto & hero=find(world,"heroes",goal["actor_ref"]);
    if(hero.isNull() || hero["army_value"].Integer()<goal["min_army_value"].Integer()) return false;
    auto near=[&](const JsonNode & town) {
        const auto & a=hero["position"], & b=town["position"];
        return a.isVector() && b.isVector() && a.Vector().size()==3 && b.Vector().size()==3
            && a[2]==b[2] && std::abs(a[0].Integer()-b[0].Integer())<=1 && std::abs(a[1].Integer()-b[1].Integer())<=1;
    };
    const auto & original=find(world,"towns",goal["target_ref"]);
    if(!original.isNull()) return near(original);
    if(plan()["policy"]["allow_route_repair"].Bool())
        for(const auto & town:world["towns"].Vector()) if(near(town)) return true;
    return false;
}

bool CampaignState::finished(const JsonNode & goal, const JsonNode & world) const
{
    const auto & predicate = goal["complete_when"];
    const auto & hero = find(world, "heroes", goal["actor_ref"]);
    const auto & town = find(world, "towns", goal["target_ref"]);
    const auto & target = find(world, "objects", goal["target_ref"]);
    const auto & kind = predicate["kind"].String();
    if(kind == "helper_hired")
    {
        for(const auto & receipt:world["confirmed_helper_hires"].Vector())
            if(helperHireProved(goal,receipt))
            {
                const auto & hired=find(world,"heroes",receipt["hero_ref"]);
                if(!hired.isNull() && hired["hero_type_id"]==receipt["hero_type_id"]) return true;
            }
        return false;
    }
    if(kind == "building_present") return !town.isNull() && contains(town["buildings"], predicate["value"]);
    if(kind == "target_owned") return !town.isNull() || (!target.isNull() && target["visible"].Bool() && target["owner"] == world["player"]);
    if(kind == "army_at_least")
    {
        if(hero.isNull() || hero["army_value"].Integer()<predicate["value"].Integer()) return false;
        for(const auto & receipt:world["confirmed_deliveries"].Vector()) if(deliveryProved(goal,receipt)) return true;
        return false;
    }
    if(kind == "reserve_at_least") return contains(world["confirmed_resource_pickups"], goal["target_ref"])
        && world["resources"][6].Integer() >= predicate["value"].Integer();
    if(kind == "enemy_engaged")
    {
        auto proves=[&](const JsonNode & receipt) { return interceptionProved(goal,receipt); };
        if(proves(state["interception_completions"][goal["id"].String()])) return true;
        for(const auto & receipt:world["confirmed_interceptions"].Vector()) if(proves(receipt)) return true;
        return false;
    }
    if(kind == "garrison_at_least")
        return !town.isNull() && !hero.isNull() && town["army_holder_ref"]!=goal["actor_ref"]
            && town["defense_value"].Integer()>=predicate["value"].Integer()
            && hero["army_value"].Integer()>=goal["min_army_value"].Integer();
    if(kind == "site_visited")
    {
        for(const auto & receipt:world["confirmed_site_visits"].Vector()) if(siteProved(goal,receipt)) return true;
        return false;
    }
    if(kind == "area_observed")
    {
        for(const auto & area:world["observed_scout_areas"].Vector())
            if(area.isStruct() && area["target_ref"]==goal["target_ref"] && area["sight_radius"]==predicate["value"]) return true;
        return false;
    }
    if(kind == "frontier_observed") return contains(world["observed_frontiers"], goal["target_ref"]);
    if(kind == "passage_explored")
    {
        if(world["confirmed_passage_explorations"].isVector()) for(const auto & receipt:world["confirmed_passage_explorations"].Vector())
            if(passageProved(goal,receipt)) return true;
        return false;
    }
    if(kind == "force_preserved_until")
        return world["day"].Integer() >= predicate["value"].Integer() && !hero.isNull()
            && hero["army_value"].Integer() >= goal["min_army_value"].Integer();
    if(kind == "held_until")
    {
        if(world["day"].Integer()<predicate["value"].Integer() || town.isNull()) return false;
        int64_t stationed=std::max<int64_t>(0,town["defense_value"].Integer());
        const auto & visitor=find(world,"heroes",town["visiting_hero_ref"]);
        // A visiting owned hero also defends this town. Count each physical
        // army once; an aliased garrison is already the town's upper army.
        if(!visitor.isNull() && visitor["ref"]!=town["army_holder_ref"]
            && visitor["position"].isVector() && visitor["position"].Vector().size()==3
            && town["position"].isVector() && town["position"].Vector().size()==3
            && visitor["position"]==town["position"])
            stationed+=std::max<int64_t>(0,visitor["army_value"].Integer());
        return stationed>=goal["min_army_value"].Integer();
    }
    return false;
}

bool CampaignState::helperJobSupported(const JsonNode & goal,const JsonNode & world)
{
    if(!label(goal["job_ref"])) return false;
    const auto & role=goal["helper_role"].String();
    const auto & object=find(world,"objects",goal["job_ref"]);
    if(role=="reinforcement") return !find(world,"heroes",goal["job_ref"]).isNull();
    if(role=="defender") return !find(world,"towns",goal["job_ref"]).isNull();
    if(role=="collector") return !object.isNull()
        && (object["kind"].String()=="mine" || object["kind"].String()=="resource" || object["kind"].String()=="treasure_chest")
        && !(object["kind"].String()=="mine" && object["owner"]==world["player"]);
    if(role=="scout") return contains(world["frontiers"],goal["job_ref"])
        || !find(world,"scouting_options",goal["job_ref"]).isNull()
        || (!object.isNull() && object["visible"].Bool() && (object["kind"].String()=="scholar"
            || object["kind"].String()=="obelisk" || object["kind"].String()=="treasure_chest" || object["kind"].String()=="subterranean_gate" || object["kind"].String()=="portal"));
    return false;
}

CampaignState::CampaignState(const JsonNode & saved)
{
    // Unknown or malformed executable state is never migrated or replayed.
    if(saved.isNull()) return;
    restoreError = "invalid_saved_header";
    if(!saved.isStruct() || !integer(saved["version"], 3, 3) || !saved["validation_world"].isStruct()
        || !integer(saved["accepted_day"], 1, 2147483647) || !saved["statuses"].isStruct()) return;
    restoreError = "invalid_saved_world";
    const auto & sourceWorld = saved["validation_world"];
    if(!integer(sourceWorld["day"], 1, 2147483647) || sourceWorld["day"] != saved["accepted_day"]
        || !integer(sourceWorld["player"], 0, 7) || !resources(sourceWorld["resources"])
        || !sourceWorld["capabilities"].isVector()) return;
    for(const auto * list : {"frontiers", "observed_frontiers", "confirmed_resource_pickups"})
    {
        if(!sourceWorld[list].isNull() && !sourceWorld[list].isVector()) return;
        for(const auto & ref:sourceWorld[list].Vector()) if(!label(ref)) return;
    }
    if(!sourceWorld["observed_scout_areas"].isNull() && !sourceWorld["observed_scout_areas"].isVector()) return;
    for(const auto & area:sourceWorld["observed_scout_areas"].Vector())
        if(!fields(area,{"target_ref","sight_radius"}) || !label(area["target_ref"]) || !integer(area["sight_radius"],1,64)) return;
    if(!sourceWorld["scouting_options"].isNull() && !sourceWorld["scouting_options"].isVector()) return;
    if(!sourceWorld["confirmed_deliveries"].isNull() && !sourceWorld["confirmed_deliveries"].isVector()) return;
    if(!saved["delivery_completions"].isNull() && !saved["delivery_completions"].isStruct()) return;
    if(!sourceWorld["confirmed_passage_explorations"].isNull() && !sourceWorld["confirmed_passage_explorations"].isVector()) return;
    if(!saved["passage_completions"].isNull() && !saved["passage_completions"].isStruct()) return;
    if(!sourceWorld["confirmed_site_visits"].isNull() && !sourceWorld["confirmed_site_visits"].isVector()) return;
    if(!saved["site_completions"].isNull() && !saved["site_completions"].isStruct()) return;
    if(!saved["helper_hire_completions"].isNull() && !saved["helper_hire_completions"].isStruct()) return;
    if(!sourceWorld["confirmed_helper_hires"].isNull() && !sourceWorld["confirmed_helper_hires"].isVector()) return;
    for(const auto * list : {"heroes", "towns", "objects"})
    {
        if(!sourceWorld[list].isVector()) return;
        for(const auto & item : sourceWorld[list].Vector())
        {
            if(!item.isStruct() || !label(item["ref"])) return;
            if(!item["position"].isNull())
            {
                if(!item["position"].isVector() || item["position"].Vector().size()!=3) return;
                for(const auto & axis:item["position"].Vector()) if(!integer(axis,0,100000)) return;
            }
            if(std::string(list)=="towns")
            {
                if(!item["army_holder_ref"].isNull() && !label(item["army_holder_ref"])) return;
                if(!item["buildings"].isVector()) return;
                for(const auto & building:item["buildings"].Vector()) if(!integer(building,0,100000)) return;
                if(!item["building_options"].isNull() && !item["building_options"].isVector()) return;
                for(const auto & option:item["building_options"].Vector())
                    if(!option.isStruct() || !integer(option["id"],0,100000) || !option["supported"].isBool()) return;
            }

            if(std::string(list) == "heroes" && !integer(item["army_value"], 0, 1000000000)) return;
            if(std::string(list) == "towns" && !item["buildings"].isVector()) return;
            if(std::string(list) == "objects" && (!label(item["kind"])
                || !integer(item["owner"], -2, 7) || !item["visible"].isBool())) return;
        }
    }
    for(const auto & town:sourceWorld["towns"].Vector())
        if(!town["army_holder_ref"].isNull() && town["army_holder_ref"]!=town["ref"]
            && find(sourceWorld,"heroes",town["army_holder_ref"]).isNull()) return;
    restoreError = "invalid_saved_plan";
    CampaignState validated;
    std::string reason;
    if(!validated.accept(saved["plan"], sourceWorld, reason)
        || saved["statuses"].Struct().size() != saved["plan"]["goals"].Vector().size()) return;
    restoreError = "invalid_saved_status";
    const std::set<std::string> states{"ready", "waiting", "blocked", "completed", "cancelled"};
    for(const auto & goal : saved["plan"]["goals"].Vector())
    {
        const auto & status = saved["statuses"][goal["id"].String()];
        if(!status.isStruct() || !label(status["state"]) || !states.count(status["state"].String())
            || !label(status["reason"])) return;
        if(status["state"].String() == "completed"
            && !integer(status["completed_day"], (goal["kind"].String()=="explore_passage" || goal["kind"].String()=="visit_site" || goal["kind"].String()=="intercept_hero" || goal["kind"].String()=="hire_helper") ? 1 : saved["accepted_day"].Integer(), 2147483647)) return;
        if(status["state"].String() == "completed" && goal["kind"].String()=="reinforce_hero"
            && !validated.deliveryProved(goal,saved["delivery_completions"][goal["id"].String()])) return;
        if(status["state"].String()=="completed" && goal["kind"].String()=="intercept_hero")
        {
            const auto & receipt=saved["interception_completions"][goal["id"].String()];
            if(!interceptionProved(goal,receipt)
                || !integer(status["completed_day"],receipt["day"].Integer(),goal["deadline_day"].Integer())) return;
        }
        if(status["state"].String()=="completed" && goal["kind"].String()=="hire_helper")
        {
            const auto & receipt=saved["helper_hire_completions"][goal["id"].String()];
            if(!helperHireProved(goal,receipt) || !integer(status["completed_day"],receipt["day"].Integer(),goal["deadline_day"].Integer())) return;
        }
        if(status["state"].String()=="completed" && goal["kind"].String()=="visit_site")
        {
            const auto & receipt=saved["site_completions"][goal["id"].String()];
            if(!siteProved(goal,receipt) || !integer(status["completed_day"],receipt["day"].Integer(),goal["deadline_day"].Integer())) return;
        }
        if(status["state"].String()=="completed" && goal["kind"].String()=="explore_passage")
        {
            const auto & receipt=saved["passage_completions"][goal["id"].String()];
            if(!passageProved(goal,receipt)
                || !integer(status["completed_day"],receipt["day"].Integer(),goal["deadline_day"].Integer())) return;
        }
        if(status["reason"].String()=="force_floor_breached" || status["failure_reason"].String()=="force_floor_breached")
        {
            if(goal["kind"].String()!="preserve_force" || status["state"].String()!="blocked"
                || !integer(status["observed_day"],saved["accepted_day"].Integer(),goal["complete_when"]["value"].Integer())
                || !integer(status["observed_army_value"],0,goal["min_army_value"].Integer()-1)) return;
            if(status["failure_reason"].String()=="force_floor_breached" && status["reason"].String()!="deadline_missed") return;
        }
        if(status["reason"].String()=="force_continuity_unconfirmed" || status["failure_reason"].String()=="force_continuity_unconfirmed")
        {
            if(goal["kind"].String()!="preserve_force" || status["state"].String()!="blocked"
                || !integer(status["unconfirmed_since_day"],saved["accepted_day"].Integer(),goal["complete_when"]["value"].Integer())) return;
            if(status["failure_reason"].String()=="force_continuity_unconfirmed" && status["reason"].String()!="deadline_missed") return;
        }
        if(!status["stabilized_day"].isNull()
            && ((status["reason"].String()!="force_continuity_unconfirmed" && status["failure_reason"].String()!="force_continuity_unconfirmed")
                || !integer(status["stabilized_day"],status["unconfirmed_since_day"].Integer(),goal["deadline_day"].Integer()))) return;
    }
    state = saved;
    restoreError.clear();
}

bool CampaignState::accept(const JsonNode & proposal, const JsonNode & world, std::string & reason, int64_t executionDay)
{
    auto reject = [&](const char * why) { reason = why; return false; };
    if(!fields(proposal, {"version", "revision", "approach", "horizon_days", "goals", "reserves", "policy"})
        || !integer(proposal["version"], 3, 3) || !integer(proposal["revision"], 1, 2147483647)
        || proposal["revision"].Integer() <= plan()["revision"].Integer()
        || !integer(proposal["horizon_days"], 3, 7)) return reject("invalid_campaign_version_or_revision");
    const std::set<std::string> approaches{"economy", "expansion", "offense", "defense", "scouting"};
    if(!proposal["approach"].isString() || !approaches.count(proposal["approach"].String())) return reject("unknown_approach");
    const auto & goals = proposal["goals"];
    if(!goals.isVector() || goals.Vector().empty() || goals.Vector().size() > 12) return reject("invalid_goal_count");
    std::map<std::string, const JsonNode *> byID;
    std::set<std::string> hiredCandidates;
    const int64_t day = executionDay ? executionDay : world["day"].Integer();
    for(const auto & goal : goals.Vector())
    {
        if(!(goal["kind"].String()=="hire_helper"
            ? goalFields(goal,{"id","kind","actor_ref","target_ref","deadline_day","priority","building_id","min_army_value","depends_on","required_capabilities","complete_when","candidate_ref","helper_role","job_ref"})
            : goal["kind"].String()=="prepare_garrison"
            ? goalFields(goal, {"id", "kind", "actor_ref", "target_ref", "deadline_day", "priority", "building_id", "min_army_value", "depends_on", "required_capabilities", "complete_when", "garrison_mode"})
            : goalFields(goal, {"id", "kind", "actor_ref", "target_ref", "deadline_day", "priority", "building_id", "min_army_value", "depends_on", "required_capabilities", "complete_when"}))
            || !label(goal["kind"]) || !label(goal["id"]) || !byID.emplace(goal["id"].String(), &goal).second
            || !integer(goal["priority"], 1, 100) || !integer(goal["deadline_day"], day, day + proposal["horizon_days"].Integer())
            || !integer(goal["min_army_value"], 0, 1000000000) || !integer(goal["building_id"], -1, 100000)) return reject("invalid_goal");
        const auto & risk=goal["risk"];
        if(!risk.isNull() && ((goal["kind"].String()!="capture_target" && goal["kind"].String()!="intercept_hero")
            || !fields(risk,{"max_loss_ratio","reason"}) || !risk["max_loss_ratio"].isNumber()
            || !std::isfinite(risk["max_loss_ratio"].Float()) || risk["max_loss_ratio"].Float()<0 || risk["max_loss_ratio"].Float()>1
            || !risk["reason"].isString() || risk["reason"].String().empty() || risk["reason"].String().size()>640)) return reject("invalid_goal_risk");
        if(!goal["actor_ref"].isNull() && (!label(goal["actor_ref"]) || find(world, "heroes", goal["actor_ref"]).isNull())) return reject("executor_not_owned");
        if(!label(goal["target_ref"])) return reject("invalid_target");
        const auto & hero = find(world, "heroes", goal["actor_ref"]);
        const auto & town = find(world, "towns", goal["target_ref"]);
        const auto & object = find(world, "objects", goal["target_ref"]);
        const auto & kind = goal["kind"].String();
        if(kind == "hire_helper")
        {
            if(!goal["actor_ref"].isNull() || goal["building_id"].Integer()!=-1 || goal["min_army_value"].Integer()!=0
                || !label(goal["candidate_ref"]) || !label(goal["job_ref"])
                || (goal["helper_role"].String()!="scout" && goal["helper_role"].String()!="collector"
                    && goal["helper_role"].String()!="reinforcement" && goal["helper_role"].String()!="defender")
                || !hiredCandidates.insert(goal["candidate_ref"].String()).second)
                return reject("invalid_helper_hire");
            bool confirmed=helperHireProved(goal,state["helper_hire_completions"][goal["id"].String()]);
            for(const auto & receipt:world["confirmed_helper_hires"].Vector()) confirmed |= helperHireProved(goal,receipt);
            if(!confirmed)
            {
                if(town.isNull() || !helperJobSupported(goal,world)) return reject("unsupported_helper_job");
                const auto & option=find(town,"hiring_options",goal["candidate_ref"]);
                if(option.isNull() || !integer(option["hero_type_id"],0,1000000)
                    || option["ref"].String()!="tavern:"+std::to_string(option["hero_type_id"].Integer())
                    || !option["can_recruit"].isBool() || !option["can_recruit"].Bool() || !resources(option["cost"]))
                    return reject("helper_candidate_unavailable");
                for(int i=0;i<7;++i) if(option["cost"][i].Integer()>world["resources"][i].Integer()) return reject("helper_hire_unfunded");
            }
        }
        else if(kind == "develop_town")
        {
            if(town.isNull() || !goal["actor_ref"].isNull() || goal["building_id"].Integer() < 0) return reject("invalid_town_development");
            bool supported = false;
            for(const auto & option : town["building_options"].Vector())
                supported |= option["id"] == goal["building_id"] && option["supported"].isBool() && option["supported"].Bool();
            if(!supported) return reject("unsupported_build_mechanic");
        }
        else if(kind == "capture_target" || kind == "secure_resource")
        {
            if(hero.isNull() || object.isNull()) return reject("unknown_capture_target");
            if(object["visible"].Bool() && object["owner"]==world["player"] && (object["kind"].String()=="town" || object["kind"].String()=="mine")) return reject("new_capture_target_already_owned");
            if(kind == "capture_target" && object["kind"].String() != "town" && object["kind"].String() != "mine") return reject("unsupported_capture_target");
            if(kind == "secure_resource" && object["kind"].String() != "mine" && object["kind"].String() != "resource") return reject("unsupported_resource_target");
        }
        else if(kind == "reinforce_hero")
        {
            if(hero.isNull() || goal["actor_ref"] == goal["target_ref"] || (town.isNull() && find(world, "heroes", goal["target_ref"]).isNull())) return reject("invalid_delivery_participants");
        }
        else if(kind == "visit_site")
        {
            bool confirmed=false;
            for(const auto & receipt:world["confirmed_site_visits"].Vector()) confirmed |= siteProved(goal,receipt);
            for(const auto & previous:plan()["goals"].Vector())
                confirmed |= sameGoal(previous,goal) && state["statuses"][goal["id"].String()]["state"].String()=="completed"
                    && siteProved(goal,state["site_completions"][goal["id"].String()]);
            if(!confirmed && (hero.isNull() || object.isNull() || !object["visible"].Bool()
                || !strategicSiteAvailable(object,goal["actor_ref"])))
                return reject("unsupported_visit_site");
        }
        else if(kind == "intercept_hero")
        {
            bool confirmed=interceptionProved(goal,state["interception_completions"][goal["id"].String()]);
            for(const auto & receipt:world["confirmed_interceptions"].Vector()) confirmed |= interceptionProved(goal,receipt);
            if(!confirmed && (hero.isNull() || object.isNull() || object["kind"].String()!="hero"
                || !object["visible"].Bool() || !contains(world["enemy_players"],object["owner"])))
                return reject("unknown_visible_enemy_hero");
        }
        else if(kind == "prepare_garrison")
        {
            if(!goal["garrison_mode"].isString() || (goal["garrison_mode"].String()!="recruit"
                && goal["garrison_mode"].String()!="detach" && goal["garrison_mode"].String()!="recruit_then_detach")
                || hero.isNull() || town.isNull() || goal["min_army_value"].Integer()>hero["army_value"].Integer())
                return reject("invalid_garrison_participants");
        }
        else if(kind == "defend_area")
        {
            if(hero.isNull() || town.isNull()) return reject("invalid_defense_participants");
        }
        else if(kind == "scout_frontier")
        {
            if(hero.isNull() || !contains(world["frontiers"], goal["target_ref"])) return reject("unknown_frontier");
        }
        else if(kind == "scout_area")
        {
            const auto & area=find(world,"scouting_options",goal["target_ref"]);
            if(hero.isNull() || area.isNull() || !area["position"].isVector()
                || area["position"].Vector().size()!=3 || !area["own_arrivals"].isVector()) return reject("unknown_scout_area");
            for(const auto & axis:area["position"].Vector()) if(!integer(axis,0,100000)) return reject("invalid_scout_area_position");
            bool offered=false;
            for(const auto & route:area["own_arrivals"].Vector())
                offered |= route["hero_ref"]==goal["actor_ref"] && integer(route["sight_radius"],1,64)
                    && route["sight_radius"]==hero["sight_radius"]
                    && route["sight_radius"]==goal["complete_when"]["value"]
                    && integer(route["expected_new_tiles"],1,1000000000);
            if(!offered) return reject("unsupported_scout_area_radius");
        }
        else if(kind == "explore_passage")
        {
            if(hero.isNull() || object.isNull() || (object["kind"].String()!="subterranean_gate" && object["kind"].String()!="portal")
                || !object["visible"].Bool()) return reject("unknown_visible_passage");
        }
        else if(kind == "preserve_force")
        {
            if(hero.isNull() || town.isNull()) return reject("invalid_preservation_target");
        }
        else return reject("unsupported_goal_type");
        if(!goal["required_capabilities"].isVector() || goal["required_capabilities"].Vector().size() > 8) return reject("invalid_capabilities");
        for(const auto & cap : goal["required_capabilities"].Vector())
            if(!label(cap) || !contains(world["capabilities"], cap)) return reject("unsupported_capability");
        if(!goal["depends_on"].isVector() || goal["depends_on"].Vector().size() > 12) return reject("invalid_dependencies");
        const auto & predicate = goal["complete_when"];
        if(!fields(predicate, {"kind", "value"}) || !label(predicate["kind"]) || !integer(predicate["value"], 0, 1000000000)) return reject("invalid_completion_predicate");
        const auto & completion = predicate["kind"].String();
        const bool valid = (kind == "hire_helper" && completion == "helper_hired" && predicate["value"].Integer()==0)
            || (kind == "intercept_hero" && completion == "enemy_engaged" && predicate["value"].Integer()==0)
            || (kind == "prepare_garrison" && completion == "garrison_at_least" && predicate["value"].Integer()>0)
            || (kind == "develop_town" && completion == "building_present" && predicate["value"] == goal["building_id"])
            || ((kind == "capture_target" || (kind == "secure_resource" && object["kind"].String() == "mine")) && completion == "target_owned" && predicate["value"] == world["player"])
            || (kind == "secure_resource" && object["kind"].String() == "resource" && completion == "reserve_at_least")
            || (kind == "reinforce_hero" && completion == "army_at_least" && predicate["value"].Integer() >= goal["min_army_value"].Integer())
            || (kind == "preserve_force" && completion == "force_preserved_until" && predicate["value"].Integer() >= day && predicate["value"].Integer() <= goal["deadline_day"].Integer())
            || (kind == "visit_site" && completion == "site_visited" && predicate["value"].Integer()==0)
            || (kind == "scout_area" && completion == "area_observed" && integer(predicate["value"],1,64))
            || (kind == "scout_frontier" && completion == "frontier_observed" && predicate["value"].Integer() == 0)
            || (kind == "explore_passage" && completion == "passage_explored" && predicate["value"].Integer() == 0)
            || (kind == "defend_area" && completion == "held_until" && predicate["value"].Integer() >= day && predicate["value"].Integer() <= goal["deadline_day"].Integer());
        if(!valid) return reject("predicate_does_not_prove_goal");
    }
    // DAG validity also defines whether two assignments can reuse a hero
    // sequentially. Parallel incompatible obligations are rejected atomically.
    std::map<std::string, int> marks;
    std::function<bool(const std::string &)> visit = [&](const std::string & id) {
        if(marks[id] == 1) return false;
        if(marks[id] == 2) return true;
        marks[id] = 1;
        for(const auto & dep : (*byID.at(id))["depends_on"].Vector())
            if(!label(dep) || !byID.count(dep.String()) || !visit(dep.String())) return false;
        marks[id] = 2;
        return true;
    };
    for(const auto & [id, goal] : byID) if(!visit(id)) return reject("missing_or_cyclic_dependency");
    std::function<bool(const std::string &, const std::string &)> depends = [&](const std::string & id, const std::string & other) {
        for(const auto & dep : (*byID.at(id))["depends_on"].Vector())
            if(dep.String() == other || depends(dep.String(), other)) return true;
        return false;
    };
    auto participants = [&](const JsonNode & goal) {
        std::set<std::string> heroes;
        if(goal["actor_ref"].isString()) heroes.insert(armyPool(goal["actor_ref"].String(),world));
        if(goal["kind"].String() == "reinforce_hero" || goal["kind"].String()=="prepare_garrison")
            heroes.insert(armyPool(goal["target_ref"].String(),world));
        return heroes;
    };
    for(const auto & [id,goal]:byID)
        if((*goal)["kind"].String()=="reinforce_hero"
            && armyPool((*goal)["actor_ref"].String(),world)==armyPool((*goal)["target_ref"].String(),world))
            return reject("delivery_source_is_recipient");
    for(const auto & [id, goal] : byID)
        for(const auto & [otherID, other] : byID)
        {
            if(id >= otherID || depends(id, otherID) || depends(otherID, id)) continue;
            const auto a = participants(*goal), b = participants(*other);
            bool overlap = false;
            for(const auto & actor : a) overlap |= b.count(actor);
            // A force floor is compatible with a delivery using that
            // courier; the gateway enforces the floor during the exchange.
            const bool preservation = ((*goal)["kind"].String() == "preserve_force" && (*other)["kind"].String() == "reinforce_hero")
                || ((*other)["kind"].String() == "preserve_force" && (*goal)["kind"].String() == "reinforce_hero");
            if(overlap && !preservation) return reject("conflicting_hero_obligations");
        }
    const auto & reserves = proposal["reserves"];
    if(!reserves.isVector() || reserves.Vector().size() > 12) return reject("invalid_reserves");
    std::set<std::string> reservedGoals;
    int64_t totals[7]{};
    for(const auto & reserve : reserves.Vector())
    {
        if(!fields(reserve, {"goal_id", "resources", "force_value"}) || !label(reserve["goal_id"])
            || !byID.count(reserve["goal_id"].String()) || !reservedGoals.insert(reserve["goal_id"].String()).second
            || !resources(reserve["resources"]) || !integer(reserve["force_value"], 0, 1000000000)) return reject("invalid_commitment_reserve");
        const auto & goal = *byID.at(reserve["goal_id"].String());
        if(reserve["force_value"].Integer() && find(world, "heroes", goal["actor_ref"])["army_value"].Integer() < reserve["force_value"].Integer()) return reject("force_reserve_not_available");
        for(int i = 0; i < 7; ++i) totals[i] += reserve["resources"][i].Integer();
    }
    for(int i = 0; i < 7; ++i)
        if(totals[i] > world["resources"][i].Integer()) return reject("resource_commitments_exceed_available_funds");
    for(const auto & goal:goals.Vector()) if(goal["kind"].String()=="hire_helper")
    {
        const auto & cost=find(find(world,"towns",goal["target_ref"]),"hiring_options",goal["candidate_ref"])["cost"];
        for(int i=0;i<7;++i)
        {
            int64_t own=0;
            for(const auto & reserve:reserves.Vector()) if(reserve["goal_id"]==goal["id"]) own=reserve["resources"][i].Integer();
            if(!cost.isNull() && cost[i].Integer()>world["resources"][i].Integer()-totals[i]+own) return reject("helper_hire_unfunded");
        }
    }
    const auto & policy = proposal["policy"];
    if(!fields(policy, {"max_loss_ratio", "allow_route_repair", "allow_helper_replacement", "critical_towns"})
        || !policy["max_loss_ratio"].isNumber() || !std::isfinite(policy["max_loss_ratio"].Float()) || policy["max_loss_ratio"].Float() < 0 || policy["max_loss_ratio"].Float() > 0.5
        || !policy["allow_route_repair"].isBool() || !policy["allow_helper_replacement"].isBool()
        || !policy["critical_towns"].isVector()) return reject("invalid_policy");
    for(const auto & ref : policy["critical_towns"].Vector()) if(find(world, "towns", ref).isNull()) return reject("critical_town_not_owned");
    JsonNode accepted;
    accepted["version"].Integer() = 3;
    accepted["accepted_day"] = world["day"];
    accepted["plan"] = proposal;
    accepted["validation_world"] = world;
    // A revision preserves already confirmed results only for identical
    // goal semantics. Changing a goal ID alone never confirms execution.
    for(const auto & goal : goals.Vector())
        for(const auto & old : plan()["goals"].Vector())
            if(sameGoal(goal,old)) accepted["statuses"][goal["id"].String()] = state["statuses"][goal["id"].String()];
    for(const auto & goal : goals.Vector())
        if(accepted["statuses"][goal["id"].String()]["state"].String()=="completed" && goal["kind"].String()=="reinforce_hero")
            accepted["delivery_completions"][goal["id"].String()]=state["delivery_completions"][goal["id"].String()];
    for(const auto & goal : goals.Vector())
        if(accepted["statuses"][goal["id"].String()]["state"].String()=="completed" && goal["kind"].String()=="explore_passage")
            accepted["passage_completions"][goal["id"].String()]=state["passage_completions"][goal["id"].String()];
    for(const auto & goal:goals.Vector())
        if(accepted["statuses"][goal["id"].String()]["state"].String()=="completed" && goal["kind"].String()=="visit_site")
            accepted["site_completions"][goal["id"].String()]=state["site_completions"][goal["id"].String()];
    // A consumed site can disappear from the fresh world. Preserve only
    // already-proved carried receipts so strict save validation sees the
    // same own facts that justified this revision.
    for(const auto & goal:goals.Vector()) if(goal["kind"].String()=="visit_site")
    {
        const auto & receipt=static_cast<const JsonNode &>(accepted)["site_completions"][goal["id"].String()];
        if(!siteProved(goal,receipt)) continue;
        auto & confirmations=accepted["validation_world"]["confirmed_site_visits"].Vector();
        if(std::none_of(confirmations.begin(),confirmations.end(),[&](const auto & existing) {return siteProved(goal,existing);}))
            confirmations.push_back(receipt);
    }
    for(const auto & goal:goals.Vector())
        if(accepted["statuses"][goal["id"].String()]["state"].String()=="completed" && goal["kind"].String()=="intercept_hero")
            accepted["interception_completions"][goal["id"].String()]=state["interception_completions"][goal["id"].String()];
    for(const auto & goal:goals.Vector())
        if(accepted["statuses"][goal["id"].String()]["state"].String()=="completed" && goal["kind"].String()=="hire_helper")
            accepted["helper_hire_completions"][goal["id"].String()]=state["helper_hire_completions"][goal["id"].String()];
    state = accepted;
    review(world);
    reason.clear();
    return true;
}

std::optional<int64_t> CampaignState::townlessCaptureDeadline(const JsonNode & world)
{
    const auto & rule=world["victory"]["townless_defeat"];
    if(!world["towns"].isVector() || !world["towns"].Vector().empty()
        || rule["status"].String()!="public_rule"
        || !integer(world["day"],1,2147483647) || !integer(rule["turns"],1,2147483647)
        || !integer(rule["own_elapsed_turns"],0,2147483647)) return {};
    // The loss check follows this player's turn: six elapsed of seven means
    // capture today, not tomorrow. Owning a town removes this constraint.
    return world["day"].Integer()+rule["turns"].Integer()-rule["own_elapsed_turns"].Integer()-1;
}
bool CampaignState::validateTownlessRecovery(const JsonNode & world,std::string & reason) const
{
    const auto deadline=townlessCaptureDeadline(world);
    if(!deadline) return true;
    for(const auto & goal:plan()["goals"].Vector())
        if(statuses()[goal["id"].String()]["state"].String()!="completed"
            && goal["deadline_day"].Integer()>*deadline)
        { reason="townless_goal_after_defeat";return false; }
    for(const auto & goal:plan()["goals"].Vector())
    {
        if(goal["kind"].String()!="capture_target" || statuses()[goal["id"].String()]["state"].String()!="ready") continue;
        const auto & target=find(world,"objects",goal["target_ref"]);
        if(target["kind"].String()=="town" && target["visible"].Bool()
            && target["owner"].isNumber() && (target["owner"].Integer()<0 || contains(world["enemy_players"],target["owner"]))
            && hasSupportedRoute(goal,world)) return true;
    }
    reason="townless_recovery_not_supported";
    return false;
}

JsonNode CampaignState::routeFeedback(const JsonNode & goal,const JsonNode & world) const
{
    JsonNode feedback;feedback["goal_id"]=goal["id"];feedback["actor_ref"]=goal["actor_ref"];
    feedback["target_ref"]=goal["target_ref"];feedback["deadline_day"]=goal["deadline_day"];
    feedback["supported"].Bool()=false;feedback["assigned_routes"].Vector();feedback["safe_options"].Vector();
    const auto & kind=goal["kind"].String();
    if(kind!="capture_target" && kind!="intercept_hero" && kind!="secure_resource" && kind!="scout_frontier" && kind!="scout_area" && kind!="visit_site" && kind!="explore_passage")
    { feedback["supported"].Bool()=true;return feedback; }
    const auto & entries=kind=="scout_area" ? world["scouting_options"] : kind=="scout_frontier" ? world["frontier_options"] : world["forecasts"]["routes"];
    for(const auto & entry:entries.Vector())
    {
        const auto & target=(kind=="scout_frontier" || kind=="scout_area") ? entry["ref"] : entry["target_ref"];
        if(target!=goal["target_ref"]) continue;
        for(const auto & route:entry["own_arrivals"].Vector())
        {
            JsonNode option=route;option["issues"].Vector();
            auto issue=[&](const char * code) {option["issues"].Vector().emplace_back(code);};
            if(find(world,"heroes",route["hero_ref"]).isNull()
                || !integer(route["day"],world["day"].Integer(),2147483647)
                || !integer(route["army_value"],0,1000000000000LL)
                || !integer(route["army_loss_estimate"],0,1000000000000LL))
            { if(route["hero_ref"]==goal["actor_ref"]) {issue("incomplete_route_forecast");feedback["assigned_routes"].Vector().push_back(option);} continue; }
            if(kind=="scout_area" && route["sight_radius"].Integer()<goal["complete_when"]["value"].Integer()) issue("insufficient_sight_radius");
            const auto army=route["army_value"].Integer(),loss=route["army_loss_estimate"].Integer();
            const auto floor=reservedForce(route["hero_ref"].String(),world);
            option["retained_force_floor"].Integer()=floor;
            const auto riskGoal=route["hero_ref"]==goal["actor_ref"] ? goal : JsonNode();
            option["allowed_loss_ratio"].Float()=lossLimit(riskGoal);
            if(army>0) option["estimated_loss_percent"].Float()=100.0*loss/army;
            option["allowed_loss_percent"].Float()=100.0*lossLimit(riskGoal);
            if(army<goal["min_army_value"].Integer()) issue("starting_army_below_minimum");
            if(!allowsLoss(riskGoal,army,loss)) issue("loss_exceeds_policy");
            if(loss>army || army-loss<floor) issue("retained_force_below_reserve");
            const bool safe=option["issues"].Vector().empty();
            option["meets_deadline"].Bool()=route["day"].Integer()<=goal["deadline_day"].Integer();
            if(!option["meets_deadline"].Bool()) issue("arrival_after_deadline");
            if(safe) feedback["safe_options"].Vector().push_back(option);
            if(route["hero_ref"]==goal["actor_ref"])
            {
                feedback["supported"].Bool() |= option["issues"].Vector().empty();
                feedback["assigned_routes"].Vector().push_back(option);
            }
        }
    }
    if(feedback["assigned_routes"].Vector().empty()) feedback["reason"].String()="assigned_actor_route_not_established";
    else feedback["reason"].String()=feedback["supported"].Bool() ? "supported_route" : "assigned_routes_violate_constraints";
    // A correction keeps the chosen actor and passes army/loss/reserve
    // constraints; only its deadline may need changing.
    for(const auto & option:feedback["safe_options"].Vector())
        if(option["hero_ref"]==goal["actor_ref"] && (feedback["earliest_safe_arrival_day"].isNull()
            || option["day"].Integer()<feedback["earliest_safe_arrival_day"].Integer()))
            feedback["earliest_safe_arrival_day"]=option["day"];
    return feedback;
}

std::string CampaignState::routeFeedbackFacts(const JsonNode & goal,const JsonNode & world) const
{
    const auto feedback=routeFeedback(goal,world);
    JsonNode facts;facts["reason"]=feedback["reason"];facts["supported"]=feedback["supported"];
    for(const auto * key : {"assigned_routes","safe_options"})
    {
        std::set<std::string> options;
        for(const auto & route:feedback[key].Vector())
        {
            JsonNode option;option["hero_ref"]=route["hero_ref"];option["day"]=route["day"];
            option["issues"]=route["issues"];option["meets_deadline"]=route["meets_deadline"];
            options.insert(option.toCompactString());
        }
        facts[key].Vector();
        for(const auto & option:options) facts[key].Vector().emplace_back(option);
    }
    const auto canonical=facts.toCompactString();
    boost::uuids::detail::sha1 digest;digest.process_bytes(canonical.data(),canonical.size());
    unsigned int words[5];digest.get_digest(words);
    static constexpr char hex[]="0123456789abcdef";
    std::string result;
    for(const auto word:words) for(int shift=28;shift>=0;shift-=4) result+=hex[(word>>shift)&15];
    return result;
}

JsonNode CampaignState::review(const JsonNode & world,bool checkRoutes)
{
    const auto goals = plan()["goals"];
    std::map<std::string, const JsonNode *> byID;
    for(const auto & goal : goals.Vector()) byID[goal["id"].String()] = &goal;
    JsonNode result;
    std::function<void(const std::string &)> reviewGoal = [&](const std::string & id) {
        if(result.Struct().count(id)) return;
        const auto & goal = *byID.at(id);
        auto & status = result[id];
        const auto & previous = static_cast<const JsonNode &>(state)["statuses"][id];
        if(previous["state"].String() == "completed" || previous["state"].String()=="cancelled")
        { status = previous; return; }
        // Preservation describes the whole accepted interval. Later
        // recruitment cannot erase an observed loss below its floor;
        // keep that evidence in the saved goal status until a revision.
        if(previous["reason"].String()=="force_floor_breached")
        {
            status=previous;
            if(world["day"].Integer()>goal["deadline_day"].Integer())
            {
                status["reason"].String()="deadline_missed";
                status["failure_reason"].String()="force_floor_breached";
            }
            return;
        }
        if(previous["reason"].String()=="deadline_missed" && previous["failure_reason"].String()=="force_floor_breached")
        { status=previous;return; }
        status["state"].String() = "ready";
        status["reason"].String() = "preconditions_met";
        if(goal["kind"].String()=="preserve_force" && world["day"].Integer()<=goal["complete_when"]["value"].Integer())
        {
            const auto & hero=find(world,"heroes",goal["actor_ref"]);
            if(!hero.isNull() && hero["army_value"].Integer()<goal["min_army_value"].Integer())
            {
                status["state"].String()="blocked";
                status["reason"].String()="force_floor_breached";
                status["observed_day"]=world["day"];
                status["observed_army_value"]=hero["army_value"];
                return;
            }
        }
        // An unfinished saved task proves its endpoint, not every army
        // value during the missing interval. Do not fabricate continuity.
        if(previous["reason"].String()=="force_continuity_unconfirmed"
            || (previous["reason"].String()=="deadline_missed" && previous["failure_reason"].String()=="force_continuity_unconfirmed"))
        {
            status=previous;
            // The missing historical interval remains unconfirmed. Once
            // its hero is observed at refuge with the promised force,
            // stop repeating that return before another compatible task.
            if(status["stabilized_day"].isNull() && world["day"].Integer()<=goal["deadline_day"].Integer()
                && atPreservationRefuge(goal,world)) status["stabilized_day"]=world["day"];
            if(world["day"].Integer()>goal["deadline_day"].Integer())
            {
                status["reason"].String()="deadline_missed";
                status["failure_reason"].String()="force_continuity_unconfirmed";
            }
            return;
        }
        // Newly observed state after the deadline does not establish when
        // a building/capture/preservation predicate became true. Completed
        // acknowledgments already retained above remain durable on load.
        if(world["day"].Integer()<=goal["deadline_day"].Integer() && finished(goal, world))
        {
            status["state"].String() = "completed";
            status["reason"].String() = "observed_completion_predicate";
            status["completed_day"] = world["day"];
            if(goal["kind"].String()=="explore_passage")
                for(const auto & receipt:world["confirmed_passage_explorations"].Vector()) if(passageProved(goal,receipt))
                    state["passage_completions"][id]=receipt;
            if(goal["kind"].String()=="hire_helper")
                for(const auto & receipt:world["confirmed_helper_hires"].Vector()) if(helperHireProved(goal,receipt))
                    state["helper_hire_completions"][id]=receipt;
            if(goal["kind"].String()=="visit_site")
                for(const auto & receipt:world["confirmed_site_visits"].Vector()) if(siteProved(goal,receipt))
                    state["site_completions"][id]=receipt;
            if(goal["kind"].String()=="intercept_hero")
                for(const auto & receipt:world["confirmed_interceptions"].Vector()) if(interceptionProved(goal,receipt))
                    state["interception_completions"][id]=receipt;
            if(goal["kind"].String()=="reinforce_hero")
                for(const auto & receipt:world["confirmed_deliveries"].Vector()) if(deliveryProved(goal,receipt))
                    state["delivery_completions"][id]=receipt;
            return;
        }
        if(!goal["actor_ref"].isNull() && find(world, "heroes", goal["actor_ref"]).isNull())
        { status["state"].String() = "blocked"; status["reason"].String() = "executor_no_longer_owned"; }
        else if(world["day"].Integer() > goal["deadline_day"].Integer())
        { status["state"].String() = "blocked"; status["reason"].String() = "deadline_missed"; }
        else if((goal["kind"].String()=="develop_town" || goal["kind"].String()=="prepare_garrison" || goal["kind"].String()=="defend_area" || goal["kind"].String()=="hire_helper")
            && find(world,"towns",goal["target_ref"]).isNull())
        { status["state"].String()="blocked";status["reason"].String()="target_no_longer_owned"; }
        else if(goal["kind"].String() == "preserve_force")
        {
            if(atPreservationRefuge(goal,world))
            { status["state"].String() = "waiting"; status["reason"].String() = "holding_preserved_force"; }
        }
        if(status["state"].String() == "ready" || status["state"].String() == "waiting")
            for(const auto & dependency : goal["depends_on"].Vector())
            {
                reviewGoal(dependency.String());
                if(result[dependency.String()]["state"].String() != "completed")
                {
                    const bool failed=failedCommitment(result[dependency.String()]);
                    status["state"].String() = failed ? "blocked" : "waiting";
                    status["reason"].String() = failed ? "dependency_failed" : "dependency_unconfirmed";
                }
            }
        if(checkRoutes && status["state"].String()=="ready" && !hasSupportedRoute(goal,world))
        {
            status["state"].String()="blocked";
            status["reason"].String()="no_supported_route";
        }
    };
    for(const auto & [id, goal] : byID) reviewGoal(id);
    state["statuses"] = result;
    return result;
}

void CampaignState::unconfirmedExecution(int firstDay)
{
    for(const auto & goal:plan()["goals"].Vector())
    {
        if(goal["kind"].String()!="preserve_force" || firstDay<state["accepted_day"].Integer()
            || firstDay>goal["complete_when"]["value"].Integer()) continue;
        auto & status=state["statuses"][goal["id"].String()];
        if(status["state"].String()=="completed" || status["state"].String()=="cancelled"
            || status["reason"].String()=="force_floor_breached" || failedCommitment(status)) continue;
        status["state"].String()="blocked";
        status["reason"].String()="force_continuity_unconfirmed";
        status.Struct().erase("stabilized_day");
        if(status["unconfirmed_since_day"].isNull()) status["unconfirmed_since_day"].Integer()=firstDay;
    }
}

bool CampaignState::observeForceMinimum(const std::string & heroRef, int day, int64_t armyValue)
{
    bool changed=false;
    for(const auto & goal:plan()["goals"].Vector())
    {
        if(goal["kind"].String()!="preserve_force" || goal["actor_ref"].String()!=heroRef
            || day<state["accepted_day"].Integer() || day>goal["complete_when"]["value"].Integer()
            || armyValue>=goal["min_army_value"].Integer()) continue;
        auto & status=state["statuses"][goal["id"].String()];
        if(status["state"].String()=="completed" || status["state"].String()=="cancelled"
            || status["reason"].String()=="force_floor_breached") continue;
        status["state"].String()="blocked";
        status["reason"].String()="force_floor_breached";
        status["observed_day"].Integer()=day;
        status["observed_army_value"].Integer()=armyValue;
        changed=true;
    }
    return changed;
}

std::set<std::string> CampaignState::participantGoals(const std::string & ref,
        const std::map<std::string,std::string> & replacements, const JsonNode & world) const
{
    const auto pool=armyPool(ref,world);
    std::set<std::string> result;
    for(const auto & goal : plan()["goals"].Vector())
    {
        const auto & id = goal["id"].String();
        if(!holdsCommitment(id)) continue;
        if((goal["actor_ref"].isString() && armyPool(goal["actor_ref"].String(),world) == pool)
            || (goal["kind"].String() == "reinforce_hero" && armyPool(deliverySource(goal,replacements),world) == pool)) result.insert(id);
    }
    return result;
}

int64_t CampaignState::operationForce(const std::string & ref,const JsonNode & world,const std::string & spendingGoal) const
{
    const auto pool=armyPool(ref,world);
    int64_t floor=0;
    for(const auto & goal:plan()["goals"].Vector())
    {
        const auto & kind=goal["kind"].String(), & id=goal["id"].String();
        if(id==spendingGoal || !holdsCommitment(id)
            || (kind!="capture_target" && kind!="intercept_hero" && kind!="secure_resource")
            || !goal["actor_ref"].isString() || armyPool(goal["actor_ref"].String(),world)!=pool) continue;
        floor=std::max(floor,goal["min_army_value"].Integer());
    }
    for(const auto & hero:world["heroes"].Vector()) if(armyPool(hero["ref"].String(),world)==pool)
        return std::min(floor,hero["army_value"].Integer());
    return 0;
}

int64_t CampaignState::reservedForce(const std::string & ref, const JsonNode & world,
        const std::map<std::string,std::string> & replacements, const std::string & spendingGoal) const
{
    const auto pool=armyPool(ref,world);
    int64_t floor = 0, pledged = 0;
    for(const auto & goal : plan()["goals"].Vector())
    {
        const auto & id = goal["id"].String();
        if(goal["kind"].String()=="prepare_garrison" && world["day"].Integer()<=goal["deadline_day"].Integer()
            && armyPool(goal["target_ref"].String(),world)==pool && pool!=goal["actor_ref"].String())
            floor=std::max(floor,goal["complete_when"]["value"].Integer());
        if(!holdsCommitment(id)) continue;
        const bool actor = goal["actor_ref"].isString() && armyPool(goal["actor_ref"].String(),world) == pool;
        if((goal["kind"].String() == "defend_area" && armyPool(goal["target_ref"].String(),world) == pool)
            || (actor && (goal["kind"].String() == "preserve_force" || goal["kind"].String() == "prepare_garrison" || goal["kind"].String() == "defend_area")))
            floor = std::max(floor, goal["min_army_value"].Integer());
        for(const auto & reserve : plan()["reserves"].Vector())
            if(actor && reserve["goal_id"].String() == id) floor = std::max(floor, reserve["force_value"].Integer());
        if(goal["kind"].String() != "reinforce_hero") continue;
        const auto required = goal["complete_when"]["value"].Integer();
        const auto current = find(world,"heroes",goal["actor_ref"])["army_value"].Integer();
        // Keep the recipient's contribution and the source's promised
        // surplus out of unrelated exchanges. Only this delivery releases
        // its own pledge; preservation floors remain in force.
        if(actor) floor = std::max(floor, std::min(current,required));
        if(id != spendingGoal && armyPool(deliverySource(goal,replacements),world) == pool)
            pledged = std::max(pledged, std::max<int64_t>(0,required-current));
    }
    return floor + pledged;
}

JsonNode CampaignState::reservedResources(const std::string & spendingGoal) const
{
    JsonNode result;
    for(int i = 0; i < 7; ++i) result.Vector().emplace_back(0);
    for(const auto & reserve : plan()["reserves"].Vector())
    {
        const auto & id = reserve["goal_id"].String();
        if(id == spendingGoal || !holdsCommitment(id)) continue;
        for(int i = 0; i < 7; ++i) result[i].Integer() += reserve["resources"][i].Integer();
    }
    return result;
}
}
