cmake_minimum_required(VERSION 3.16)
project(gst_detector VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(PkgConfig REQUIRED)
pkg_check_modules(GSTREAMER REQUIRED IMPORTED_TARGET
  gstreamer-1.0
  gstreamer-base-1.0
  gstreamer-video-1.0
)

find_package(OpenCV REQUIRED COMPONENTS core imgproc)

add_library(gstcontrolledreddetect SHARED
  src/controlledreddetect.cpp
)

target_compile_options(gstcontrolledreddetect PRIVATE -Wall -Wextra -Wpedantic)
target_compile_definitions(gstcontrolledreddetect PRIVATE PACKAGE="gst_detector")
target_link_libraries(gstcontrolledreddetect
  PRIVATE
    PkgConfig::GSTREAMER
    ${OpenCV_LIBS}
)
target_include_directories(gstcontrolledreddetect
  PRIVATE
    ${OpenCV_INCLUDE_DIRS}
)

set_target_properties(gstcontrolledreddetect PROPERTIES
  PREFIX ""
  OUTPUT_NAME "libgstcontrolledreddetect"
)

install(TARGETS gstcontrolledreddetect
  LIBRARY DESTINATION lib/gstreamer-1.0
)
