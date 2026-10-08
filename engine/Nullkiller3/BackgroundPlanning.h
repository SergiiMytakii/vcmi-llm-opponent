#pragma once
#include "StrategicDecision.h"
namespace nullkiller3
{
// Native scope and admission are value contracts. No game command or pointer
// crosses this boundary; all route/safety inputs come from the own turn owner.
JsonNode preparationScope(const JsonNode & world,const CampaignState & campaign);
bool preparationStrategyFresh(const JsonNode & observed,const JsonNode & fresh);
bool admitPreparation(const JsonNode & reply,const JsonNode & request,const JsonNode & observed,const JsonNode & fresh,
    const CampaignState & current,const JsonNode & intent,const JsonNode & pending,
    CampaignState & candidate,JsonNode & nextIntent,JsonNode & derived,JsonNode & groups,std::string & reason);
}
