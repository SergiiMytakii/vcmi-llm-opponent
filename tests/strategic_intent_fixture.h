#pragma once
// Existing admission probes exercise the operational contract. Supply a valid
// independent initial course so their mutations still reach that public seam.
inline void initialCourseFixture(JsonNode & request,JsonNode & reply,const JsonNode & world)
{
    reply["decision_basis"]["waits"].Vector().clear();reply["decision_basis"]["town_choices"].Vector().clear();
    request["observation"]=world;request["strategic_intent"]=JsonNode();
    JsonNode selected;selected["objective"].String()="Capture hostile towns";selected["selection_reason"].String()="Build sufficient force for conquest";
    selected["assumptions"].Vector();
    for(int index=1;index<=3;++index)
    {
        JsonNode milestone;milestone["id"].String()="force-"+std::to_string(index);milestone["description"].String()="Build the main army";
        milestone["depends_on"].Vector();milestone["complete_when"]["kind"].String()="army_at_least";
        milestone["complete_when"]["actor_ref"]=world["heroes"][0]["ref"];milestone["complete_when"]["target_ref"]=JsonNode();
        milestone["complete_when"]["value"].Integer()=1000000*index;
        selected["milestones"].Vector().push_back(milestone);
    }
    JsonNode condition;condition["kind"].String()="milestone_completed";condition["milestone_id"].String()="force-1";condition["reason"].String()="Review the next operation";
    selected["reconsider_when"].Vector().push_back(condition);
    reply["strategy_update"]["decision"].String()="revise";reply["strategy_update"]["base_revision"].Integer()=0;
    reply["strategy_update"]["selected"]=selected;reply["strategy_update"]["change_reason"].String()="Initial course";
    reply["operation_focus"]["revision"].Integer()=1;reply["operation_focus"]["bindings"].Vector().clear();
    for(const auto & goal:reply["plan"]["goals"].Vector())
    {
        const auto & kind=goal["kind"].String();
        if(kind!="preserve_force" && kind!="defend_area" && (goal["depends_on"].Vector().empty() || !goal["actor_ref"].isString())) continue;
        JsonNode wait;wait["goal_id"]=goal["id"];wait["purpose"].String()=kind=="preserve_force" ? "safety" : kind=="defend_area" ? "defend" : "prepare";
        if(kind=="preserve_force" || kind=="defend_area") wait["basis_goal_ids"].Vector().push_back(goal["id"]);
        else for(const auto & id:goal["depends_on"].Vector()) {
            wait["basis_goal_ids"].Vector().push_back(id);
            JsonNode sourceBinding;sourceBinding["goal_id"]=id;sourceBinding["milestone_id"].String()="force-1";
            reply["operation_focus"]["bindings"].Vector().push_back(sourceBinding);
        }wait["next_goal_id"]=JsonNode();
        reply["decision_basis"]["waits"].Vector().push_back(wait);
        JsonNode binding;binding["goal_id"]=goal["id"];binding["milestone_id"].String()="force-1";
        reply["operation_focus"]["bindings"].Vector().push_back(binding);
    }
    for(const auto & defense:world["forecasts"]["defenses"].Vector()) if(!defense["threats"].Vector().empty())
    {
        JsonNode choice;choice["town_ref"]=defense["town_ref"];choice["choice"].String()="accept_risk";choice["goal_ids"].Vector();
        for(const auto & goal:reply["plan"]["goals"].Vector()) choice["goal_ids"].Vector().push_back(goal["id"]);
        reply["decision_basis"]["town_choices"].Vector().push_back(choice);
    }

}
