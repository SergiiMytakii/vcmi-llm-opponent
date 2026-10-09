#pragma once

#include "CampaignState.h"
#include "RequestArbiter.h"
#include <optional>

namespace nullkiller3
{
struct PreparationRequest
{
    int64_t executionDay;
    bool strategicReview;
    JsonNode scope;
};

// The turn owner decides when/why to request and supplies identity and limits.
// Assembly only reads these values; it never charges, persists or dispatches.
struct StrategicRequestParameters
{
    JsonNode identity;
    std::string requestID;
    std::vector<StrategicSignal> signals;
    int64_t waitMs;
    int64_t tokens;
    bool includeIdle = false;
    std::optional<PreparationRequest> preparation;
};

struct StrategicRequest
{
    JsonNode request;
    std::string wire;
    bool fits() const { return wire.size() <= 512 * 1024; }
};

// The complete model-facing copy, including mode-specific evidence and final
// wire size. Full native observations remain with the caller for fresh admission.
StrategicRequest buildStrategicRequest(const JsonNode & world, const CampaignState & campaign,
    const JsonNode & persisted, const StrategicRequestParameters & parameters);
}
