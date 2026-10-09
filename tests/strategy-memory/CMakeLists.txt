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
add_test(NAME nullkiller3-income COMMAND nullkiller3-campaign-driver --income)

add_executable(nullkiller3-idle-driver ../nullkiller3_idle_driver.cpp)
target_compile_features(nullkiller3-idle-driver PRIVATE cxx_std_20)
target_compile_definitions(nullkiller3-idle-driver PRIVATE VCMI_DLL=1 BOOST_ALL_DYN_LINK)
target_include_directories(nullkiller3-idle-driver PRIVATE
    ../../engine/Nullkiller3 "${VCMI_SOURCE_DIR}" "${VCMI_SOURCE_DIR}/lib"
    "${VCMI_SOURCE_DIR}/include" ${Boost_INCLUDE_DIRS})
target_link_libraries(nullkiller3-idle-driver PRIVATE "${VCMI_LIBRARY}")
add_test(NAME nullkiller3-idle COMMAND nullkiller3-idle-driver)

add_executable(strategic-candidates-driver ../strategic_candidates_driver.cpp)
target_compile_features(strategic-candidates-driver PRIVATE cxx_std_20)
target_compile_definitions(strategic-candidates-driver PRIVATE VCMI_DLL=1 BOOST_ALL_DYN_LINK)
target_include_directories(strategic-candidates-driver PRIVATE
    ../../engine/Nullkiller3 "${VCMI_SOURCE_DIR}" "${VCMI_SOURCE_DIR}/lib"
    "${VCMI_SOURCE_DIR}/include" ${Boost_INCLUDE_DIRS})
target_link_libraries(strategic-candidates-driver PRIVATE "${VCMI_LIBRARY}")

add_executable(strategic-request-driver ../strategic_request_driver.cpp
    ../../engine/Nullkiller3/StrategicRequest.cpp
    ../../engine/TransportJSON/TransportJSON.cpp)
target_compile_features(strategic-request-driver PRIVATE cxx_std_20)
target_compile_definitions(strategic-request-driver PRIVATE VCMI_DLL=1 BOOST_ALL_DYN_LINK)
target_include_directories(strategic-request-driver PRIVATE
    ../../engine/Nullkiller3 "${VCMI_SOURCE_DIR}" "${VCMI_SOURCE_DIR}/lib"
    "${VCMI_SOURCE_DIR}/include" ${Boost_INCLUDE_DIRS})
target_link_libraries(strategic-request-driver PRIVATE "${VCMI_LIBRARY}")

# These consumers exercise the same separately compiled value-contract bodies
# that the native Nullkiller2 target includes through the project overlay.
foreach(target nullkiller3-campaign-driver nullkiller3-idle-driver strategic-candidates-driver strategic-request-driver)
    target_sources(${target} PRIVATE
        ../../engine/Nullkiller3/Forecasts.cpp
        ../../engine/Nullkiller3/CampaignState.cpp
        ../../engine/Nullkiller3/StrategicDecision.cpp)
endforeach()

# Header-only strategic course/progress and restore contract. This standalone
# driver reuses the prepared JSON library; it never builds or starts the game.
add_executable(strategic-intent-driver ../strategic_intent_driver.cpp)
target_compile_features(strategic-intent-driver PRIVATE cxx_std_20)
target_compile_definitions(strategic-intent-driver PRIVATE VCMI_DLL=1 BOOST_ALL_DYN_LINK)
target_include_directories(strategic-intent-driver PRIVATE
    ../../engine/Nullkiller3 "${VCMI_SOURCE_DIR}" "${VCMI_SOURCE_DIR}/lib"
    "${VCMI_SOURCE_DIR}/include" ${Boost_INCLUDE_DIRS})
target_link_libraries(strategic-intent-driver PRIVATE "${VCMI_LIBRARY}")
add_test(NAME strategic-intent COMMAND strategic-intent-driver)
add_executable(background-planning-driver ../background_planning_driver.cpp
    ../../engine/Nullkiller3/BackgroundPlanning.cpp ../../engine/Nullkiller3/Forecasts.cpp
    ../../engine/Nullkiller3/CampaignState.cpp ../../engine/Nullkiller3/StrategicDecision.cpp)
target_compile_features(background-planning-driver PRIVATE cxx_std_20)
target_compile_definitions(background-planning-driver PRIVATE VCMI_DLL=1 BOOST_ALL_DYN_LINK)
target_include_directories(background-planning-driver PRIVATE
    ../../engine/Nullkiller3 "${VCMI_SOURCE_DIR}" "${VCMI_SOURCE_DIR}/lib"
    "${VCMI_SOURCE_DIR}/include" ${Boost_INCLUDE_DIRS})
target_link_libraries(background-planning-driver PRIVATE "${VCMI_LIBRARY}")

add_executable(decision-wait-driver ../decision_wait_driver.cpp
    ../../engine/Nullkiller3/CampaignState.cpp ../../engine/Nullkiller3/Forecasts.cpp)
target_compile_features(decision-wait-driver PRIVATE cxx_std_20)
target_compile_definitions(decision-wait-driver PRIVATE VCMI_DLL=1 BOOST_ALL_DYN_LINK)
target_include_directories(decision-wait-driver PRIVATE
    ../../engine/Nullkiller3 "${VCMI_SOURCE_DIR}" "${VCMI_SOURCE_DIR}/lib"
    "${VCMI_SOURCE_DIR}/include" ${Boost_INCLUDE_DIRS})
target_link_libraries(decision-wait-driver PRIVATE "${VCMI_LIBRARY}")
add_test(NAME decision-wait COMMAND decision-wait-driver)
