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
        const auto & world=input["world"];const auto & plan=input["plan"];
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
        result["scouts"]=nullkiller3::generateScoutCandidates(world,plan,coverage,quote);
        result["targets"]=nullkiller3::generateTargetCandidates(world,plan,quote);
        auto generated=world;
        generated["frontier_options"]=result["scouts"]["frontiers"];
        generated["scouting_options"]=result["scouts"]["scouting"];
        generated["forecasts"]["routes"]=result["targets"]["routes"];
        result["view"]=nullkiller3::strategicCandidateView(generated,plan);
        result["memory"]=nullkiller3::strategicCandidateMemory(input["memory"],result["view"]);
        result["quote_calls"].Integer()=calls;
        std::cout<<result.toCompactString()<<'\n';return 0;
    }
    catch(const std::exception & error) {std::cerr<<error.what()<<'\n';return 1;}
}
