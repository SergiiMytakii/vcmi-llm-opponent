#pragma once
#include "json/JsonNode.h"
#include <algorithm>
#include <set>

namespace nullkiller3
{
inline bool keymasterObject(const JsonNode & object)
{
    const auto & kind=object["kind"].String();
    return kind=="keymaster_tent" || kind=="border_guard" || kind=="border_gate";
}
inline bool strategicSiteAvailable(const JsonNode & object,const JsonNode & actor=JsonNode())
{
    if(!object["visible"].Bool() || !object["visited"].isBool() || object["visited"].Bool()) return false;
    const auto & kind=object["kind"].String();
    if(kind=="scholar" || kind=="treasure_chest" || kind=="obelisk" || kind=="artifact") return true;
    if(kind=="keymaster_tent") return object["key_owned"].isBool() && !object["key_owned"].Bool();
    if(kind!="border_guard" && kind!="border_gate") return false;
    if(!object["key_owned"].isBool() || !object["key_owned"].Bool()) return false;
    const auto & eligible=object["eligible_hero_refs"].Vector();
    return actor.isNull() ? !eligible.empty() : std::find(eligible.begin(),eligible.end(),actor)!=eligible.end();
}
// Link only presently visible sites. Matching colour proves a key relationship,
// never a hidden exit, onward objective, safe region or route feasibility.
inline void linkKeymasterSites(JsonNode & world)
{
    for(auto & site:world["visible_objects"].Vector())
    {
        if(!keymasterObject(site)) continue;
        site["matching_visible_refs"].Vector().clear();
        for(const auto & other:world["visible_objects"].Vector())
            if(keymasterObject(other) && other["ref"]!=site["ref"] && other["key_color"]==site["key_color"]
                && (other["kind"].String()=="keymaster_tent")!=(site["kind"].String()=="keymaster_tent"))
                site["matching_visible_refs"].Vector().push_back(other["ref"]);
    }
}
// Visit-end callbacks carry no object ID. Success comes from a fresh own view
// after the acknowledged task, not from the callback's null object pointer.
inline bool validArtifactInventory(const JsonNode & inventory)
{
    if(!inventory.isVector() || inventory.Vector().size()>1024) return false;
    std::set<int64_t> ids;
    for(const auto & id:inventory.Vector())
        if(id.getType()!=JsonNode::JsonType::DATA_INTEGER || id.Integer()<0 || id.Integer()>1000000000
            || !ids.insert(id.Integer()).second) return false;
    return true;
}
// Preserve the exact instance before map removal; a different item of the same
// type cannot satisfy this pickup, including after save/load reconciliation.
inline bool validArtifactVisitEvidence(const JsonNode & event)
{
    auto integer=[](const JsonNode & value,int64_t low,int64_t high) {
        return value.getType()==JsonNode::JsonType::DATA_INTEGER && value.Integer()>=low && value.Integer()<=high;
    };
    const auto & goal=event["goal"];
    if(!event.isStruct() || event["kind"].String()!="artifact" || !event["goal"].isStruct()
        || event["goal"]["kind"].String()!="visit_site"
        || !integer(event["day"],1,2147483647) || !integer(event["target_id"],0,1000000000)
        || !event["position"].isVector() || event["position"].Vector().size()!=3
        || !integer(goal["deadline_day"],1,2147483647)
        || goal["complete_when"]["kind"].String()!="site_visited"
        || !integer(goal["complete_when"]["value"],0,0)
        || !event["visit_started"].isBool() || !event["acknowledged"].isBool()
        || event["artifact_instance_id"].getType()!=JsonNode::JsonType::DATA_INTEGER
        || event["artifact_instance_id"].Integer()<0 || event["artifact_instance_id"].Integer()>1000000000
        || !validArtifactInventory(event["inventory_before"])) return false;
    for(const auto * field:{"id","actor_ref","target_ref"})
        if(!goal[field].isString() || goal[field].String().empty() || goal[field].String().size()>240) return false;
    for(const auto & axis:event["position"].Vector()) if(!integer(axis,0,100000)) return false;
    if(std::find(event["inventory_before"].Vector().begin(),event["inventory_before"].Vector().end(),event["artifact_instance_id"])
        !=event["inventory_before"].Vector().end()) return false;
    if(event["acknowledged"].Bool())
        return event["visit_started"].Bool() && validArtifactInventory(event["inventory_after"]);
    return event["inventory_after"].isNull();
}
inline bool artifactVisitConfirmed(const JsonNode & event)
{
    return validArtifactVisitEvidence(event) && event["acknowledged"].Bool()
        && std::find(event["inventory_after"].Vector().begin(),event["inventory_after"].Vector().end(),event["artifact_instance_id"])
            !=event["inventory_after"].Vector().end();
}
inline bool keySiteVisitConfirmed(const JsonNode & facts)
{
    if(facts["kind"].String()=="artifact") return facts["actor_owned"].Bool() && artifactVisitConfirmed(facts);
    if(!facts["actor_owned"].Bool() || !facts["target_visible"].Bool()) return false;
    const auto & kind=facts["kind"].String();
    if(kind=="border_guard") return !facts["target_present"].Bool();
    if(kind=="border_gate") return facts["target_present"].Bool()
        && facts["entry_allowed"].Bool() && facts["actor_at_target"].Bool();
    if(kind=="keymaster_tent") return facts["target_present"].Bool() && facts["visited_by_player"].Bool();
    return !facts["target_present"].Bool() || facts["visited_by_player"].Bool();
}
inline void recordStrategicSiteVisit(JsonNode & saved,const JsonNode & event)
{
    JsonNode receipt;receipt["goal"]=event["goal"];receipt["day"]=event["day"];
    if(event["kind"].String()=="artifact") receipt["artifact_visit"]=event;
    saved["site_receipts"][event["goal"]["id"].String()]=receipt;
    if(event["kind"].String()=="border_guard" || event["kind"].String()=="border_gate")
        saved["confirmed_border_visits"][event["goal"]["target_ref"].String()]=event["day"];
}

}
