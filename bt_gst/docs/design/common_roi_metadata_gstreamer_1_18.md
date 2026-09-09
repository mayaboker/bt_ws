# Common detection metadata for GStreamer 1.18

## Decision

`cpuyolodetect` and `cpunanotrack` use
`GstVideoRegionOfInterestMeta` as their only result metadata. This API is
available on GStreamer 1.18, unlike `GstAnalyticsODMtd` and
`objectdetectionoverlay`, which require GStreamer 1.24.

Both plugins call the shared writer in `src/detection_meta.hpp`, preventing the
field names and types from drifting apart.

## Buffer contract

Each result is one `GstVideoRegionOfInterestMeta`:

| Value | Type | Meaning |
| --- | --- | --- |
| `roi_type` | `GQuark` | YOLO label/numeric class ID, or `nanotrack` |
| `x`, `y`, `w`, `h` | `guint` | Box in input-frame pixels |
| parameter structure | `GstStructure` | Named `bt-object-detection` |
| `confidence` | `G_TYPE_DOUBLE` | Location confidence in `[0,1]` |
| `class-id` | `G_TYPE_INT` | YOLO class ID, or `-1` for NanoTrack |
| `initialized` | `G_TYPE_BOOLEAN` | True only for NanoTrack template capture |

Zero YOLO detections produce zero result ROIs. Multiple detections produce one
ROI per detection. NanoTrack produces one ROI per active frame; its template
capture has the selected box, confidence `0.0`, class ID `-1`, and
`initialized=true`. Disabled elements add no result metadata. Neither plugin
removes upstream metadata.

`cpuyolodetect` assigns ROI IDs sequentially from zero on each buffer. This
lets the GStreamer 1.18 Python application retrieve every result by ID, because
typed iteration over multiple ROI metas is not reliable through PyGObject on
the supported runtime.

## Reading the metadata

```cpp
gpointer state = nullptr;
while (GstMeta* raw = gst_buffer_iterate_meta_filtered(
           buffer, &state, GST_VIDEO_REGION_OF_INTEREST_META_API_TYPE)) {
    auto* roi = reinterpret_cast<GstVideoRegionOfInterestMeta*>(raw);
    auto* values = gst_video_region_of_interest_meta_get_param(
        roi, "bt-object-detection");
    if (!values) continue;

    gdouble confidence = 0.0;
    gint class_id = -1;
    gboolean initialized = FALSE;
    gst_structure_get_double(values, "confidence", &confidence);
    gst_structure_get_int(values, "class-id", &class_id);
    gst_structure_get_boolean(values, "initialized", &initialized);
    // roi->x, roi->y, roi->w, roi->h contain the box.
}
```

## Pipeline checks

YOLO metadata from the included video and model:

```bash
export GST_PLUGIN_PATH="$PWD/build/plugins${GST_PLUGIN_PATH:+:$GST_PLUGIN_PATH}"

gst-launch-1.0 -e \
  filesrc location="$PWD/assets/detection-demo.mp4" ! decodebin ! \
  videoconvert ! video/x-raw,format=RGB ! \
  cpuyolodetect model-file="$PWD/models/yolov8n.onnx" intra-op-threads=4 ! \
  metaprint ! fpsdisplaysink video-sink=fakesink text-overlay=false sync=false
```

NanoTrack metadata:

```bash
gst-launch-1.0 -e \
  videotestsrc num-buffers=30 ! video/x-raw,width=320,height=240 ! \
  videoconvert ! video/x-raw,format=BGR ! \
  cpunanotrack enabled=true roi="100,80,60,90" \
    models-dir="$PWD/src/cpunanotracker/models" ! \
  metaprint ! fakesink sync=false
```

`metaprint` prints the same structure for both producers. On GStreamer 1.18,
visualization uses the application's existing `cairooverlay` callback; the
standard `objectdetectionoverlay` element is not available.
