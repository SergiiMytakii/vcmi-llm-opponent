#include "Global.h"
#include "OffensivePreparation.h"
#include "StrategicCandidates.h"
#include <iostream>
#include <iterator>
int main(int argc,char ** argv)
{
    try
    {
        const std::string raw(std::istreambuf_iterator<char>(std::cin),{});
        JsonParsingSettings parser;parser.strict=true;parser.mode=JsonParsingSettings::JsonFormatMode::JSON;
        const JsonNode request(raw.data(),raw.size(),parser,"intermediate preparation");
        if(argc==2 && std::string(argv[1])=="--candidates")
        {
            const auto & world=request["observation"];
            const auto result=nullkiller3::generateTargetCandidates(world,request["campaign"],
                [&](const JsonNode & position,bool,bool) {
                    JsonNode routes;routes.Vector();
                    for(const auto & object:world["visible_objects"].Vector()) if(object["position"]==position)
                        for(const auto & entry:world["forecasts"]["routes"].Vector())
                            if(entry["target_ref"]==object["ref"]) return entry["own_arrivals"];
                    return routes;
                });
            std::cout<<result.toCompactString()<<'\n';return 0;
        }
        nullkiller3::CampaignState campaign;std::string reason;
        if(!campaign.accept(request["campaign"],request["observation"],reason)) throw std::runtime_error(reason);
        campaign.review(request["observation"]);
        std::cout<<nullkiller3::offensivePreparation(campaign,request["observation"]).toCompactString()<<'\n';
    }
    catch(const std::exception & error) {std::cerr<<error.what()<<'\n';return 1;}
}
