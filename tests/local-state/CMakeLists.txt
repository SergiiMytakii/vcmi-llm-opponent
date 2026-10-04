cmake_minimum_required(VERSION 3.21)
project(ExternalAILocalStateTests LANGUAGES CXX)
find_package(Boost REQUIRED)
find_path(VCMI_SOURCE_DIR Global.h REQUIRED)
find_library(VCMI_LIBRARY NAMES vcmi REQUIRED)
add_executable(local-state-driver ../local_state_driver.cpp)
target_compile_features(local-state-driver PRIVATE cxx_std_20)
target_compile_definitions(local-state-driver PRIVATE VCMI_DLL=1 BOOST_ALL_DYN_LINK)
target_include_directories(local-state-driver PRIVATE
    ../../engine/ExternalAI "${VCMI_SOURCE_DIR}" "${VCMI_SOURCE_DIR}/lib"
    "${VCMI_SOURCE_DIR}/include" ${Boost_INCLUDE_DIRS})
target_link_libraries(local-state-driver PRIVATE "${VCMI_LIBRARY}")
enable_testing()
add_test(NAME local-state COMMAND local-state-driver)
