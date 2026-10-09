#pragma once
#include "StrategicDecision.h"
namespace nullkiller3
{
// Native scope and admission are value contracts. No game command or pointer
// crosses this boundary; all route/safety inputs come from the own turn owner.
JsonNode preparationScope(const JsonNode & world,const CampaignState & campaign);
bool preparationStrategyFresh(const JsonNode & observed,const JsonNode & fresh);
struct PreparationQuestionCoverage
{
    std::vector<StrategicSignal> resolved;
    std::map<std::string,StrategicSignal> pending;
};
// Evaluate only after installing the admitted plan and metadata. Return the
// next question state without changing the live questions, arbiter or campaign.
PreparationQuestionCoverage preparationQuestionCoverage(const JsonNode & request,const JsonNode & groups,
    bool strategyFresh,const CampaignState & campaign,const JsonNode & intent,const JsonNode & metadata,
    const JsonNode & world,const std::map<std::string,StrategicSignal> & pending);
bool admitPreparation(const JsonNode & reply,const JsonNode & request,const JsonNode & observed,const JsonNode & fresh,
    const CampaignState & current,const JsonNode & intent,const JsonNode & pending,
    CampaignState & candidate,JsonNode & nextIntent,JsonNode & derived,JsonNode & groups,std::string & reason);
}
