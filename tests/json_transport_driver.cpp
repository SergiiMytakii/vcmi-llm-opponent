#include <iostream>
#include <iterator>
#include <string>
#include "TransportJSON.h"

int main()
{
	const std::string input{std::istreambuf_iterator<char>(std::cin), {}};
	std::cout << ai_transport::transportJSON(input);
}
