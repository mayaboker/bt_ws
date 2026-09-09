cmake_minimum_required(VERSION 3.18)
project(bt_gst_native_plugins VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(CTest)

option(BT_GST_BUILD_CONTROLLED_RED_DETECT "Build controlledreddetect" OFF)
option(BT_GST_BUILD_CPU_NANOTRACK "Build cpunanotrack and metaprint" ON)
option(BT_GST_BUILD_CPU_YOLO_DETECT "Build cpuyolodetect" ON)

set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/plugins")
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")

set(BT_GST_PLUGIN_TARGETS "")
if(BT_GST_BUILD_CONTROLLED_RED_DETECT)
    add_subdirectory(plugins/gst_detector)
    list(APPEND BT_GST_PLUGIN_TARGETS gstcontrolledreddetect)
endif()
if(BT_GST_BUILD_CPU_NANOTRACK)
    add_subdirectory(src/cpunanotracker)
    list(APPEND BT_GST_PLUGIN_TARGETS gstcpunanotrack gstmetaprint)
endif()
if(BT_GST_BUILD_CPU_YOLO_DETECT)
    add_subdirectory(src/cpuyolodetect)
    list(APPEND BT_GST_PLUGIN_TARGETS gstcpuyolodetect)
endif()

if(BT_GST_PLUGIN_TARGETS)
    add_custom_target(bt-gst-plugins ALL DEPENDS ${BT_GST_PLUGIN_TARGETS})
    install(TARGETS ${BT_GST_PLUGIN_TARGETS}
        LIBRARY DESTINATION lib/gstreamer-1.0)
endif()

message(STATUS "bt_gst plugin output directory: ${CMAKE_LIBRARY_OUTPUT_DIRECTORY}")
