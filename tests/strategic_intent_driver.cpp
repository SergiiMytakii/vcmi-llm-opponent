#include "Global.h"
#include "StrategicIntent.h"
#include "NativePersistence.h"
#include <iostream>
#include <fstream>
#include <stdexcept>

JsonNode json(const std::string & value)
{
    JsonParsingSettings settings;settings.strict=true;settings.mode=JsonParsingSettings::JsonFormatMode::JSON;
    return JsonNode(value.data(),value.size(),settings,"strategic intent proof");
}
void require(bool value,const char * message) { if(!value) throw std::runtime_error(message); }
int main(int argc,char ** argv)
{
    using namespace nullkiller3;
    try
    {
        if(argc==2)
        {
            std::ifstream input(argv[1]);require(bool(input),"recorded request unavailable");
            const auto request=json(std::string(std::istreambuf_iterator<char>(input),{}));
            JsonNode projection;projection["stalls"]=strategicStalls(request["strategic_intent"],request["observation"]);
            projection["signals"].Vector();
            for(const auto & signal:strategicIntentSignals(request["strategic_intent"],request["observation"],true))
            {
                JsonNode item;item["question"].String()=signal.question;item["facts"].String()=signal.facts;
                item["critical"].Bool()=signal.critical;projection["signals"].Vector().push_back(item);
            }
            std::cout << projection.toCompactString() << '\n';
            return 0;
        }
        auto world=json(R"({"day":1,"player":0,"heroes":[{"ref":"hero","army_value":50}],"towns":[{"ref":"home","kind":"town","buildings":[]}],"objects":[{"ref":"far","kind":"town","visible":true,"owner":1},{"ref":"site","kind":"scholar","visible":true},{"ref":"gate","kind":"subterranean_gate","visible":true}]})");
        auto selected=json(R"({"objective":"Capture the enemy bases","selection_reason":"Known towns offer a route to victory","assumptions":[],"milestones":[{"id":"capture","description":"Take the far town","depends_on":[],"complete_when":{"kind":"target_owned","target_ref":"far","actor_ref":null,"value":0}},{"id":"visit","description":"Learn from the scholar","depends_on":["capture"],"complete_when":{"kind":"site_visited","target_ref":"site","actor_ref":"hero","value":0}},{"id":"army","description":"Reach sufficient army strength","depends_on":[],"complete_when":{"kind":"army_at_least","target_ref":null,"actor_ref":"hero","value":100}}],"reconsider_when":[{"kind":"milestone_completed","milestone_id":"visit","reason":"Choose the next operation"},{"kind":"no_progress","milestone_id":"capture","reason":"Review a stalled route"}]})");
        auto goal=json(R"({"id":"old","kind":"visit_site","actor_ref":"hero","target_ref":"site","deadline_day":5,"complete_when":{"kind":"site_visited","value":0}})");
        JsonNode plan;plan["revision"].Integer()=1;plan["goals"].Vector().push_back(goal);
        JsonNode request;request["observation"]=world;request["strategic_intent"]=JsonNode();request["evidence_refs"].Vector();
        JsonNode reply;reply["decision_basis"]=json(R"({"waits":[],"town_choices":[]})");reply["strategy_update"]["decision"].String()="revise";reply["strategy_update"]["base_revision"].Integer()=0;
        reply["strategy_update"]["selected"]=selected;reply["strategy_update"]["change_reason"].String()="Initial course";
        reply["operation_focus"]["revision"].Integer()=1;
        reply["operation_focus"]["bindings"].Vector().push_back(json(R"({"goal_id":"old","milestone_id":"visit"})"));
        std::string reason;JsonNode intent;
        auto missingBasis=reply;missingBasis.Struct().erase("decision_basis");
        require(!validateStrategicIntentUpdate(missingBasis,request,world,plan,JsonNode(),intent,reason),"missing decision basis accepted");
        require(validateStrategicIntentUpdate(reply,request,world,plan,JsonNode(),intent,reason),reason.c_str());
        bindStrategicOperation(intent,reply["operation_focus"],plan,JsonNode());
        require(validSavedStrategicIntent(intent),"initial course cannot restore");
        // Completed preparation must not hide a stalled capture when the model
        // attached no_progress only to the army milestone.
        auto stalledCourse=intent;
        stalledCourse["reconsider_when"]=json(R"([{"kind":"no_progress","milestone_id":"army","reason":"Review preparation"}])");
        auto stalledWorld=world;stalledWorld["day"].Integer()=4;
        stalledWorld["heroes"][0]["army_value"].Integer()=100;
        observeStrategicIntent(stalledCourse,stalledWorld);
        const auto captureSignals=strategicIntentSignals(stalledCourse,stalledWorld,true);
        require(captureSignals.size()==1 && captureSignals[0].question=="strategy:no_progress:capture",
            "completed army preparation hid stalled capture");
        require(strategicStalls(stalledCourse,stalledWorld)[0]["days_without_progress"].Integer()==3,
            "stall duration did not reach the request observation");
        auto nextDay=stalledWorld;nextDay["day"].Integer()=5;
        const auto nextSignals=strategicIntentSignals(stalledCourse,nextDay,true);
        RequestArbiter stallArbiter;stallArbiter.beginTurn(4,{280000,120000,0});
        const auto firstReview=stallArbiter.consider(captureSignals);require(firstReview.request,"stalled capture not admitted");
        stallArbiter.dispatched(firstReview);stallArbiter.finished(1000,1);
        stallArbiter.beginTurn(5,{280000,120000,0});
        require(stallArbiter.consider(nextSignals).request,"unanswered capture review vanished next day");
        for(const auto & signal:nextSignals) stallArbiter.resolved(signal);
        require(!stallArbiter.consider(nextSignals).request,"confirmed resolution repeated unchanged capture review");
        require(strategicStalls(stalledCourse,nextDay)[0]["days_without_progress"].Integer()==4,
            "model-facing delay did not advance independently of deduplication");
        auto premature=stalledWorld;premature["day"].Integer()=3;
        require(strategicStalls(stalledCourse,premature).Vector().empty(),"early capture incorrectly stalled");
        auto dependent=stalledCourse;
        dependent["milestones"][0]["depends_on"].Vector().emplace_back("army");
        dependent["progress"]["army"]["state"].String()="needs_confirmation";
        require(strategicStalls(dependent,stalledWorld).Vector().empty(),"unfinished preparation stalled future capture");
        auto owned=stalledCourse;owned["progress"]["capture"]["state"].String()="completed";
        require(strategicStalls(owned,stalledWorld).Vector().empty(),"historical capture mistaken for unfinished capture");
        auto configured=stalledCourse;configured["reconsider_when"].Vector().push_back(
            json(R"({"kind":"no_progress","milestone_id":"capture","reason":"Review conquest"})"));
        require(strategicIntentSignals(configured,stalledWorld,true).size()==1,"automatic review duplicated configured condition");

        auto cyclic=reply;cyclic["strategy_update"]["selected"]["milestones"][0]["depends_on"].Vector().emplace_back("visit");
        auto narrowed=request;narrowed["observation"]["objects"].Vector().erase(narrowed["observation"]["objects"].Vector().begin());
        JsonNode rejected;require(!validateStrategicIntentUpdate(reply,narrowed,world,plan,JsonNode(),rejected,reason),"unoffered native-only alias accepted");
        require(!validateStrategicIntentUpdate(cyclic,request,world,plan,JsonNode(),rejected,reason),"cyclic dependencies accepted");
        auto bad=reply;bad["operation_focus"]["bindings"][0]["milestone_id"].String()="unknown";
        require(!validateStrategicIntentUpdate(bad,request,world,plan,JsonNode(),rejected,reason),"unknown milestone accepted");
        bad=reply;bad["strategy_update"]["selected"]["milestones"][0]["complete_when"]["target_ref"].String()="hidden";
        require(!validateStrategicIntentUpdate(bad,request,world,plan,JsonNode(),rejected,reason),"hidden target accepted");
        JsonNode receipt;receipt["goal"]=goal;receipt["day"].Integer()=2;
        world["day"].Integer()=2;world["confirmed_site_visits"].Vector().push_back(receipt);
        // Presence, disappearance, and a receipt for a different actor/target/effect
        // must not complete an action milestone.
        auto wrongWorld=world;wrongWorld["confirmed_site_visits"][0]["goal"]["actor_ref"].String()="other";
        auto untouched=intent;observeStrategicIntent(untouched,wrongWorld);
        require(untouched["progress"]["visit"]["state"].String()!="completed","wrong actor completed milestone");
        wrongWorld=world;wrongWorld["confirmed_site_visits"][0]["goal"]["target_ref"].String()="far";
        observeStrategicIntent(untouched,wrongWorld);require(untouched["progress"]["visit"]["state"].String()!="completed","wrong target completed milestone");
        wrongWorld=world;wrongWorld["confirmed_site_visits"][0]["goal"]["kind"].String()="defend_area";
        observeStrategicIntent(untouched,wrongWorld);require(untouched["progress"]["visit"]["state"].String()!="completed","support defense completed milestone");
        // Original pending binding survives operation replacement and uses the
        // original goal snapshot, rather than fabricating a long-term goal.
        JsonNode pending;pending["action"]["goal_id"].String()="old";
        auto newPlan=plan;newPlan["revision"].Integer()=2;newPlan["goals"][0]["id"].String()="new";newPlan["goals"][0]["deadline_day"].Integer()=8;
        auto focus=reply["operation_focus"];focus["bindings"][0]["goal_id"].String()="new";
        bindStrategicOperation(intent,focus,newPlan,pending);
        require(intent["bindings"].Vector().size()==2,"pending original binding lost");
        observeStrategicIntent(intent,world);
        require(intent["progress"]["visit"]["state"].String()=="completed","original pending receipt did not complete milestone");
        require(validSavedStrategicIntent(intent),"pending course cannot restore");
        bindStrategicOperation(intent,focus,newPlan,JsonNode());
        require(intent["bindings"].Vector().size()==1,"retired binding retained after pending completion");
        require(intent["progress"]["visit"]["state"].String()=="completed","operation replacement erased confirmed milestone");
        request["strategic_intent"]=intent;
        auto keep=reply;keep["strategy_update"]=json(R"({"decision":"keep","base_revision":1,"selected":null,"change_reason":null})");keep["operation_focus"]=focus;
        JsonNode kept;require(validateStrategicIntentUpdate(keep,request,world,newPlan,intent,kept,reason),"operation revise with course keep rejected");
        bad=keep;bad["strategy_update"]["base_revision"].Integer()=0;
        require(!validateStrategicIntentUpdate(bad,request,world,newPlan,intent,rejected,reason),"stale revision accepted");
        bad=keep;bad["strategy_update"]["selected"]=selected;
        require(!validateStrategicIntentUpdate(bad,request,world,newPlan,intent,rejected,reason),"keep silently changed course");
        auto revise=reply;revise["strategy_update"]["base_revision"].Integer()=1;revise["operation_focus"]=focus;revise["operation_focus"]["revision"].Integer()=2;
        revise["strategy_update"]["selected"]["milestones"][1]["complete_when"]["target_ref"].String()="gate";
        revise["strategy_update"]["selected"]["milestones"][1]["complete_when"]["kind"].String()="passage_explored";
        JsonNode revised;require(validateStrategicIntentUpdate(revise,request,world,newPlan,intent,revised,reason),reason.c_str());
        require(revised["progress"]["visit"]["state"].String()!="completed","changed predicate inherited completion");
        // State fact completion is native, independent of a recruitment receipt.
        world["heroes"][0]["army_value"].Integer()=100;world["objects"][0]["owner"].Integer()=0;
        observeStrategicIntent(intent,world);
        require(intent["progress"]["army"]["state"].String()=="completed","native force fact not confirmed");
        require(intent["progress"]["capture"]["currently_satisfied"].Bool(),"current ownership missing");
        world["objects"][0]["owner"].Integer()=1;observeStrategicIntent(intent,world);
        require(intent["progress"]["capture"]["state"].String()=="completed" && !intent["progress"]["capture"]["currently_satisfied"].Bool(),"historic capture confused with current ownership");
        JsonNode saved;saved["object_ids"].Struct();saved["strategic_intent"]=intent;saved["native_campaign"]=newPlan;saved["request_arbiter"]["charged"].Integer()=42;
        auto restored=restoreNativeNamespace(saved);require(restored["strategic_intent"]==intent,"save/load changed course");
        saved["strategic_intent"]["version"].Integer()=99;restored=restoreNativeNamespace(saved);
        require(restored["strategic_intent"].isNull() && restored["native_campaign"]==newPlan && restored["request_arbiter"]==saved["request_arbiter"],"invalid course damaged valid operation/budget");
        saved["strategic_intent"]=intent;saved["object_ids"]["01"].Integer()=1;restored=restoreNativeNamespace(saved);
        require(restored["strategic_intent"].isNull() && restored["native_campaign"].isNull() && restored["request_arbiter"]==saved["request_arbiter"],"invalid namespace retained strategic refs or reset budget");
        auto rebound=untouched;bindStrategicOperation(rebound,focus,newPlan,JsonNode());
        auto currentReceipt=receipt;currentReceipt["goal"]=newPlan["goals"][0];
        auto rebindWorld=world;rebindWorld["confirmed_site_visits"].Vector().clear();rebindWorld["confirmed_site_visits"].Vector().push_back(currentReceipt);
        observeStrategicIntent(rebound,rebindWorld);
        require(rebound["progress"]["visit"]["state"].String()=="completed","new goal id/deadline receipt failed for unchanged milestone");
        auto movingWorld=request["observation"];movingWorld["heroes"][0]["position"]=json("[14,0,0]");movingWorld["objects"][0]["position"]=json("[0,0,0]");
        JsonNode opening=request;opening["strategic_intent"]=JsonNode();opening["observation"]=movingWorld;
        JsonNode moving;require(validateStrategicIntentUpdate(reply,opening,movingWorld,plan,JsonNode(),moving,reason),reason.c_str());
        bindStrategicOperation(moving,reply["operation_focus"],plan,JsonNode());
        // Capture has no explicit actor; give it an operation participant.
        moving["bindings"][0]["milestone_id"].String()="capture";
        moving["bindings"][0]["predicate_fingerprint"].String()=strategicPredicateFingerprint(moving["milestones"][0]["complete_when"]);
        observeStrategicIntent(moving,movingWorld);movingWorld["day"].Integer()=4;movingWorld["heroes"][0]["position"]=json("[12,0,0]");
        observeStrategicIntent(moving,movingWorld);
        require(moving["progress"]["capture"]["last_progress_day"].Integer()==4,"native approach did not advance milestone");
        require(strategicIntentSignals(moving,movingWorld,true).empty(),"progressing milestone triggered no-progress review");
        movingWorld["day"].Integer()=7;observeStrategicIntent(moving,movingWorld);
        const auto stalled=strategicIntentSignals(moving,movingWorld,true);
        require(stalled.size()==1,"stalled milestone did not trigger review");
        movingWorld["day"].Integer()=8;observeStrategicIntent(moving,movingWorld);
        require(strategicIntentSignals(moving,movingWorld,true)[0].facts==stalled[0].facts,"daily clock multiplied unchanged stagnation facts");
        auto damaged=intent;damaged["bindings"][0]["predicate_fingerprint"].String()="{}";
        require(!validSavedStrategicIntent(damaged),"malformed predicate fingerprint restored");
        saved["object_ids"].Struct().clear();saved["strategic_intent"]=intent;
        saved["pending_native_task"]=json(R"({"version":1,"before":{"day":1,"player":0,"resources":[0,0,0,0,0,0,0],"heroes":[{"ref":"hero","army_value":50,"position":[0,0,0]}],"towns":[]},"action":{"kind":"visit","goal_id":"old","native_goal_type":-1,"artifact_visit":{}}})");
        restored=restoreNativeNamespace(saved);
        require(restored["native_campaign"]==newPlan && !restored["pending_native_task"].isNull()
            && restored["pending_native_task"]["action"]["artifact_visit"].isNull(),"invalid optional pickup proof discarded valid pending operation");
        saved["site_receipts"]["old"]=receipt;saved["site_receipts"]["old"]["artifact_visit"].Struct();
        restored=restoreNativeNamespace(saved);
        require(restored["native_campaign"]==newPlan && restored["site_receipts"]["old"].isNull(),"invalid optional pickup receipt reset operation or remained usable");
        auto withSupport=saved;
        withSupport["building_progress"]["home:1"]=json(R"({"remaining":[1],"last_progress_day":1,"support":{"owned":true,"day":1,"treasury":[0,0,0,0,0,0,100],"available":[0,0,0,0,0,0,100],"remaining_cost":[0,0,0,0,0,0,200],"base_income":[0,0,0,0,0,0,10]}})");
        restored=restoreNativeNamespace(withSupport);
        require(restored["native_campaign"]==newPlan && restored["building_progress"]==withSupport["building_progress"],"valid building support cannot restore");
        for(const auto * field:{"owned","day","treasury","available","remaining_cost","base_income"})
        {
            auto corruptSupport=withSupport;corruptSupport["building_progress"]["home:1"]["support"][field].String()="bad";
            const auto cleared=restoreNativeNamespace(corruptSupport);
            require(cleared["building_progress"].isNull(),"corrupt building support retained progression permission");
        }
        saved["strategy_metadata"]["assignments"].Vector();
        saved["strategy_metadata"]["decision_basis"]=reply["decision_basis"];
        restored=restoreNativeNamespace(saved);
        require(restored["strategy_metadata"]["decision_basis"]==reply["decision_basis"],"accepted decision basis discarded on restore");
        auto coveredSave=saved;
        auto & coverage=coveredSave["strategy_metadata"]["question_coverage"];
        const auto & milestone=coveredSave["strategic_intent"]["milestones"][0]["id"];
        JsonNode covered;covered["question"].String()="strategy:no_progress:"+milestone.String();
        covered["facts"].String()="same native facts";covered["milestone_id"]=milestone;
        covered["campaign_revision"]=coveredSave["native_campaign"]["plan"]["revision"];
        // This fixture historically stored the raw plan. Use an actual saved
        // campaign shape for the new optional coverage validation.
        if(covered["campaign_revision"].isNull())
        { coveredSave["native_campaign"]["plan"]=newPlan;covered["campaign_revision"]=newPlan["revision"]; }
        covered["goal_ids"].Vector().push_back(newPlan["goals"][0]["id"]);
        coverage.Vector().push_back(covered);
        auto checkedCoverage=restoreNativeNamespace(coveredSave);
        require(checkedCoverage["strategy_metadata"]["question_coverage"]==coverage,"valid optional question coverage was lost");
        for(const auto * field:{"question","facts","milestone_id","campaign_revision","goal_ids"})
        {
            auto corrupt=coveredSave;corrupt["strategy_metadata"]["question_coverage"][0].Struct().erase(field);
            auto checked=restoreNativeNamespace(corrupt);
            require(checked["strategy_metadata"]["question_coverage"].isNull(),"incomplete coverage restored closure proof");
            require(checked["strategic_intent"]==coveredSave["strategic_intent"]
                && checked["native_campaign"]==coveredSave["native_campaign"],"bad optional coverage reset the namespace");
        }
        saved["strategy_metadata"].Struct().erase("decision_basis");
        restored=restoreNativeNamespace(saved);
        require(restored["native_campaign"]==newPlan && restored["strategic_intent"]==saved["strategic_intent"],"legacy optional basis reset namespace/course");
        saved.Struct().erase("strategic_intent");restored=restoreNativeNamespace(saved);
        require(restored["native_campaign"]==newPlan && restored["request_arbiter"]==saved["request_arbiter"],"old save without course lost operation or budget");
        auto unassigned=saved;unassigned["pending_native_task"]["action"]["goal_id"].String()="";
        unassigned["pending_native_task"]["action"]["campaign_revision"].Integer()=0;
        unassigned["pending_native_task"]["action"].Struct().erase("artifact_visit");
        restored=restoreNativeNamespace(unassigned);
        require(!restored["pending_native_task"].isNull() && restored["native_campaign"]==newPlan,"unassigned native task revision zero reset saved namespace");
        auto courseLoss=saved;courseLoss["strategic_intent"]=intent;courseLoss["strategic_intent"]["version"].Integer()=99;
        courseLoss["request_arbiter"]=json(R"({"version":1,"day":2,"requests":2,"wait_ms":150000,"tokens":42,"critical_reserve_ms":0,"addressed":{"initial_strategy":"no_selected_course","other":"unchanged"}})");
        restored=restoreNativeNamespace(courseLoss);
        auto expectedBudget=courseLoss["request_arbiter"];expectedBudget["addressed"].Struct().erase("initial_strategy");
        require(restored["request_arbiter"]==expectedBudget,"course corruption changed charged budget or other arbiter questions");
        ArbiterState ledger;ledger.day=2;ledger.requests=2;ledger.remaining={150000,42,0};
        for(const auto & [question,facts]:restored["request_arbiter"]["addressed"].Struct()) ledger.addressed[question]=facts.String();
        RequestArbiter recovered(ledger);
        require(recovered.consider(strategicIntentSignals(JsonNode(),world,true)).request,"discarded course initialization remained suppressed");
        ledger.remaining.waitMs=0;RequestArbiter exhausted(ledger);
        require(exhausted.consider(strategicIntentSignals(JsonNode(),world,true)).deadlineMs==80000,"spent legacy allowance blocked new course selection");
        courseLoss["strategic_intent"]=JsonNode();restored=restoreNativeNamespace(courseLoss);
        require(restored["request_arbiter"]==courseLoss["request_arbiter"],"null course timeout/rejection lost suppression baseline");
        std::cout << "strategic intent contract/progress/receipt/restore checks passed\n";
        return 0;
    }
    catch(const std::exception & error) { std::cerr << error.what() << '\n';return 1; }
}
