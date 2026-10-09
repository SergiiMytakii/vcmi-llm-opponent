#include "Global.h"
#include "BackgroundPlanning.h"
#include <iostream>

JsonNode question(const nullkiller3::StrategicSignal & signal)
{
    JsonNode item;item["question"].String()=signal.question;item["facts"].String()=signal.facts;
    item["critical"].Bool()=signal.critical;
    return item;
}

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
    if(accepted)
    {
        nullkiller3::bindStrategicOperation(intent,derived["operation_focus"],candidate.plan(),input["pending"]);
        auto metadata=derived;
        metadata["question_coverage"]=nullkiller3::acceptedQuestionCoverage(request["signals"],metadata,candidate,intent);
        std::map<std::string,nullkiller3::StrategicSignal> pending;
        for(const auto & item:input["pending_questions"].Vector())
            pending.insert_or_assign(item["question"].String(),nullkiller3::StrategicSignal{
                item["question"].String(),item["facts"].String(),true,true,true,item["critical"].Bool()});
        const auto before=candidate.save();
        const auto coverage=nullkiller3::preparationQuestionCoverage(request,groups,
            request["strategic_review"].Bool() && result["strategy_fresh"].Bool(),candidate,intent,metadata,fresh,pending);
        if(candidate.save()!=before) {std::cerr<<"coverage changed admitted campaign";return 1;}
        result["questions"]["resolved"].Vector();result["questions"]["pending"].Vector();
        for(const auto & signal:coverage.resolved) result["questions"]["resolved"].Vector().push_back(question(signal));
        for(const auto & [key,signal]:coverage.pending) result["questions"]["pending"].Vector().push_back(question(signal));
    }
    std::cout<<result.toCompactString()<<'\n';
}
