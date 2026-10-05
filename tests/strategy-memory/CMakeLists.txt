cmake_minimum_required(VERSION 3.21)
project(ExternalAIStrategyMemoryTests LANGUAGES CXX)

# Use headers and library from the same prepared VCMI revision/build.
find_package(Boost REQUIRED)
find_path(VCMI_SOURCE_DIR Global.h REQUIRED)
find_library(VCMI_LIBRARY NAMES vcmi REQUIRED)
add_executable(strategy-memory-driver ../strategy_memory_driver.cpp)
target_compile_features(strategy-memory-driver PRIVATE cxx_std_20)
target_compile_definitions(strategy-memory-driver PRIVATE VCMI_DLL=1 BOOST_ALL_DYN_LINK)
target_include_directories(strategy-memory-driver PRIVATE
    ../../engine/ExternalAI "${VCMI_SOURCE_DIR}" "${VCMI_SOURCE_DIR}/lib"
    "${VCMI_SOURCE_DIR}/include" ${Boost_INCLUDE_DIRS})
target_link_libraries(strategy-memory-driver PRIVATE "${VCMI_LIBRARY}")
enable_testing()
add_test(NAME strategy-memory COMMAND strategy-memory-driver)

add_executable(turn-batch-driver ../turn_batch_driver.cpp)
target_compile_features(turn-batch-driver PRIVATE cxx_std_20)
target_compile_definitions(turn-batch-driver PRIVATE VCMI_DLL=1 BOOST_ALL_DYN_LINK)
target_include_directories(turn-batch-driver PRIVATE
    ../../engine/ExternalAI "${VCMI_SOURCE_DIR}" "${VCMI_SOURCE_DIR}/lib"
    "${VCMI_SOURCE_DIR}/include" ${Boost_INCLUDE_DIRS})
target_link_libraries(turn-batch-driver PRIVATE "${VCMI_LIBRARY}")
add_test(NAME turn-batch COMMAND turn-batch-driver)

add_executable(nullkiller3-campaign-driver ../nullkiller3_campaign_driver.cpp)
target_compile_features(nullkiller3-campaign-driver PRIVATE cxx_std_20)
target_compile_definitions(nullkiller3-campaign-driver PRIVATE VCMI_DLL=1 BOOST_ALL_DYN_LINK)
target_include_directories(nullkiller3-campaign-driver PRIVATE
    ../../engine/Nullkiller3 "${VCMI_SOURCE_DIR}" "${VCMI_SOURCE_DIR}/lib"
    "${VCMI_SOURCE_DIR}/include" ${Boost_INCLUDE_DIRS})
target_link_libraries(nullkiller3-campaign-driver PRIVATE "${VCMI_LIBRARY}")
add_test(NAME nullkiller3-campaign COMMAND nullkiller3-campaign-driver)
