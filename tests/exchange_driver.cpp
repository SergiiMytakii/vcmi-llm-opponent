#include "ProcessExchange.h"
#include <iostream>
#include <iterator>
#include <cstdlib>
#include <thread>
#ifdef _WIN32
#include <boost/locale/encoding_utf.hpp>
#endif

static int run(const std::vector<std::string> & argv)
{
	if(argv.size() < 3)
		return 2;
	std::atomic<bool> cancelled{false};
	const auto timeout = std::chrono::milliseconds(std::stoi(argv[1]));
	const std::string input(std::istreambuf_iterator<char>(std::cin), {});
	const std::vector<std::string> arguments(argv.begin() + 3, argv.end());
	std::thread cancellation;
	if(const auto * delay = std::getenv("EXCHANGE_CANCEL_MS"))
		cancellation = std::thread([&, milliseconds = std::stoi(delay)]()
		{
			std::this_thread::sleep_for(std::chrono::milliseconds(milliseconds));
			cancelled = true;
		});
	const auto * limit = std::getenv("EXCHANGE_REPLY_BYTES");
	auto reply = externalai::exchange(argv[2], arguments, input, timeout, cancelled,
		limit ? std::stoull(limit) : 8192);
	if(cancellation.joinable())
		cancellation.join();
	if(!reply.error.empty())
	{
		std::cerr << reply.error << '\n';
		return 1;
	}
	std::cout << reply.output;
	return 0;
}

#ifdef _WIN32
int wmain(int argc, wchar_t ** argv)
{
	std::vector<std::string> arguments;
	for(int i = 0; i < argc; ++i)
		arguments.push_back(boost::locale::conv::utf_to_utf<char>(std::wstring(argv[i])));
	return run(arguments);
}
#else
int main(int argc, char ** argv)
{
	return run({argv, argv + argc});
}
#endif
