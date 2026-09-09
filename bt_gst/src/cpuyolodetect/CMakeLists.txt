cmake_minimum_required(VERSION 3.18)
project(cpuyolodetect LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
find_package(PkgConfig REQUIRED)
pkg_check_modules(GST_YOLO REQUIRED IMPORTED_TARGET
    gstreamer-1.0>=1.18
    gstreamer-base-1.0
    gstreamer-video-1.0)

set(ONNXRUNTIME_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../third_party/onnxruntime-linux-x64-1.29.0"
    CACHE PATH "ONNX Runtime SDK directory")
find_path(ONNXRUNTIME_INCLUDE_DIR NAMES onnxruntime_cxx_api.h
    HINTS "${ONNXRUNTIME_ROOT}/include" "${ONNXRUNTIME_ROOT}/include/onnxruntime")
find_library(ONNXRUNTIME_LIBRARY NAMES onnxruntime
    HINTS "${ONNXRUNTIME_ROOT}/lib" "${ONNXRUNTIME_ROOT}/lib64")
if(NOT ONNXRUNTIME_INCLUDE_DIR OR NOT ONNXRUNTIME_LIBRARY)
    message(FATAL_ERROR
        "A complete ONNX Runtime SDK is required. ONNXRUNTIME_ROOT=${ONNXRUNTIME_ROOT}; "
        "header=${ONNXRUNTIME_INCLUDE_DIR}; library=${ONNXRUNTIME_LIBRARY}. "
        "The SDK must contain onnxruntime_cxx_api.h and libonnxruntime.so.")
endif()

if(NOT TARGET ONNXRuntime::ONNXRuntime)
    add_library(ONNXRuntime::ONNXRuntime SHARED IMPORTED GLOBAL)
    set_target_properties(ONNXRuntime::ONNXRuntime PROPERTIES
        IMPORTED_LOCATION "${ONNXRUNTIME_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${ONNXRUNTIME_INCLUDE_DIR}")
endif()

add_library(yolo_core STATIC yolo_core.cpp)
set_target_properties(yolo_core PROPERTIES POSITION_INDEPENDENT_CODE ON)
target_include_directories(yolo_core PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")
target_compile_options(yolo_core PRIVATE -Wall -Wextra -Wpedantic)

add_library(gstcpuyolodetect SHARED gstcpuyolodetect.cpp)
target_link_libraries(gstcpuyolodetect PRIVATE yolo_core PkgConfig::GST_YOLO ONNXRuntime::ONNXRuntime)
target_compile_options(gstcpuyolodetect PRIVATE -Wall -Wextra -Wpedantic)
get_filename_component(ONNXRUNTIME_LIBRARY_DIR "${ONNXRUNTIME_LIBRARY}" DIRECTORY)
set_target_properties(gstcpuyolodetect PROPERTIES BUILD_RPATH "${ONNXRUNTIME_LIBRARY_DIR}")

add_executable(cpuyolodetect-check check.cpp)
target_link_libraries(cpuyolodetect-check PRIVATE yolo_core PkgConfig::GST_YOLO)
target_compile_options(cpuyolodetect-check PRIVATE -Wall -Wextra -Wpedantic)
enable_testing()
add_test(NAME cpuyolodetect-core COMMAND cpuyolodetect-check)
