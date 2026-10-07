#include "Global.h"
#include "StrategicCandidates.h"
#include <iostream>
#include <iterator>
#include <stdexcept>
JsonNode parse(const std::string & raw)
{
    JsonParsingSettings parser;parser.strict=true;parser.mode=JsonParsingSettings::JsonFormatMode::JSON;
    return JsonNode(raw.data(),raw.size(),parser,"strategic candidates proof");
}
int main()
{
    try
    {
        const auto input=parse(std::string(std::istreambuf_iterator<char>(std::cin),{}));
        const auto & world=input["world"];const auto & plan=input["plan"];const auto & intent=input["intent"];
        int64_t calls=0;
        auto quote=[&](const JsonNode & pos,bool frontier,bool area) {
            ++calls;
            const auto ref="tile:"+pos.toCompactString();
            if(area) for(const auto & item:world["scouting_options"].Vector()) if(item["position"]==pos) return item["own_arrivals"];
            if(frontier) for(const auto & item:world["frontier_options"].Vector()) if(item["position"]==pos) return item["own_arrivals"];
            for(const auto & target:world["visible_objects"].Vector()) if(target["position"]==pos)
                for(const auto & item:world["forecasts"]["routes"].Vector()) if(item["target_ref"]==target["ref"]) return item["own_arrivals"];
            return parse("[]");
        };
        auto coverage=[&](const JsonNode & pos,int radius) {
            std::set<std::string> result;
            for(const auto & item:input["coverage"].Vector()) if(item["position"]==pos)
                for(const auto & cell:item["cells"].Vector()) result.insert(cell.String());
            return result;
        };
        JsonNode result;
        result["scouts"]=nullkiller3::generateScoutCandidates(world,plan,coverage,quote,intent);
        result["targets"]=nullkiller3::generateTargetCandidates(world,plan,quote,intent);
        auto generated=world;
        generated["frontier_options"]=result["scouts"]["frontiers"];
        generated["scouting_options"]=result["scouts"]["scouting"];
        generated["forecasts"]["routes"]=result["targets"]["routes"];
        result["view"]=nullkiller3::strategicCandidateView(generated,plan,intent);
        result["memory"]=nullkiller3::strategicCandidateMemory(input["memory"],result["view"]);
        result["overview"]=nullkiller3::strategicMapOverview(world,intent,!input["compact"].Bool());
        auto request=input["request"];
        if(request.isStruct())
        {
            result["request_fits"].Bool()=nullkiller3::boundStrategicRequest(request,input["max_bytes"].isNumber() ? input["max_bytes"].Integer() : 512*1024);
            result["bounded_request"]=request;
            result["request_bytes"].Integer()=nullkiller3::strategicRequestBytes(request);
        }
        for(const auto & fixture:input["income_cases"].Vector())
            result["effective_incomes"].Vector().emplace_back(nullkiller3::effectiveAIIncome(fixture["base"].Integer(),fixture["bonus"].Integer(),fixture["day_of_week"].Integer(),fixture["days_in_week"].Integer(),fixture["cap"].Integer()));
        if(input["configured_income_bonus"].isStruct())
        {
            auto configured=input["configured_income_bonus"];
            configured.setModScope("core"); // Real settings carry the originating mod namespace.
            result["economic_observation"]["weekly_bonus_percent"]=nullkiller3::projectStrategicBonusPercent(configured);
        }
        result["quote_calls"].Integer()=calls;
        std::cout<<result.toCompactString()<<'\n';return 0;
    }
    catch(const std::exception & error) {std::cerr<<error.what()<<'\n';return 1;}
}
