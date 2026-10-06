#pragma once
#include "json/JsonNode.h"
#include <array>
#include <vector>
#include <algorithm>

namespace nullkiller3
{
// Own acknowledged resource packets within one native task. A net balance
// cannot distinguish a pickup followed by spending from a cheaper purchase.
class ResourceLedger
{
    using Funds=std::array<int64_t,7>;
    Funds balance{},debits{},credits{};
    std::vector<Funds> events;
    bool overflow=false;
    static Funds values(const JsonNode & node)
    {
        Funds result{};for(int i=0;i<7;++i) result[i]=node[i].Integer();return result;
    }
    static JsonNode node(const Funds & values)
    {
        JsonNode result;result.Vector();for(const auto value:values) result.Vector().emplace_back(value);return result;
    }
public:
    void begin(const JsonNode & funds)
    {
        balance=values(funds);debits={};credits={};events.clear();overflow=false;
    }
    void received(const JsonNode & funds)
    {
        const auto after=values(funds);
        if(after==balance) return;
        if(events.size()==256) overflow=true;
        if(!overflow)
        {
            Funds delta{};
            for(int i=0;i<7;++i)
            {
                delta[i]=after[i]-balance[i];
                debits[i]+=std::max<int64_t>(0,-delta[i]);credits[i]+=std::max<int64_t>(0,delta[i]);
            }
            events.push_back(delta);
        }
        balance=after;
    }
    JsonNode receipt(const JsonNode & funds) const
    {
        JsonNode result;
        const bool complete=!overflow && balance==values(funds);
        result["coverage"].String()=complete ? "complete" : overflow ? "overflow" : "unobserved_change";
        result["events"].Vector();for(const auto & event:events) result["events"].Vector().push_back(node(event));
        if(complete) { result["debits"]=node(debits);result["credits"]=node(credits); }
        result["limits"].String()="Own acknowledged resource packets during this task; debits include trades or other resource losses. Packet cause and purchase completion are not inferred.";
        return result;
    }
};
}
