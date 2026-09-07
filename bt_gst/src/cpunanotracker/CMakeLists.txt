cmake_minimum_required(VERSION 3.18)
project(cpunanotrack LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
find_package(PkgConfig REQUIRED)
pkg_check_modules(GST REQUIRED IMPORTED_TARGET gstreamer-1.0 gstreamer-base-1.0 gstreamer-video-1.0)
find_package(OpenCV REQUIRED COMPONENTS core imgproc)
set(ONNXRUNTIME_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../third_party/onnxruntime-linux-x64-1.29.0"
    CACHE PATH "ONNX Runtime SDK directory")

# ONNX Runtime archives and distro packages use both include/ and
# include/onnxruntime, and both lib/ and lib64/. Prefer the requested SDK, but
# also allow a normal system installation when ONNXRUNTIME_ROOT is empty or
# incomplete. Keeping these as cache entries lets callers provide either path
# directly when their SDK has a non-standard layout.
find_path(ONNXRUNTIME_INCLUDE_DIR
    NAMES onnxruntime_cxx_api.h
    HINTS
        "${ONNXRUNTIME_ROOT}/include"
        "${ONNXRUNTIME_ROOT}/include/onnxruntime"
    DOC "Directory containing onnxruntime_cxx_api.h")
find_library(ONNXRUNTIME_LIBRARY
    NAMES onnxruntime
    HINTS
        "${ONNXRUNTIME_ROOT}/lib"
        "${ONNXRUNTIME_ROOT}/lib64"
    DOC "ONNX Runtime shared library")

if(NOT ONNXRUNTIME_INCLUDE_DIR OR NOT ONNXRUNTIME_LIBRARY)
    message(FATAL_ERROR
        "ONNX Runtime development files were not found.\n"
        "  ONNXRUNTIME_ROOT=${ONNXRUNTIME_ROOT}\n"
        "  header=${ONNXRUNTIME_INCLUDE_DIR}\n"
        "  library=${ONNXRUNTIME_LIBRARY}\n"
        "The SDK must contain onnxruntime_cxx_api.h and libonnxruntime.so. "
        "The current bundled directory may contain headers without the shared "
        "library. Extract a complete Linux x64 ONNX Runtime SDK, or configure "
        "with -DONNXRUNTIME_ROOT=/absolute/path/to/sdk (or set "
        "-DONNXRUNTIME_INCLUDE_DIR and -DONNXRUNTIME_LIBRARY explicitly).")
endif()

add_library(ONNXRuntime::ONNXRuntime SHARED IMPORTED)
set_target_properties(ONNXRuntime::ONNXRuntime PROPERTIES
    IMPORTED_LOCATION "${ONNXRUNTIME_LIBRARY}"
    INTERFACE_INCLUDE_DIRECTORIES "${ONNXRUNTIME_INCLUDE_DIR}")

add_library(gstcpunanotrack SHARED gstcpunanotrack.cpp)
target_include_directories(gstcpunanotrack PRIVATE ${OpenCV_INCLUDE_DIRS})
target_link_libraries(gstcpunanotrack PRIVATE PkgConfig::GST ${OpenCV_LIBS} ONNXRuntime::ONNXRuntime)
target_compile_options(gstcpunanotrack PRIVATE -Wall -Wextra)
# Keep the native build RPATH so the bundled ONNX Runtime is found by the plugin scanner.
get_filename_component(ONNXRUNTIME_LIBRARY_DIR "${ONNXRUNTIME_LIBRARY}" DIRECTORY)
set_target_properties(gstcpunanotrack PROPERTIES BUILD_RPATH "${ONNXRUNTIME_LIBRARY_DIR}")

set(METAPRINT_SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/../metaprint.cpp")
if(EXISTS "${METAPRINT_SOURCE}")
    add_library(gstmetaprint SHARED "${METAPRINT_SOURCE}")
    target_link_libraries(gstmetaprint PRIVATE PkgConfig::GST)
else()
    message(STATUS "Skipping gstmetaprint: ${METAPRINT_SOURCE} was not found")
endif()

add_executable(cpunanotracker-check check.cpp)
target_link_libraries(cpunanotracker-check PRIVATE PkgConfig::GST)
target_compile_options(cpunanotracker-check PRIVATE -Wall -Wextra)
enable_testing()
set(NANOTRACK_MODELS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../demos/nanotracker/onnx")
if(EXISTS "${NANOTRACK_MODELS_DIR}/nanotrack_backbone_template.onnx"
   AND EXISTS "${NANOTRACK_MODELS_DIR}/nanotrack_backbone.onnx"
   AND EXISTS "${NANOTRACK_MODELS_DIR}/nanotrack_head.onnx")
    add_test(NAME cpunanotracker COMMAND cpunanotracker-check "${NANOTRACK_MODELS_DIR}")
    set_tests_properties(cpunanotracker PROPERTIES
        ENVIRONMENT "GST_PLUGIN_PATH=$<TARGET_FILE_DIR:gstcpunanotrack>"
        TIMEOUT 120)
else()
    message(STATUS "Skipping cpunanotracker test: NanoTrack ONNX models were not found in ${NANOTRACK_MODELS_DIR}")
endif()
