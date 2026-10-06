#pragma once
#include "json/JsonNode.h"
#include <algorithm>

namespace nullkiller3
{
inline bool recoveryInteger(const JsonNode & value)
{
    return value.getType()==JsonNode::JsonType::DATA_INTEGER && value.Integer()>=0 && value.Integer()<=2147483647;
}
inline JsonNode restoreReturnedHeroes(const JsonNode & markers)
{
    JsonNode restored;restored.Struct();
    if(!markers.isStruct()) return restored;
    for(const auto & [key,marker]:markers.Struct())
        if(marker.isStruct() && recoveryInteger(marker["hero_type_id"]) && recoveryInteger(marker["engine_object_id"])
            && recoveryInteger(marker["day"]) && marker["day"].Integer()>0
            && key==std::to_string(marker["hero_type_id"].Integer())
            && marker["return_kind"].isString()
            && (marker["return_kind"].String()=="escape" || marker["return_kind"].String()=="surrender")) restored[key]=marker;
    return restored;
}
inline bool isOwnReturnedHero(const JsonNode & markers,int heroType,int engineID)
{
    if(heroType<0 || engineID<0) return false;
    const auto & marker=markers[std::to_string(heroType)];
    return marker.isStruct() && marker["hero_type_id"].Integer()==heroType && marker["engine_object_id"].Integer()==engineID;
}
inline void recordOwnHeroReturn(JsonNode & markers,const JsonNode & result)
{
    if(!recoveryInteger(result["own_hero_type_id"]) || !recoveryInteger(result["engine_object_id"])
        || !recoveryInteger(result["day"]) || result["day"].Integer()==0
        || !result["won"].isBool() || !result["draw"].isBool() || result["won"].Bool() || result["draw"].Bool()) return;
    const auto key=std::to_string(result["own_hero_type_id"].Integer());
    if(!result["own_hero_return"].isString()) return;
    const auto & kind=result["own_hero_return"].String();
    if(kind=="normal")
    {
        if(isOwnReturnedHero(markers,result["own_hero_type_id"].Integer(),result["engine_object_id"].Integer())) markers.Struct().erase(key);
        return;
    }
    if(kind!="escape" && kind!="surrender") return;
    auto & marker=markers[key];
    marker["hero_type_id"]=result["own_hero_type_id"];marker["engine_object_id"]=result["engine_object_id"];
    marker["day"]=result["day"];marker["return_kind"].String()=kind;
}
// Each immutable battle receipt owns a separate namespace. Publishing it cannot
// replace the worker-owned campaign snapshot or unrelated client settings.
inline std::string ownHeroReturnNamespace(int heroType)
{
    return "Nullkiller3_return_"+std::to_string(heroType);
}
inline JsonNode consumedOwnHeroReturnUpdate(int heroType)
{
    JsonNode update;
    if(heroType>=0) update["_namespaces"][ownHeroReturnNamespace(heroType)]=JsonNode();
    return update;
}
inline JsonNode ownHeroReturnUpdate(const JsonNode & result)
{
    if(!recoveryInteger(result["own_hero_type_id"]) || !recoveryInteger(result["engine_object_id"])
        || !recoveryInteger(result["day"]) || result["day"].Integer()==0
        || !result["won"].isBool() || !result["draw"].isBool() || result["won"].Bool() || result["draw"].Bool()
        || !result["own_hero_return"].isString()) return {};
    const auto & kind=result["own_hero_return"].String();
    if(kind!="escape" && kind!="surrender" && kind!="normal") return {};
    JsonNode update,receipt;
    for(const auto * field:{"own_hero_type_id","engine_object_id","day","won","draw","own_hero_return"}) receipt[field]=result[field];
    update["_namespaces"][ownHeroReturnNamespace(result["own_hero_type_id"].Integer())]=receipt;
    return update;
}
// Call only after validating the original saved namespace. Independent receipts
// must not manufacture a saved namespace before fresh-game budget restoration.
inline JsonNode restoreOwnHeroReturns(const JsonNode & saved,const JsonNode & namespaces)
{
    if((!saved.isNull() && !saved.isStruct()) || !namespaces.isStruct()) return saved;
    const auto original=restoreReturnedHeroes(saved["own_returned_heroes"]);
    auto markers=original;
    // Explicit null receipts are successful hire/expired-roster tombstones.
    std::erase_if(markers.Struct(),[&](const auto & marker) {
        const auto found=namespaces.Struct().find(ownHeroReturnNamespace(marker.second["hero_type_id"].Integer()));
        return found!=namespaces.Struct().end() && found->second.isNull();
    });
    for(const auto & [name,receipt]:namespaces.Struct())
        if(receipt.isStruct() && recoveryInteger(receipt["own_hero_type_id"])
            && name==ownHeroReturnNamespace(receipt["own_hero_type_id"].Integer()))
            recordOwnHeroReturn(markers,receipt);
    if(markers==original) return saved;
    auto restored=saved;
    restored["own_returned_heroes"]=markers;
    return restored;
}
inline bool recoveryFundsAvailable(const JsonNode & funds,const JsonNode & locks,const JsonNode & reserved,int hireCost)
{
    for(const auto * amounts:{&funds,&locks,&reserved}) if(!amounts->isVector() || amounts->Vector().size()!=7) return false;
    for(int i=0;i<7;++i)
        if(funds[i].Integer()-locks[i].Integer()-reserved[i].Integer()<(i==6 ? hireCost : 0)) return false;
    return true;
}
}
