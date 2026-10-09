#include "Global.h"
#include "StrategicRequest.h"
#include <iostream>
#include <stdexcept>

int main()
{
    try
    {
        const std::string raw((std::istreambuf_iterator<char>(std::cin)), {});
        JsonParsingSettings parser;
        parser.strict = true;
        parser.mode = JsonParsingSettings::JsonFormatMode::JSON;
        const JsonNode input(raw.data(), raw.size(), parser, "strategic request proof");
        const auto before = input.toCompactString();
        const auto & world = input["world"];
        nullkiller3::CampaignState campaign;
        std::string reason;
        if(!input["campaign"].isNull() && !campaign.accept(input["campaign"], world, reason))
            throw std::runtime_error(reason);
        campaign.review(world);
        const auto campaignBefore = campaign.save();
        const auto & options = input["parameters"];
        nullkiller3::StrategicRequestParameters parameters;
        parameters.identity = options["identity"];
        parameters.requestID = options["request_id"].String();
        parameters.waitMs = options["wait_ms"].Integer();
        parameters.tokens = options["tokens"].Integer();
        parameters.includeIdle = options["include_idle"].Bool();
        for(const auto & signal : options["signals"].Vector())
            parameters.signals.push_back({signal["question"].String(), signal["facts"].String(),
                true, true, true, signal["critical"].Bool()});
        if(!options["preparation"].isNull())
        {
            const auto & preparation = options["preparation"];
            parameters.preparation = nullkiller3::PreparationRequest{
                preparation["execution_day"].Integer(), preparation["strategic_review"].Bool(), preparation["scope"]};
        }
        const auto result = nullkiller3::buildStrategicRequest(world, campaign, input["persisted"], parameters);
        if(input.toCompactString() != before || campaign.save() != campaignBefore)
            throw std::runtime_error("request assembly changed its source facts");
        const JsonNode wire(result.wire.data(), result.wire.size(), parser, "assembled wire");
        if(wire != result.request) throw std::runtime_error("wire differs from request used for admission");
        std::cout << result.wire << '\n';
        return result.fits() ? 0 : 2;
    }
    catch(const std::exception & error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
