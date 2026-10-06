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
        if(!link.isStruct() || link.Struct().size()!=2 || !passagePosition(link["from"]) || !passagePosition(link["to"])
            || link["from"][2].Integer()>=link["to"][2].Integer()) return false;
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
}
