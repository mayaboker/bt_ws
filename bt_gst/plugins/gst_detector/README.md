# gst_detector

Standalone GStreamer C++ plugin project for the `controlledreddetect` element.

The element is based on the tutorial implementation at
`/home/user/projects/gst_cpp_plugin_tutorial/src/controlledreddetect.cpp`.
It accepts RGB raw video, detects red pixels using OpenCV HSV thresholding, and
attaches `GstRedDetectionMeta` custom metadata to each buffer.

## Dependencies

```sh
sudo apt install \
  build-essential \
  cmake \
  pkg-config \
  libgstreamer1.0-dev \
  libgstreamer-plugins-base1.0-dev \
  gstreamer1.0-tools \
  libopencv-dev
```

## Build

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build
```

## Inspect

```sh
GST_PLUGIN_PATH="$PWD/build" gst-inspect-1.0 controlledreddetect
```

## Example Pipeline

```sh
GST_PLUGIN_PATH="$PWD/build" \
gst-launch-1.0 -v \
  videotestsrc pattern=ball \
  ! video/x-raw,format=RGB,width=640,height=480,framerate=30/1 \
  ! controlledreddetect \
  ! videoconvert \
  ! fpsdisplaysink video-sink=glimagesink text-overlay=true
```

## Properties

- `detection-enabled`: enables or disables red detection.
- `low-h`, `low-s`, `low-v`: lower HSV threshold.
- `high-h`, `high-s`, `high-v`: upper HSV threshold. Hue is circular; setting
  `low-h` greater than `high-h` selects a wrapped interval such as `170..10`
  for both OpenCV red hue bands.
- `selector-state`: `0` disabled, `1` selecting, `2` locked.
- `selector-center-x`, `selector-center-y`: normalized selector center.
- `selector-width`, `selector-height`: selector dimensions in pixels.
- `minimum-area`, `minimum-coverage`: candidate qualification thresholds.

The detector finds separate external red contours. In selecting state it emits
only the contour under the selector; in locked state it associates subsequent
frames with that selected contour. Metadata also contains the selector and all
candidate rectangles for the bt_gst Cairo overlay.
