#pragma once
// Existing admission probes exercise the operational contract. Supply a valid
// independent initial course so their mutations still reach that public seam.
inline void initialCourseFixture(JsonNode & request,JsonNode & reply,const JsonNode & world)
{
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
    reply["operation_focus"]["revision"].Integer()=1;reply["operation_focus"]["bindings"].Vector();
}
