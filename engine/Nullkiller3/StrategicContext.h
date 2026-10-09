#pragma once

#include "CampaignState.h"

namespace nullkiller3
{
struct StrategicContextOptions
{
    bool preparation = false;
    bool detailed = false;
    bool includeIdle = false;
};

struct StrategicContext
{
    JsonNode observation;
    JsonNode memory;
    JsonNode evidenceRefs;
};

// Build only model-facing content. The caller owns the request envelope,
// final size limit and serialization, and retains native facts for admission.
StrategicContext buildStrategicContext(const JsonNode & world, const CampaignState & campaign,
    const JsonNode & persisted, const StrategicContextOptions & options);
}
