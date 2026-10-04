add_library(ExternalAI OBJECT ExternalAI.cpp ProcessExchange.cpp VisiblePathfinder.cpp)
target_compile_definitions(ExternalAI PRIVATE VCMI_DLL=1)
target_link_libraries(ExternalAI PRIVATE vcmiMain)
