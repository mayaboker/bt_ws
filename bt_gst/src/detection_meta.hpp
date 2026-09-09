#pragma once

#include <gst/video/video.h>

namespace bt::gstmeta {

inline constexpr const char* kDetectionParameters = "bt-object-detection";

inline GstVideoRegionOfInterestMeta* add_detection(
    GstBuffer* buffer,
    const char* object_type,
    gint class_id,
    guint x,
    guint y,
    guint width,
    guint height,
    gdouble confidence,
    gboolean initialized)
{
    auto* roi = gst_buffer_add_video_region_of_interest_meta(
        buffer, object_type, x, y, width, height);
    if (!roi) return nullptr;

    auto* parameters = gst_structure_new(
        kDetectionParameters,
        "confidence", G_TYPE_DOUBLE, confidence,
        "class-id", G_TYPE_INT, class_id,
        "initialized", G_TYPE_BOOLEAN, initialized,
        nullptr);
    gst_video_region_of_interest_meta_add_param(roi, parameters);
    return roi;
}

}  // namespace bt::gstmeta
