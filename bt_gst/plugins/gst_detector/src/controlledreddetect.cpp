#include <gst/base/gstbasetransform.h>
#include <gst/gst.h>
#include <gst/video/video.h>

#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>

#include <vector>

namespace
{

constexpr const char *kDetectionMetaName = "GstRedDetectionMeta";

GST_DEBUG_CATEGORY_STATIC(gst_controlled_red_detect_debug);
#define GST_CAT_DEFAULT gst_controlled_red_detect_debug

struct GstControlledRedDetect
{
  GstBaseTransform parent;
  GstVideoInfo videoInfo;
  gboolean detectionEnabled = TRUE;
  guint lowH = 0;
  guint lowS = 100;
  guint lowV = 100;
  guint highH = 10;
  guint highS = 255;
  guint highV = 255;
};

struct GstControlledRedDetectClass
{
  GstBaseTransformClass parentClass;
};

enum
{
  PROP_0,
  PROP_DETECTION_ENABLED,
  PROP_LOW_H,
  PROP_LOW_S,
  PROP_LOW_V,
  PROP_HIGH_H,
  PROP_HIGH_S,
  PROP_HIGH_V,
};

GType gst_controlled_red_detect_get_type();

#define GST_TYPE_CONTROLLED_RED_DETECT (gst_controlled_red_detect_get_type())
#define GST_CONTROLLED_RED_DETECT(obj) \
  (G_TYPE_CHECK_INSTANCE_CAST( \
    (obj), GST_TYPE_CONTROLLED_RED_DETECT, GstControlledRedDetect))

G_DEFINE_TYPE(
  GstControlledRedDetect,
  gst_controlled_red_detect,
  GST_TYPE_BASE_TRANSFORM)

GstStaticPadTemplate sinkTemplate =
  GST_STATIC_PAD_TEMPLATE(
    "sink",
    GST_PAD_SINK,
    GST_PAD_ALWAYS,
    GST_STATIC_CAPS("video/x-raw,format=RGB"));

GstStaticPadTemplate srcTemplate =
  GST_STATIC_PAD_TEMPLATE(
    "src",
    GST_PAD_SRC,
    GST_PAD_ALWAYS,
    GST_STATIC_CAPS("video/x-raw,format=RGB"));

void ensureDetectionMetaRegistered()
{
  if (gst_meta_get_info(kDetectionMetaName) == nullptr)
  {
    gst_meta_register_custom_simple(kDetectionMetaName);
  }
}

void attachDetectionMeta(
  GstBaseTransform *base,
  GstBuffer *buffer,
  gboolean found,
  gint x,
  gint y,
  gint width,
  gint height)
{
  ensureDetectionMetaRegistered();

  GstCustomMeta *meta = gst_buffer_add_custom_meta(buffer, kDetectionMetaName);
  if (meta == nullptr)
  {
    GST_WARNING_OBJECT(base, "Failed to attach %s", kDetectionMetaName);
    return;
  }

  GstStructure *structure = gst_custom_meta_get_structure(meta);
  gst_structure_set(
    structure,
    "found", G_TYPE_BOOLEAN, found,
    "x", G_TYPE_INT, x,
    "y", G_TYPE_INT, y,
    "width", G_TYPE_INT, width,
    "height", G_TYPE_INT, height,
    nullptr);
}

void gst_controlled_red_detect_set_property(
  GObject *object,
  guint propertyId,
  const GValue *value,
  GParamSpec *pspec)
{
  auto *self = GST_CONTROLLED_RED_DETECT(object);

  switch (propertyId)
  {
    case PROP_DETECTION_ENABLED:
      self->detectionEnabled = g_value_get_boolean(value);
      break;
    case PROP_LOW_H:
      self->lowH = g_value_get_uint(value);
      break;
    case PROP_LOW_S:
      self->lowS = g_value_get_uint(value);
      break;
    case PROP_LOW_V:
      self->lowV = g_value_get_uint(value);
      break;
    case PROP_HIGH_H:
      self->highH = g_value_get_uint(value);
      break;
    case PROP_HIGH_S:
      self->highS = g_value_get_uint(value);
      break;
    case PROP_HIGH_V:
      self->highV = g_value_get_uint(value);
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID(object, propertyId, pspec);
      break;
  }
}

void gst_controlled_red_detect_get_property(
  GObject *object,
  guint propertyId,
  GValue *value,
  GParamSpec *pspec)
{
  auto *self = GST_CONTROLLED_RED_DETECT(object);

  switch (propertyId)
  {
    case PROP_DETECTION_ENABLED:
      g_value_set_boolean(value, self->detectionEnabled);
      break;
    case PROP_LOW_H:
      g_value_set_uint(value, self->lowH);
      break;
    case PROP_LOW_S:
      g_value_set_uint(value, self->lowS);
      break;
    case PROP_LOW_V:
      g_value_set_uint(value, self->lowV);
      break;
    case PROP_HIGH_H:
      g_value_set_uint(value, self->highH);
      break;
    case PROP_HIGH_S:
      g_value_set_uint(value, self->highS);
      break;
    case PROP_HIGH_V:
      g_value_set_uint(value, self->highV);
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID(object, propertyId, pspec);
      break;
  }
}

gboolean gst_controlled_red_detect_set_caps(
  GstBaseTransform *base,
  GstCaps *inputCaps,
  GstCaps *outputCaps)
{
  (void)outputCaps;
  auto *self = GST_CONTROLLED_RED_DETECT(base);
  return gst_video_info_from_caps(&self->videoInfo, inputCaps);
}

GstFlowReturn gst_controlled_red_detect_transform_ip(
  GstBaseTransform *base,
  GstBuffer *buffer)
{
  auto *self = GST_CONTROLLED_RED_DETECT(base);

  if (!self->detectionEnabled)
  {
    GST_LOG_OBJECT(base, "Detection disabled");
    attachDetectionMeta(base, buffer, FALSE, 0, 0, 0, 0);
    return GST_FLOW_OK;
  }

  GstVideoFrame videoFrame;
  if (!gst_video_frame_map(&videoFrame, &self->videoInfo, buffer, GST_MAP_READ))
  {
    GST_WARNING_OBJECT(base, "Failed to map video frame");
    return GST_FLOW_ERROR;
  }

  auto *pixels = static_cast<guint8 *>(GST_VIDEO_FRAME_PLANE_DATA(&videoFrame, 0));
  const gint width = GST_VIDEO_FRAME_WIDTH(&videoFrame);
  const gint height = GST_VIDEO_FRAME_HEIGHT(&videoFrame);
  const gsize stride = GST_VIDEO_FRAME_PLANE_STRIDE(&videoFrame, 0);

  cv::Mat rgb(height, width, CV_8UC3, pixels, stride);

  cv::Mat hsv;
  cv::cvtColor(rgb, hsv, cv::COLOR_RGB2HSV);

  cv::Mat mask;
  cv::inRange(
    hsv,
    cv::Scalar(self->lowH, self->lowS, self->lowV),
    cv::Scalar(self->highH, self->highS, self->highV),
    mask);

  std::vector<cv::Point> redPixels;
  cv::findNonZero(mask, redPixels);

  gboolean found = FALSE;
  gint boxX = 0;
  gint boxY = 0;
  gint boxWidth = 0;
  gint boxHeight = 0;

  if (!redPixels.empty())
  {
    const cv::Rect box = cv::boundingRect(redPixels);
    found = TRUE;
    boxX = box.x;
    boxY = box.y;
    boxWidth = box.width;
    boxHeight = box.height;

    GST_LOG_OBJECT(
      base,
      "Red box found x=%d y=%d width=%d height=%d",
      boxX,
      boxY,
      boxWidth,
      boxHeight);
  }
  else
  {
    GST_LOG_OBJECT(base, "Red box not found");
  }

  gst_video_frame_unmap(&videoFrame);

  attachDetectionMeta(base, buffer, found, boxX, boxY, boxWidth, boxHeight);
  return GST_FLOW_OK;
}

void installUintProperty(
  GObjectClass *objectClass,
  guint propertyId,
  const gchar *name,
  const gchar *nick,
  const gchar *blurb,
  guint maximum,
  guint defaultValue)
{
  g_object_class_install_property(
    objectClass,
    propertyId,
    g_param_spec_uint(
      name,
      nick,
      blurb,
      0,
      maximum,
      defaultValue,
      static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS)));
}

void gst_controlled_red_detect_class_init(GstControlledRedDetectClass *klass)
{
  auto *objectClass = G_OBJECT_CLASS(klass);
  auto *elementClass = GST_ELEMENT_CLASS(klass);
  auto *transformClass = GST_BASE_TRANSFORM_CLASS(klass);

  objectClass->set_property = gst_controlled_red_detect_set_property;
  objectClass->get_property = gst_controlled_red_detect_get_property;

  g_object_class_install_property(
    objectClass,
    PROP_DETECTION_ENABLED,
    g_param_spec_boolean(
      "detection-enabled",
      "Detection enabled",
      "Run OpenCV red detection when enabled",
      TRUE,
      static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS)));

  installUintProperty(
    objectClass, PROP_LOW_H, "low-h", "Low hue",
    "Lower HSV hue threshold", 179, 0);
  installUintProperty(
    objectClass, PROP_LOW_S, "low-s", "Low saturation",
    "Lower HSV saturation threshold", 255, 100);
  installUintProperty(
    objectClass, PROP_LOW_V, "low-v", "Low value",
    "Lower HSV value threshold", 255, 100);
  installUintProperty(
    objectClass, PROP_HIGH_H, "high-h", "High hue",
    "Upper HSV hue threshold", 179, 10);
  installUintProperty(
    objectClass, PROP_HIGH_S, "high-s", "High saturation",
    "Upper HSV saturation threshold", 255, 255);
  installUintProperty(
    objectClass, PROP_HIGH_V, "high-v", "High value",
    "Upper HSV value threshold", 255, 255);

  gst_element_class_set_static_metadata(
    elementClass,
    "ControlledRedDetect",
    "Filter/Video",
    "Detects red pixels with configurable HSV thresholds",
    "Betaloop");

  gst_element_class_add_static_pad_template(elementClass, &sinkTemplate);
  gst_element_class_add_static_pad_template(elementClass, &srcTemplate);

  transformClass->set_caps =
    GST_DEBUG_FUNCPTR(gst_controlled_red_detect_set_caps);
  transformClass->transform_ip =
    GST_DEBUG_FUNCPTR(gst_controlled_red_detect_transform_ip);
}

void gst_controlled_red_detect_init(GstControlledRedDetect *self)
{
  gst_video_info_init(&self->videoInfo);

  self->detectionEnabled = TRUE;
  self->lowH = 0;
  self->lowS = 100;
  self->lowV = 100;
  self->highH = 10;
  self->highS = 255;
  self->highV = 255;

  gst_base_transform_set_in_place(GST_BASE_TRANSFORM(self), TRUE);
  gst_base_transform_set_passthrough(GST_BASE_TRANSFORM(self), FALSE);
}

gboolean pluginInit(GstPlugin *plugin)
{
  ensureDetectionMetaRegistered();

  GST_DEBUG_CATEGORY_INIT(
    gst_controlled_red_detect_debug,
    "controlledreddetect",
    0,
    "Configurable OpenCV red object detection filter");

  return gst_element_register(
    plugin,
    "controlledreddetect",
    GST_RANK_NONE,
    GST_TYPE_CONTROLLED_RED_DETECT);
}

}  // namespace

GST_PLUGIN_DEFINE(
  GST_VERSION_MAJOR,
  GST_VERSION_MINOR,
  controlledreddetect,
  "Configurable OpenCV red object detection filter",
  pluginInit,
  "0.1.0",
  "MIT",
  "gst_detector",
  "https://example.invalid/gst_detector")
