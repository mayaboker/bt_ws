#include <gst/base/gstbasetransform.h>
#include <gst/video/video.h>

#ifndef PACKAGE
#define PACKAGE "metaprint"
#endif

typedef struct _GstMetaPrint {
    GstBaseTransform parent;
} GstMetaPrint;

typedef struct _GstMetaPrintClass {
    GstBaseTransformClass parent_class;
} GstMetaPrintClass;

G_DEFINE_TYPE(GstMetaPrint, gst_meta_print, GST_TYPE_BASE_TRANSFORM)

static GstFlowReturn gst_meta_print_transform_ip(GstBaseTransform*, GstBuffer* buffer)
{
    gpointer state = nullptr;
    while (GstMeta* meta = gst_buffer_iterate_meta_filtered(
               buffer, &state, GST_VIDEO_REGION_OF_INTEREST_META_API_TYPE)) {
        auto* roi = reinterpret_cast<GstVideoRegionOfInterestMeta*>(meta);
        const gchar* roi_type = g_quark_to_string(roi->roi_type);
        GstStructure* params = gst_video_region_of_interest_meta_get_param(roi, "nanotrack");
        gboolean initialized = FALSE;
        gdouble confidence = 0.0;
        const gboolean has_initialized =
            params && gst_structure_get_boolean(params, "initialized", &initialized);
        const gboolean has_confidence =
            params && gst_structure_get_double(params, "confidence", &confidence);

        g_print("pts=%" GST_TIME_FORMAT " roi=%s box=%u,%u,%u,%u",
                GST_TIME_ARGS(GST_BUFFER_PTS(buffer)),
                roi_type ? roi_type : "unknown", roi->x, roi->y, roi->w, roi->h);
        if (has_initialized)
            g_print(" initialized=%s", initialized ? "true" : "false");
        if (has_confidence)
            g_print(" confidence=%.6f", confidence);
        g_print("\n");
    }
    return GST_FLOW_OK;
}

static void gst_meta_print_class_init(GstMetaPrintClass* klass)
{
    auto* element = GST_ELEMENT_CLASS(klass);
    auto* transform = GST_BASE_TRANSFORM_CLASS(klass);
    gst_element_class_set_static_metadata(
        element, "ROI metadata printer", "Filter/Debug/Video",
        "Prints GstVideoRegionOfInterestMeta attached to video buffers", "Betaloop");

    GstCaps* caps = gst_caps_from_string("video/x-raw");
    gst_element_class_add_pad_template(
        element, gst_pad_template_new("sink", GST_PAD_SINK, GST_PAD_ALWAYS, caps));
    gst_element_class_add_pad_template(
        element, gst_pad_template_new("src", GST_PAD_SRC, GST_PAD_ALWAYS, gst_caps_copy(caps)));
    gst_caps_unref(caps);

    transform->transform_ip = GST_DEBUG_FUNCPTR(gst_meta_print_transform_ip);
}

static void gst_meta_print_init(GstMetaPrint* self)
{
    gst_base_transform_set_in_place(GST_BASE_TRANSFORM(self), TRUE);
    gst_base_transform_set_passthrough(GST_BASE_TRANSFORM(self), TRUE);
}

static gboolean plugin_init(GstPlugin* plugin)
{
    return gst_element_register(plugin, "metaprint", GST_RANK_NONE, gst_meta_print_get_type());
}

GST_PLUGIN_DEFINE(GST_VERSION_MAJOR, GST_VERSION_MINOR, metaprint,
                  "Video ROI metadata printer", plugin_init,
                  "1.0", "LGPL", "metaprint", "https://example.com")
