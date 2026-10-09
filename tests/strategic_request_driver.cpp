#include "Global.h"
#include "StrategicContext.h"
#include "StrategicMapOverview.h"
#include "../engine/TransportJSON/TransportJSON.h"
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
        const auto & persisted = input["persisted"];
        const auto & preparation = options["preparation"];
        const bool background = !preparation.isNull();
        bool detailed = persisted["strategic_intent"].isNull();
        for(const auto & signal : options["signals"].Vector())
        {
            const auto & question = signal["question"].String();
            detailed |= question.starts_with("strategy:") || question.starts_with("battle_loss:")
                || question.starts_with("critical_town:") || question.starts_with("defense:")
                || question.starts_with("checkpoint:") || question.starts_with("stagnation:");
        }
        if(background) detailed = preparation["strategic_review"].Bool();
        auto context = nullkiller3::buildStrategicContext(world, campaign, persisted,
            {background, detailed, options["include_idle"].Bool()});
        // Test-owned envelope: the production context API has no identity,
        // budget, transport or whole-request size responsibilities.
        JsonNode request;
        request["observation"] = std::move(context.observation);
        request["memory"] = std::move(context.memory);
        request["evidence_refs"] = std::move(context.evidenceRefs);
        request["protocol"].Integer() = 2;
        request["identity"] = options["identity"];
        request["request_id"] = options["request_id"];
        request["strategic_intent"] = persisted["strategic_intent"];
        request["campaign"] = campaign.plan();
        request["signals"] = options["signals"];
        request["budget"]["wait_ms"] = options["wait_ms"];
        request["budget"]["tokens"] = options["tokens"];
        if(background)
        {
            request["mode"].String() = "prepare_next_turn";
            request["execution_day"] = preparation["execution_day"];
            request["intent_revision"] = persisted["strategic_intent"]["revision"];
            request["strategic_review"] = preparation["strategic_review"];
            request["allowed_actor_refs"] = preparation["scope"]["actors"];
            request["allowed_target_refs"] = preparation["scope"]["targets"];
            request["routine_needs"] = preparation["scope"]["needs"];
        }
        nullkiller3::boundStrategicRequest(request);
        if(background)
        {
            std::set<std::string> exposed;
            for(const auto * list : {"heroes", "towns", "objects", "visible_objects"})
                for(const auto & item : request["observation"][list].Vector()) exposed.insert(item["ref"].String());
            for(const auto & ref : request["observation"]["frontiers"].Vector()) exposed.insert(ref.String());
            std::erase_if(request["allowed_target_refs"].Vector(), [&](const auto & ref) { return !exposed.count(ref.String()); });
        }
        const auto serialized = ai_transport::transportJSON(request.toCompactString());
        if(input.toCompactString() != before || campaign.save() != campaignBefore)
            throw std::runtime_error("request assembly changed its source facts");
        const JsonNode wire(serialized.data(), serialized.size(), parser, "assembled wire");
        if(wire != request) throw std::runtime_error("wire differs from request used for admission");
        std::cout << serialized << '\n';
        return serialized.size() <= 512 * 1024 ? 0 : 2;
    }
    catch(const std::exception & error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
