#pragma once

#include "json/JsonNode.h"
#include "KeymasterAccess.h"
#include <boost/uuid/detail/sha1.hpp>
#include <algorithm>
#include <functional>
#include <cmath>
#include <map>
#include <optional>
#include <set>
#include <string>

namespace nullkiller3
{
// Version 3 extends the campaign vocabulary with executable native intentions.
// This value-only boundary receives a player-visible world, never game pointers.
class CampaignState
{
    JsonNode state;
    std::string restoreError;

    static bool integer(const JsonNode & value, int64_t low, int64_t high)
    {
        return value.getType() == JsonNode::JsonType::DATA_INTEGER && value.Integer() >= low && value.Integer() <= high;
    }
    static bool fields(const JsonNode & value, std::initializer_list<const char *> names)
    {
        if(!value.isStruct() || value.Struct().size() != names.size()) return false;
        for(const auto * name : names) if(!value.Struct().count(name)) return false;
        return true;
    }
    static bool goalFields(const JsonNode & value, std::initializer_list<const char *> names)
    {
        if(!value.isStruct()) return false;
        auto legacy=value;
        legacy.Struct().erase("risk");
        return fields(legacy,names);
    }
    static bool label(const JsonNode & value)
    {
        return value.isString() && !value.String().empty() && value.String().size() <= 120;
    }
    static bool resources(const JsonNode & value)
    {
        if(!value.isVector() || value.Vector().size() != 7) return false;
        for(const auto & amount : value.Vector()) if(!integer(amount, 0, 100000000)) return false;
        return true;
    }
    static const JsonNode & find(const JsonNode & world, const char * list, const JsonNode & ref)
    {
        static const JsonNode missing;
        for(const auto & object : world[list].Vector()) if(object["ref"] == ref) return object;
        return missing;
    }
    static bool contains(const JsonNode & list, const JsonNode & value)
    {
        return std::find(list.Vector().begin(), list.Vector().end(), value) != list.Vector().end();
    }
    bool atPreservationRefuge(const JsonNode & goal,const JsonNode & world) const;
    static bool failedCommitment(const JsonNode & status)
    {
        if(status["state"].String()=="cancelled") return true;
        if(status["state"].String()!="blocked") return false;
        const auto & reason=status["reason"].String();
        return reason=="deadline_missed" || reason=="executor_no_longer_owned" || reason=="target_no_longer_owned"
            || reason=="source_no_longer_owned" || reason=="recipient_sufficient_delivery_unconfirmed" || reason=="dependency_failed";
    }
    bool deliveryProved(const JsonNode & goal, const JsonNode & receipt) const
    {
        return receipt.isStruct() && sameGoal(receipt["goal"],goal) && label(receipt["source_ref"])
            && integer(receipt["day"],1,goal["deadline_day"].Integer())
            && integer(receipt["recipient_after"],goal["complete_when"]["value"].Integer(),1000000000)
            && (receipt["source_ref"] == goal["target_ref"] || plan()["policy"]["allow_helper_replacement"].Bool());
    }
    static bool passageProved(const JsonNode & goal,const JsonNode & receipt)
    {
        auto position=[](const JsonNode & value) {
            return value.isVector() && value.Vector().size()==3
                && integer(value[0],0,100000) && integer(value[1],0,100000) && integer(value[2],0,255);
        };
        return receipt.isStruct() && sameGoal(receipt["goal"],goal) && integer(receipt["day"],1,goal["deadline_day"].Integer())
            && position(receipt["from"]) && position(receipt["to"]) && receipt["from"]!=receipt["to"];
    }
    static bool siteProved(const JsonNode & goal,const JsonNode & receipt)
    {
        return fields(receipt,{"goal","day"}) && sameGoal(receipt["goal"],goal) && integer(receipt["day"],1,goal["deadline_day"].Integer());
    }
    static bool interceptionProved(const JsonNode & goal,const JsonNode & receipt)
    {
        return receipt.isStruct() && sameGoal(receipt["goal"],goal) && receipt["won"].isBool() && receipt["won"].Bool()
            && integer(receipt["day"],1,goal["deadline_day"].Integer());
    }
    static bool helperHireProved(const JsonNode & goal,const JsonNode & receipt)
    {
        return fields(receipt,{"goal","day","hero_ref","hero_type_id"}) && sameGoal(receipt["goal"],goal)
            && integer(receipt["day"],1,goal["deadline_day"].Integer()) && label(receipt["hero_ref"])
            && integer(receipt["hero_type_id"],0,1000000)
            && goal["candidate_ref"].String()=="tavern:"+std::to_string(receipt["hero_type_id"].Integer());
    }
    bool finished(const JsonNode & goal, const JsonNode & world) const;

public:
    // Only an explicit own counter and public standalone rule bound survival.
    static std::optional<int64_t> townlessCaptureDeadline(const JsonNode & world);
    bool validateTownlessRecovery(const JsonNode & world,std::string & reason) const;
    static bool sameGoal(const JsonNode & left,const JsonNode & right)
    {
        auto a=left,b=right;
        if(a.isStruct() && a["risk"].isNull()) a.Struct().erase("risk");
        if(b.isStruct() && b["risk"].isNull()) b.Struct().erase("risk");
        return a==b;
    }
    // A model risk grant belongs to exactly one named combat operation.
    // Unnamed native work and legacy plans retain the ordinary policy ceiling.
    double lossLimit(const JsonNode & goal) const
    {
        return goal["risk"].isStruct() ? goal["risk"]["max_loss_ratio"].Float()
            : (plan().isNull() ? .2 : plan()["policy"]["max_loss_ratio"].Float());
    }
    double lossLimit(const std::string & goalID) const
    {
        if(!goalID.empty()) for(const auto & goal:plan()["goals"].Vector())
            if(goal["id"].String()==goalID && holdsCommitment(goalID)) return lossLimit(goal);
        return lossLimit(JsonNode());
    }
    bool allowsLoss(const JsonNode & goal,int64_t army,int64_t loss) const
    {
        return army>0 && loss>=0 && loss<army && loss<=army*lossLimit(goal);
    }
    bool allowsLoss(const std::string & goalID,int64_t army,int64_t loss) const
    {
        return army>0 && loss>=0 && loss<army && loss<=army*lossLimit(goalID);
    }
    // Hiring names a current useful job, never a route for an unowned hero.
    static bool helperJobSupported(const JsonNode & goal,const JsonNode & world);
    bool holdsCommitment(const std::string & id) const
    {
        const auto & status=state["statuses"][id];
        return status["state"].String()!="completed" && status["state"].String()!="cancelled" && !failedCommitment(status);
    }
    bool requiresStabilization(const std::string & id) const
    {
        const auto & status=state["statuses"][id];
        return status["reason"].String()=="force_floor_breached"
            || (status["reason"].String()=="force_continuity_unconfirmed" && status["stabilized_day"].isNull());
    }
    // A town's upper army may physically belong to its garrison hero. The
    // current owned-world projection identifies that one pool without pointers.
    static std::string armyPool(const std::string & ref, const JsonNode & world)
    {
        const auto & town=find(world,"towns",JsonNode(ref));
        const auto & holder=town["army_holder_ref"];
        if(holder.isString() && !find(world,"heroes",holder).isNull()) return holder.String();
        return ref;
    }
    CampaignState() = default;
    explicit CampaignState(const JsonNode & saved);
    const std::string & restoreReason() const { return restoreError; }
    const JsonNode & plan() const { return state["plan"]; }
    JsonNode save() const { return state; }

    bool accept(const JsonNode & proposal, const JsonNode & world, std::string & reason, int64_t executionDay=0);

    // Facts for model correction, not a shortlist restricting strategic goals.
    // Every option is an offered native route; no private map facts are added.
    JsonNode routeFeedback(const JsonNode & goal,const JsonNode & world) const;

    bool hasSupportedRoute(const JsonNode & goal,const JsonNode & world) const
    { return routeFeedback(goal,world)["supported"].Bool(); }

    // Arbiter identity tracks constraint failures and offered corrections, not
    // local path scores or enumeration order. Keep saved facts bounded.
    std::string routeFeedbackFacts(const JsonNode & goal,const JsonNode & world) const;

    JsonNode review(const JsonNode & world,bool checkRoutes=true);
    void unconfirmedExecution(int firstDay);
    bool observeForceMinimum(const std::string & heroRef, int day, int64_t armyValue);
    void blocked(const std::string & goalID, const std::string & reason)
    {
        auto & status = state["statuses"][goalID];
        if(status["state"].String() == "completed") return;
        status["state"].String() = "blocked";
        status["reason"].String() = reason;
    }
    void waiting(const std::string & goalID,const std::string & reason)
    {
        auto & status=state["statuses"][goalID];
        if(status["state"].String()=="completed") return;
        status["state"].String()="waiting";
        status["reason"].String()=reason;
    }
    const JsonNode & statuses() const { return state["statuses"]; }
    // Replacements contain only freshly verified, owned helpers selected by
    // the native executor for this revision. They never change the recipient.
    std::string deliverySource(const JsonNode & goal, const std::map<std::string,std::string> & replacements = {}) const
    {
        const auto found = replacements.find(goal["id"].String());
        return found == replacements.end() ? goal["target_ref"].String() : found->second;
    }
    std::set<std::string> participantGoals(const std::string & ref,
        const std::map<std::string,std::string> & replacements = {}, const JsonNode & world = JsonNode()) const;
    // Starting force is protected only from unrelated exchanges. Its own
    // operation may spend that force under the existing battle-loss policy.
    int64_t operationForce(const std::string & ref,const JsonNode & world,const std::string & spendingGoal = {}) const;
    int64_t reservedForce(const std::string & ref, const JsonNode & world,
        const std::map<std::string,std::string> & replacements = {}, const std::string & spendingGoal = {}) const;
    int64_t exchangeForce(const std::string & ref,const JsonNode & world,
        const std::map<std::string,std::string> & replacements = {},const std::string & spendingGoal = {}) const
    {
        return std::max(reservedForce(ref,world,replacements,spendingGoal),operationForce(ref,world,spendingGoal));
    }
    JsonNode reservedResources(const std::string & spendingGoal = {}) const;
};
}
