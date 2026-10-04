#pragma once

#include "json/JsonNode.h"

namespace externalai
{
// SaveLocalState keeps its upstream wire layout. AI updates use only its JSON.
inline JsonNode localStateUpdate(const JsonNode & state)
{
	JsonNode update;
	update["_namespaces"]["ExternalAI"] = state;
	return update;
}

// A namespace-only update leaves UI state untouched. Ordinary client snapshots
// replace UI state while preserving server-held namespaces.
inline bool applyLocalState(JsonNode & settings, const JsonNode & update)
{
	if(!update.isStruct()) return false;
	const auto found = update.Struct().find("_namespaces");
	if(update.Struct().size() == 1 && found != update.Struct().end())
	{
		if(!found->second.isStruct()) return false;
		for(const auto & [name, state] : found->second.Struct())
			settings["_namespaces"][name] = state;
		return true;
	}
	const auto namespaces = static_cast<const JsonNode &>(settings)["_namespaces"];
	settings = update;
	settings.Struct().erase("_namespaces");
	if(!namespaces.isNull()) settings["_namespaces"] = namespaces;
	return true;
}
}
