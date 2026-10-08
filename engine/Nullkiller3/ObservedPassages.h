#pragma once
#include "json/JsonNode.h"
#include <algorithm>

namespace nullkiller3
{
inline bool passagePosition(const JsonNode & pos)
{
    if(!pos.isVector() || pos.Vector().size()!=3) return false;
    for(int axis=0;axis<3;++axis)
        if(pos[axis].getType()!=JsonNode::JsonType::DATA_INTEGER || pos[axis].Integer()<0
            || pos[axis].Integer()>(axis==2 ? 255 : 100000)) return false;
    return true;
}
inline bool validObservedPassages(const JsonNode & links)
{
    if(links.isNull()) return true;
    if(!links.isVector()) return false;
    for(const auto & link:links.Vector())
        if(!link.isStruct() || !passagePosition(link["from"]) || !passagePosition(link["to"]) || link["from"]==link["to"]) return false;
        else if(link["kind"].isNull()) {
            if(link.Struct().size()!=2 || link["from"][2].Integer()>=link["to"][2].Integer()) return false;
        } else if(link.Struct().size()!=5 || link["kind"].String()!="portal"
            || !link["bidirectional"].isBool() || !link["selectable"].isBool()) return false;
    return true;
}
// Only the native own-visit callback produces this fact. Goal replacement
// does not erase learned map connectivity; seeing endpoints is insufficient.
inline bool recordObservedPassage(JsonNode & links,const JsonNode & from,const JsonNode & to)
{
    if(!validObservedPassages(links) || !passagePosition(from) || !passagePosition(to) || from[2]==to[2]) return false;
    JsonNode link;link["from"]=from;link["to"]=to;
    if(from[2].Integer()>to[2].Integer()) std::swap(link["from"],link["to"]);
    auto & known=links.Vector();
    if(std::find(known.begin(),known.end(),link)!=known.end()) return false;
    known.push_back(link);return true;
}
inline bool recordObservedPortal(JsonNode & links,const JsonNode & from,const JsonNode & to,bool bidirectional,bool selectable)
{
    if(!validObservedPassages(links) || !passagePosition(from) || !passagePosition(to) || from==to) return false;
    JsonNode link;link["from"]=from;link["to"]=to;link["kind"].String()="portal";
    link["bidirectional"].Bool()=bidirectional;link["selectable"].Bool()=selectable;
    auto & known=links.Vector();
    if(std::find(known.begin(),known.end(),link)!=known.end()) return false;
    known.push_back(link);return true;
}
inline bool passageLinkFrom(const JsonNode & link,const JsonNode & position,bool guaranteed=false)
{
    if(guaranteed && !link["kind"].isNull() && !link["selectable"].Bool()) return false;
    return link["from"]==position || ((link["kind"].isNull() || link["bidirectional"].Bool()) && link["to"]==position);
}
inline bool observedPassageKnown(const JsonNode & links,const JsonNode & from,const JsonNode & to)
{
    if(!validObservedPassages(links)) return false;
    return std::any_of(links.Vector().begin(),links.Vector().end(),[&](const auto & link) {
        return (link["from"]==from && link["to"]==to)
            || (passageLinkFrom(link,from) && link["from"]==to && link["to"]==from);
    });
}

}
