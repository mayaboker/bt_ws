#include <gst/base/gstbasetransform.h>
#include <gst/gst.h>
#include <gst/video/video.h>

#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <string>
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
  GMutex configMutex;
  guint selectorState = 1;
  gdouble selectorCenterX = 0.5;
  gdouble selectorCenterY = 0.5;
  guint selectorWidth = 80;
  guint selectorHeight = 80;
  guint minimumArea = 150;
  gdouble minimumCoverage = 0.30;
  gboolean hasTrackedTarget = FALSE;
  gint trackedX = 0;
  gint trackedY = 0;
  gint trackedWidth = 0;
  gint trackedHeight = 0;
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
  PROP_SELECTOR_STATE,
  PROP_SELECTOR_CENTER_X,
  PROP_SELECTOR_CENTER_Y,
  PROP_SELECTOR_WIDTH,
  PROP_SELECTOR_HEIGHT,
  PROP_MINIMUM_AREA,
  PROP_MINIMUM_COVERAGE,
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
  gint height,
  const cv::Rect &selector,
  gboolean selectorValid,
  guint selectorState,
  const std::vector<cv::Rect> &candidates)
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
    "selector-x", G_TYPE_INT, selector.x,
    "selector-y", G_TYPE_INT, selector.y,
    "selector-width", G_TYPE_INT, selector.width,
    "selector-height", G_TYPE_INT, selector.height,
    "selector-valid", G_TYPE_BOOLEAN, selectorValid,
    "selector-state", G_TYPE_UINT, selectorState,
    "candidate-count", G_TYPE_UINT, static_cast<guint>(candidates.size()),
    nullptr);
  for (guint index = 0; index < candidates.size(); ++index)
  {
    const auto &candidate = candidates[index];
    const std::string prefix = "candidate-" + std::to_string(index) + "-";
    gst_structure_set(
      structure,
      (prefix + "x").c_str(), G_TYPE_INT, candidate.x,
      (prefix + "y").c_str(), G_TYPE_INT, candidate.y,
      (prefix + "width").c_str(), G_TYPE_INT, candidate.width,
      (prefix + "height").c_str(), G_TYPE_INT, candidate.height,
      nullptr);
  }
}

void gst_controlled_red_detect_set_property(
  GObject *object,
  guint propertyId,
  const GValue *value,
  GParamSpec *pspec)
{
  auto *self = GST_CONTROLLED_RED_DETECT(object);
  g_mutex_lock(&self->configMutex);

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
    case PROP_SELECTOR_STATE:
      self->selectorState = g_value_get_uint(value);
      if (self->selectorState == 0)
      {
        self->hasTrackedTarget = FALSE;
      }
      break;
    case PROP_SELECTOR_CENTER_X:
      self->selectorCenterX = g_value_get_double(value);
      break;
    case PROP_SELECTOR_CENTER_Y:
      self->selectorCenterY = g_value_get_double(value);
      break;
    case PROP_SELECTOR_WIDTH:
      self->selectorWidth = g_value_get_uint(value);
      break;
    case PROP_SELECTOR_HEIGHT:
      self->selectorHeight = g_value_get_uint(value);
      break;
    case PROP_MINIMUM_AREA:
      self->minimumArea = g_value_get_uint(value);
      break;
    case PROP_MINIMUM_COVERAGE:
      self->minimumCoverage = g_value_get_double(value);
      break;
    default:
      g_mutex_unlock(&self->configMutex);
      G_OBJECT_WARN_INVALID_PROPERTY_ID(object, propertyId, pspec);
      break;
  }
  if (propertyId != PROP_0 && propertyId <= PROP_MINIMUM_COVERAGE)
  {
    g_mutex_unlock(&self->configMutex);
  }
}

void gst_controlled_red_detect_get_property(
  GObject *object,
  guint propertyId,
  GValue *value,
  GParamSpec *pspec)
{
  auto *self = GST_CONTROLLED_RED_DETECT(object);
  g_mutex_lock(&self->configMutex);

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
    case PROP_SELECTOR_STATE:
      g_value_set_uint(value, self->selectorState);
      break;
    case PROP_SELECTOR_CENTER_X:
      g_value_set_double(value, self->selectorCenterX);
      break;
    case PROP_SELECTOR_CENTER_Y:
      g_value_set_double(value, self->selectorCenterY);
      break;
    case PROP_SELECTOR_WIDTH:
      g_value_set_uint(value, self->selectorWidth);
      break;
    case PROP_SELECTOR_HEIGHT:
      g_value_set_uint(value, self->selectorHeight);
      break;
    case PROP_MINIMUM_AREA:
      g_value_set_uint(value, self->minimumArea);
      break;
    case PROP_MINIMUM_COVERAGE:
      g_value_set_double(value, self->minimumCoverage);
      break;
    default:
      g_mutex_unlock(&self->configMutex);
      G_OBJECT_WARN_INVALID_PROPERTY_ID(object, propertyId, pspec);
      break;
  }
  if (propertyId != PROP_0 && propertyId <= PROP_MINIMUM_COVERAGE)
  {
    g_mutex_unlock(&self->configMutex);
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

  gboolean detectionEnabled;
  guint lowH, lowS, lowV, highH, highS, highV;
  guint selectorState, selectorWidth, selectorHeight, minimumArea;
  gdouble selectorCenterX, selectorCenterY, minimumCoverage;
  g_mutex_lock(&self->configMutex);
  detectionEnabled = self->detectionEnabled;
  lowH = self->lowH;
  lowS = self->lowS;
  lowV = self->lowV;
  highH = self->highH;
  highS = self->highS;
  highV = self->highV;
  selectorState = self->selectorState;
  selectorCenterX = self->selectorCenterX;
  selectorCenterY = self->selectorCenterY;
  selectorWidth = self->selectorWidth;
  selectorHeight = self->selectorHeight;
  minimumArea = self->minimumArea;
  minimumCoverage = self->minimumCoverage;
  g_mutex_unlock(&self->configMutex);

  if (!detectionEnabled)
  {
    GST_LOG_OBJECT(base, "Detection disabled");
    attachDetectionMeta(base, buffer, FALSE, 0, 0, 0, 0, cv::Rect(), FALSE, 0, {});
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
    cv::Scalar(lowH, lowS, lowV),
    cv::Scalar(highH, highS, highV),
    mask);

  const cv::Mat kernel = cv::Mat::ones(5, 5, CV_8U);
  cv::morphologyEx(mask, mask, cv::MORPH_OPEN, kernel);
  cv::morphologyEx(mask, mask, cv::MORPH_CLOSE, kernel);

  std::vector<std::vector<cv::Point>> contours;
  cv::findContours(mask.clone(), contours, cv::RETR_EXTERNAL, cv::CHAIN_APPROX_SIMPLE);
  std::vector<cv::Rect> candidates;
  candidates.reserve(contours.size());
  for (const auto &contour : contours)
  {
    if (cv::contourArea(contour) >= minimumArea)
    {
      candidates.push_back(cv::boundingRect(contour));
    }
  }

  const gint requestedWidth = std::min<gint>(selectorWidth, width);
  const gint requestedHeight = std::min<gint>(selectorHeight, height);
  const gint centerX = std::clamp(
    static_cast<gint>(std::lround(selectorCenterX * width)),
    requestedWidth / 2,
    width - (requestedWidth - requestedWidth / 2));
  const gint centerY = std::clamp(
    static_cast<gint>(std::lround(selectorCenterY * height)),
    requestedHeight / 2,
    height - (requestedHeight - requestedHeight / 2));
  const cv::Rect selector(
    centerX - requestedWidth / 2,
    centerY - requestedHeight / 2,
    requestedWidth,
    requestedHeight);

  gboolean found = FALSE;
  gint boxX = 0;
  gint boxY = 0;
  gint boxWidth = 0;
  gint boxHeight = 0;

  gint selectedIndex = -1;
  if (selectorState == 1 && selector.area() > 0)
  {
    gdouble bestCoverage = -1.0;
    gdouble bestDistance = std::numeric_limits<gdouble>::max();
    for (guint index = 0; index < candidates.size(); ++index)
    {
      const auto &candidate = candidates[index];
      const cv::Point candidateCenter(
        candidate.x + candidate.width / 2,
        candidate.y + candidate.height / 2);
      if (!selector.contains(candidateCenter))
      {
        continue;
      }
      const gdouble coverage = static_cast<gdouble>(cv::countNonZero(mask(candidate))) /
        static_cast<gdouble>(candidate.area());
      if (coverage < minimumCoverage)
      {
        continue;
      }
      const gdouble distance = std::hypot(
        candidate.x + candidate.width / 2.0 - centerX,
        candidate.y + candidate.height / 2.0 - centerY);
      if (coverage > bestCoverage ||
          (std::abs(coverage - bestCoverage) < 1e-9 && distance < bestDistance))
      {
        bestCoverage = coverage;
        bestDistance = distance;
        selectedIndex = static_cast<gint>(index);
      }
    }
  }
  else if (selectorState == 2)
  {
    gboolean hasTrackedTarget;
    cv::Rect previous;
    g_mutex_lock(&self->configMutex);
    hasTrackedTarget = self->hasTrackedTarget;
    previous = cv::Rect(
      self->trackedX, self->trackedY, self->trackedWidth, self->trackedHeight);
    g_mutex_unlock(&self->configMutex);
    if (hasTrackedTarget)
    {
      const gdouble gate = std::max(50.0, 1.5 * std::hypot(previous.width, previous.height));
      gdouble bestDistance = gate;
      const cv::Point2d previousCenter(
        previous.x + previous.width / 2.0,
        previous.y + previous.height / 2.0);
      for (guint index = 0; index < candidates.size(); ++index)
      {
        const auto &candidate = candidates[index];
        const gdouble distance = std::hypot(
          candidate.x + candidate.width / 2.0 - previousCenter.x,
          candidate.y + candidate.height / 2.0 - previousCenter.y);
        if (distance <= bestDistance)
        {
          bestDistance = distance;
          selectedIndex = static_cast<gint>(index);
        }
      }
    }
  }

  if (selectedIndex >= 0)
  {
    const auto &box = candidates[selectedIndex];
    found = TRUE;
    boxX = box.x;
    boxY = box.y;
    boxWidth = box.width;
    boxHeight = box.height;
    g_mutex_lock(&self->configMutex);
    self->hasTrackedTarget = TRUE;
    self->trackedX = boxX;
    self->trackedY = boxY;
    self->trackedWidth = boxWidth;
    self->trackedHeight = boxHeight;
    g_mutex_unlock(&self->configMutex);
  }
  else if (selectorState == 1)
  {
    g_mutex_lock(&self->configMutex);
    self->hasTrackedTarget = FALSE;
    g_mutex_unlock(&self->configMutex);
  }

  gst_video_frame_unmap(&videoFrame);

  attachDetectionMeta(
    base, buffer, found, boxX, boxY, boxWidth, boxHeight,
    selector, found, selectorState, candidates);
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

void installDoubleProperty(
  GObjectClass *objectClass,
  guint propertyId,
  const gchar *name,
  const gchar *nick,
  const gchar *blurb,
  gdouble minimum,
  gdouble maximum,
  gdouble defaultValue)
{
  g_object_class_install_property(
    objectClass,
    propertyId,
    g_param_spec_double(
      name, nick, blurb, minimum, maximum, defaultValue,
      static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS)));
}

void gst_controlled_red_detect_finalize(GObject *object)
{
  auto *self = GST_CONTROLLED_RED_DETECT(object);
  g_mutex_clear(&self->configMutex);
  G_OBJECT_CLASS(gst_controlled_red_detect_parent_class)->finalize(object);
}

void gst_controlled_red_detect_class_init(GstControlledRedDetectClass *klass)
{
  auto *objectClass = G_OBJECT_CLASS(klass);
  auto *elementClass = GST_ELEMENT_CLASS(klass);
  auto *transformClass = GST_BASE_TRANSFORM_CLASS(klass);

  objectClass->set_property = gst_controlled_red_detect_set_property;
  objectClass->get_property = gst_controlled_red_detect_get_property;
  objectClass->finalize = gst_controlled_red_detect_finalize;

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
  installUintProperty(
    objectClass, PROP_SELECTOR_STATE, "selector-state", "Selector state",
    "0=disabled, 1=selecting, 2=locked", 2, 1);
  installDoubleProperty(
    objectClass, PROP_SELECTOR_CENTER_X, "selector-center-x", "Selector center X",
    "Normalized horizontal selector center", 0.0, 1.0, 0.5);
  installDoubleProperty(
    objectClass, PROP_SELECTOR_CENTER_Y, "selector-center-y", "Selector center Y",
    "Normalized vertical selector center", 0.0, 1.0, 0.5);
  installUintProperty(
    objectClass, PROP_SELECTOR_WIDTH, "selector-width", "Selector width",
    "Selector width in pixels", 4096, 80);
  installUintProperty(
    objectClass, PROP_SELECTOR_HEIGHT, "selector-height", "Selector height",
    "Selector height in pixels", 4096, 80);
  installUintProperty(
    objectClass, PROP_MINIMUM_AREA, "minimum-area", "Minimum contour area",
    "Minimum red contour area in pixels", 10000000, 150);
  installDoubleProperty(
    objectClass, PROP_MINIMUM_COVERAGE, "minimum-coverage", "Minimum red coverage",
    "Minimum red-mask coverage within a candidate bounding box", 0.0, 1.0, 0.30);

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
  g_mutex_init(&self->configMutex);

  self->detectionEnabled = TRUE;
  self->lowH = 0;
  self->lowS = 100;
  self->lowV = 100;
  self->highH = 10;
  self->highS = 255;
  self->highV = 255;
  self->selectorState = 1;
  self->selectorCenterX = 0.5;
  self->selectorCenterY = 0.5;
  self->selectorWidth = 80;
  self->selectorHeight = 80;
  self->minimumArea = 150;
  self->minimumCoverage = 0.30;
  self->hasTrackedTarget = FALSE;

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
