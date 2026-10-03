#pragma once

#include <atomic>
#include <chrono>
#include <string>
#include <vector>

namespace externalai
{
struct Reply
{
	std::string output;
	std::string error;
};

Reply exchange(const std::string & executable, const std::vector<std::string> & arguments,
	const std::string & input, std::chrono::milliseconds timeout, const std::atomic<bool> & cancelled);
}
