cmake_minimum_required(VERSION 3.21)
project(IntermediatePreparationProof LANGUAGES CXX)
find_package(Boost REQUIRED)
find_path(VCMI_SOURCE_DIR Global.h REQUIRED)
find_library(VCMI_LIBRARY NAMES vcmi REQUIRED)
add_executable(intermediate-preparation-driver ../intermediate_preparation_driver.cpp
    ../../engine/Nullkiller3/CampaignState.cpp ../../engine/Nullkiller3/Forecasts.cpp)
target_compile_features(intermediate-preparation-driver PRIVATE cxx_std_20)
target_compile_definitions(intermediate-preparation-driver PRIVATE VCMI_DLL=1 BOOST_ALL_DYN_LINK)
target_include_directories(intermediate-preparation-driver PRIVATE ../../engine/Nullkiller3
    "${VCMI_SOURCE_DIR}" "${VCMI_SOURCE_DIR}/lib" "${VCMI_SOURCE_DIR}/include" ${Boost_INCLUDE_DIRS})
target_link_libraries(intermediate-preparation-driver PRIVATE "${VCMI_LIBRARY}")

add_executable(intermediate-admission-driver ../nullkiller3_idle_driver.cpp
    ../../engine/Nullkiller3/CampaignState.cpp ../../engine/Nullkiller3/Forecasts.cpp ../../engine/Nullkiller3/StrategicDecision.cpp)
target_compile_features(intermediate-admission-driver PRIVATE cxx_std_20)
target_compile_definitions(intermediate-admission-driver PRIVATE VCMI_DLL=1 BOOST_ALL_DYN_LINK)
target_include_directories(intermediate-admission-driver PRIVATE ../../engine/Nullkiller3
    "${VCMI_SOURCE_DIR}" "${VCMI_SOURCE_DIR}/lib" "${VCMI_SOURCE_DIR}/include" ${Boost_INCLUDE_DIRS})
target_link_libraries(intermediate-admission-driver PRIVATE "${VCMI_LIBRARY}")
