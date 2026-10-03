#include "ProcessExchange.h"
#include <iostream>
#include <iterator>
#include <cstdlib>
#include <thread>

int main(int argc, char ** argv)
{
	if(argc < 3)
		return 2;
	std::atomic<bool> cancelled{false};
	const auto timeout = std::chrono::milliseconds(std::stoi(argv[1]));
	const std::string input(std::istreambuf_iterator<char>(std::cin), {});
	const std::vector<std::string> arguments(argv + 3, argv + argc);
	std::thread cancellation;
	if(const auto * delay = std::getenv("EXCHANGE_CANCEL_MS"))
		cancellation = std::thread([&, milliseconds = std::stoi(delay)]()
		{
			std::this_thread::sleep_for(std::chrono::milliseconds(milliseconds));
			cancelled = true;
		});
	auto reply = externalai::exchange(argv[2], arguments, input, timeout, cancelled);
	if(cancellation.joinable())
		cancellation.join();
	if(!reply.error.empty())
	{
		std::cerr << reply.error << '\n';
		return 1;
	}
	std::cout << reply.output;
}
