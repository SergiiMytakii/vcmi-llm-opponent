#include "Global.h"
#include "BackgroundPlanning.h"
#include <iostream>
int main()
{
    std::string raw((std::istreambuf_iterator<char>(std::cin)),{});
    JsonParsingSettings parser;parser.strict=true;parser.mode=JsonParsingSettings::JsonFormatMode::JSON;
    const JsonNode input(raw.data(),raw.size(),parser,"background admission proof");
    const auto & request=input["request"], & observed=input["observed"], & fresh=input["fresh"];
    nullkiller3::CampaignState current,candidate;std::string reason;JsonNode intent,derived,groups,result;
    if(!current.accept(request["campaign"],observed,reason)) {std::cerr<<reason;return 1;}
    current.review(fresh);
    const bool accepted=nullkiller3::admitPreparation(input["reply"],request,observed,fresh,current,
        request["strategic_intent"],input["pending"],candidate,intent,derived,groups,reason);
    result["accepted"].Bool()=accepted;result["reason"].String()=reason;result["groups"]=groups;
    result["candidate"]=derived;result["strategy_fresh"].Bool()=nullkiller3::preparationStrategyFresh(observed,fresh);
    result["scope"]=nullkiller3::preparationScope(observed,current);
    std::cout<<result.toCompactString()<<'\n';
}
