#pragma once
#include "json/JsonNode.h"
#include <algorithm>
#include <cstdint>
#include <map>
#include <set>
#include <string>
#include <tuple>

namespace nullkiller3
{
// Same whitespace rules as ai_transport::transportJSON. Count the serialized,
// escaped UTF-8 representation, including bytes inside quoted strings.
inline size_t strategicRequestBytes(const JsonNode & value)
{
    const auto raw=value.toCompactString();
    bool quoted=false,escaped=false;size_t bytes=0;
    for(char ch:raw)
    {
        if(quoted)
        {
            ++bytes;
            if(escaped) escaped=false;
            else if(ch=='\\') escaped=true;
            else if(ch=='"') quoted=false;
        }
        else if(ch=='"') {quoted=true;++bytes;}
        else if(ch!=' ' && ch!='\t' && ch!='\r' && ch!='\n') ++bytes;
    }
    return bytes;
}
inline std::set<std::string> strategicIntentCandidateRefs(const JsonNode & intent,bool includeCompleted=false)
{
    std::set<std::string> refs;
    for(const auto & milestone:intent["milestones"].Vector())
    {
        if(!includeCompleted && intent["progress"][milestone["id"].String()]["state"].String()=="completed") continue;
        for(const auto * field:{"target_ref","actor_ref"})
            if(milestone["complete_when"][field].isString()) refs.insert(milestone["complete_when"][field].String());
    }
    return refs;
}
inline JsonNode projectStrategicBonusPercent(const JsonNode & configured)
{
    auto result=configured;
    // Mod provenance is serializer metadata, not part of the player-visible DTO.
    result.setModScope("",true);
    return result;
}
// NewTurnProcessor applies this to income that already includes the handicap.
// Integer divisions must stay in native order; rounding a daily average differs.
inline int64_t effectiveAIIncome(int64_t income,int64_t weeklyBonus,int64_t dayOfWeek,int64_t daysInWeek,int64_t cap)
{
    if(daysInWeek<1 || dayOfWeek<1 || dayOfWeek>daysInWeek) return income;
    const auto before=income*weeklyBonus*(dayOfWeek-1)/daysInWeek/100;
    const auto after=income*weeklyBonus*dayOfWeek/daysInWeek/100;
    return std::min(cap,income+after-before);
}
inline void updateOverviewCoverage(JsonNode & overview)
{
    auto & coverage=overview["coverage"];
    coverage["shown_objects"].Integer()=overview["objects"].Vector().size();
    coverage["omitted_objects"].Integer()=std::max<int64_t>(0,coverage["known_objects"].Integer()-coverage["shown_objects"].Integer());
    coverage["complete"].Bool()=coverage["omitted_objects"].Integer()==0;
    coverage["unlisted_objects"].String()="Unlisted objects are omitted, not absent; coordinates do not establish reachability.";
}
inline JsonNode strategicMapOverview(const JsonNode & world,const JsonNode & intent,bool detailed)
{
    JsonNode result;
    result["detailed"].Bool()=detailed;
    for(const auto * field:{"map_size","visible_levels","visible_tile_counts","observed_passages","resources","resource_order","daily_income","economy","victory"})
        result[field]=world[field];
    result["objects"].Vector();
    std::map<std::string,JsonNode> known;
    // Only values already projected through the player view enter the overview.
    // A last observation remains labelled stale, never converted to visibility.
    for(const auto * field:{"objects","visible_objects","heroes","towns"})
        for(const auto & object:world[field].Vector())
        {
            if(!object["ref"].isString()) continue;
            if(object["visible"].isBool() && !object["visible"].Bool() && std::string(field)=="visible_objects") continue;
            auto item=object;
            if(std::string(field)=="objects" && item["stale"].Bool()) item["visible"].Bool()=false;
            if(std::string(field)=="heroes" || std::string(field)=="towns")
            {
                item["kind"].String()=std::string(field)=="heroes" ? "hero" : "town";
                item["owner"]=world["player"];item["visible"].Bool()=true;
            }
            known[item["ref"].String()]=item;
        }
    const auto active=strategicIntentCandidateRefs(intent,true);
    std::vector<JsonNode> ranked;
    std::set<std::tuple<std::string,std::string,int64_t,int64_t,int64_t>> represented;
    const auto width=std::max<int64_t>(1,world["map_size"][0].Integer());
    const auto height=std::max<int64_t>(1,world["map_size"][1].Integer());
    for(const auto & [ref,item]:known)
    {
        const auto & kind=item["kind"].String();
        if(kind!="town" && kind!="hero" && kind!="mine" && kind!="resource" && kind!="artifact"
            && kind!="subterranean_gate" && kind!="keymaster_tent" && kind!="border_guard" && kind!="border_gate"
            && kind!="scholar" && kind!="treasure_chest" && kind!="obelisk" && kind!="garrison" && kind!="monster") continue;
        ranked.push_back(item);
        result["summary"]["objects_by_kind"][kind].Integer()++;
        if(item["visible"].Bool()) result["summary"]["currently_visible_objects"].Integer()++;
    }
    auto priority=[&](const JsonNode & item) {
        const auto & kind=item["kind"].String();
        const bool own=item["owner"]==world["player"];
        if(own && (kind=="town" || kind=="hero")) return 0;
        if(!own && item["visible"].Bool() && (kind=="town" || kind=="hero")) return 1;
        if(active.count(item["ref"].String())) return 2;
        return 3;
    };
    std::sort(ranked.begin(),ranked.end(),[&](const auto & a,const auto & b){
        return std::tuple{priority(a),a["ref"].String()}<std::tuple{priority(b),b["ref"].String()};
    });
    auto sector=[&](const JsonNode & item) {
        const auto & p=item["position"];
        return std::tuple{item["kind"].String(),item["resource_type"].String(),p[2].Integer(),p[0].Integer()*3/width,p[1].Integer()*3/height};
    };
    std::vector<JsonNode> ordered,remaining;
    for(const auto & item:ranked)
        if(priority(item)<3 || represented.insert(sector(item)).second) ordered.push_back(item);
        else remaining.push_back(item);
    ordered.insert(ordered.end(),remaining.begin(),remaining.end());
    const size_t countLimit=detailed ? 384 : 64;
    const size_t byteLimit=detailed ? 160*1024 : 24*1024;
    size_t bytes=0;
    for(const auto & object:ordered)
    {
        // Ordinary updates carry relevant states; a detailed review additionally
        // contains public production/artifact effects and town development facts.
        if(!detailed && priority(object)>=3) continue;
        JsonNode item;
        for(const auto * field:{"ref","kind","owner","position","visible","stale","not_seen_at_last_position","last_seen_day","army_value","army_interval","visited","key_color","key_owned","resource_type","production_per_day","resource_visibility"})
            if(!object[field].isNull()) item[field]=object[field];
        if(object["visible"].Bool()) item["last_seen_day"]=world["day"];
        if(detailed)
            for(const auto * field:{"resource_amount","resource_amount_visibility","production_basis","artifact","daily_income","buildings","building_options","recruitment_options","army_units"})
                if(!object[field].isNull()) item[field]=object[field];
        const auto itemBytes=strategicRequestBytes(item);
        if(result["objects"].Vector().size()>=countLimit || bytes+itemBytes>byteLimit) continue;
        bytes+=itemBytes;result["objects"].Vector().push_back(std::move(item));
    }
    result["coverage"]["known_objects"].Integer()=ranked.size();
    result["coverage"]["object_limit"].Integer()=countLimit;
    result["coverage"]["object_bytes_limit"].Integer()=byteLimit;
    updateOverviewCoverage(result);
    return result;
}
inline bool requestContainsRef(const JsonNode & value,const std::string & ref)
{
    if(value.isVector()) for(const auto & item:value.Vector()) if(requestContainsRef(item,ref)) return true;
    if(value.isStruct())
    {
        if(value["ref"].isString() && value["ref"].String()==ref) return true;
        for(const auto & [key,item]:value.Struct()) if(requestContainsRef(item,ref)) return true;
    }
    return false;
}
// Returns false if required context alone cannot fit. Callers keep the previous
// accepted operation through the existing context-overflow failure accounting.
inline bool boundStrategicRequest(JsonNode & request,size_t maxBytes=512*1024)
{
    auto & overview=request["observation"]["map_overview"];
    while(strategicRequestBytes(request)>maxBytes && !overview["objects"].Vector().empty())
    {
        const auto ref=overview["objects"].Vector().back()["ref"].String();
        overview["objects"].Vector().pop_back();updateOverviewCoverage(overview);
        // Evidence refs are permission labels, not separate evidence. Retain a
        // label only if its object remains in another projected request field.
        auto withoutRefs=request;withoutRefs.Struct().erase("evidence_refs");
        withoutRefs["observation"].Struct().erase("evidence_refs");
        if(!requestContainsRef(withoutRefs,ref))
            for(auto * refs:{&request["evidence_refs"],&request["observation"]["evidence_refs"]})
                if(refs->isVector()) std::erase_if(refs->Vector(),[&](const auto & item){return item.isString() && (item.String()==ref || item.String()=="target:"+ref);});
    }
    return strategicRequestBytes(request)<=maxBytes;
}
}
