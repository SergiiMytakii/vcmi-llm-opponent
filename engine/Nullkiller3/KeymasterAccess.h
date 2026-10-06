#pragma once
#include "json/JsonNode.h"
#include <algorithm>

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
    if(kind=="scholar" || kind=="treasure_chest" || kind=="obelisk") return true;
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
inline bool keySiteVisitConfirmed(const JsonNode & facts)
{
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
    saved["site_receipts"][event["goal"]["id"].String()]=receipt;
    if(event["kind"].String()=="border_guard" || event["kind"].String()=="border_gate")
        saved["confirmed_border_visits"][event["goal"]["target_ref"].String()]=event["day"];
}

}
