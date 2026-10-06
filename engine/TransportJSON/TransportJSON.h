#pragma once
#include <string>

namespace ai_transport
{
// Remove only JSON whitespace outside strings; preserve the engine's value encoding.
std::string transportJSON(const std::string & json);
}
