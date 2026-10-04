#pragma once
#include <string>

namespace externalai
{
// Remove only JSON whitespace outside strings; preserve the engine's value encoding.
inline std::string transportJSON(const std::string & json)
{
	std::string result;
	result.reserve(json.size());
	bool quoted = false, escaped = false;
	for(const char ch : json)
	{
		if(quoted)
		{
			result += ch;
			if(escaped) escaped = false;
			else if(ch == '\\') escaped = true;
			else if(ch == '"') quoted = false;
		}
		else if(ch == '"') { quoted = true; result += ch; }
		else if(ch != ' ' && ch != '\t' && ch != '\r' && ch != '\n') result += ch;
	}
	return result;
}
}
