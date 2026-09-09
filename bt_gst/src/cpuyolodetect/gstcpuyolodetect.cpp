#include "yolo_core.hpp"
#include "../detection_meta.hpp"

#include <gst/base/gstbasetransform.h>
#include <gst/video/video.h>
#include <onnxruntime_cxx_api.h>

#include <chrono>
#include <fstream>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#ifndef PACKAGE
#define PACKAGE "cpuyolodetect"
#endif

GST_DEBUG_CATEGORY_STATIC(cpu_yolo_debug);
#define GST_CAT_DEFAULT cpu_yolo_debug

namespace {

class YoloRuntime {
public:
    YoloRuntime(const std::string& model_file, const std::string& labels_file, int intra_op_threads)
        : env_(ORT_LOGGING_LEVEL_WARNING, "cpuyolodetect"), memory_(Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault))
    {
        if (intra_op_threads > 0) options_.SetIntraOpNumThreads(intra_op_threads);
        options_.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_EXTENDED);
        session_ = std::make_unique<Ort::Session>(env_, model_file.c_str(), options_);
        if (session_->GetInputCount() != 1 || session_->GetOutputCount() != 1)
            throw std::runtime_error("expected exactly one model input and one output");

        const Ort::TypeInfo input_type = session_->GetInputTypeInfo(0);
        const auto input_info = input_type.GetTensorTypeAndShapeInfo();
        input_shape_ = input_info.GetShape();
        if (input_info.GetElementType() != ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT || input_shape_.size() != 4 ||
            input_shape_[0] != 1 || input_shape_[1] != 3 || input_shape_[2] <= 0 || input_shape_[3] <= 0)
            throw std::runtime_error("expected fixed FLOAT32 NCHW input [1,3,height,width]");
        height = static_cast<int>(input_shape_[2]);
        width = static_cast<int>(input_shape_[3]);

        const Ort::TypeInfo output_type = session_->GetOutputTypeInfo(0);
        const auto output_info = output_type.GetTensorTypeAndShapeInfo();
        output_shape_ = output_info.GetShape();
        if (output_info.GetElementType() != ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT || output_shape_.size() != 3 ||
            output_shape_[0] != 1 || output_shape_[1] < 5 || output_shape_[2] <= 0)
            throw std::runtime_error("expected raw FLOAT32 YOLO output [1,4+classes,candidates]");
        channels = static_cast<std::size_t>(output_shape_[1]);
        candidates = static_cast<std::size_t>(output_shape_[2]);

        Ort::AllocatorWithDefaultOptions allocator;
        input_name_ = session_->GetInputNameAllocated(0, allocator).get();
        output_name_ = session_->GetOutputNameAllocated(0, allocator).get();
        input_name_ptr_ = input_name_.c_str();
        output_name_ptr_ = output_name_.c_str();

        if (!labels_file.empty()) {
            labels = read_labels(labels_file);
            if (labels.size() != channels - 4) {
                std::ostringstream message;
                message << "labels count " << labels.size() << " does not match model class count " << channels - 4;
                throw std::runtime_error(message.str());
            }
        } else {
            labels.reserve(channels - 4);
            for (std::size_t class_id = 0; class_id < channels - 4; ++class_id)
                labels.push_back(std::to_string(class_id));
        }
        preprocessor = std::make_unique<bt::yolo::Preprocessor>(width, height);
        input_data_.resize(preprocessor->tensor_size());
        output_data_.resize(channels * candidates);
        input_tensor_ = Ort::Value::CreateTensor<float>(memory_, input_data_.data(), input_data_.size(),
                                                        input_shape_.data(), input_shape_.size());
        output_tensor_ = Ort::Value::CreateTensor<float>(memory_, output_data_.data(), output_data_.size(),
                                                         output_shape_.data(), output_shape_.size());
    }

    const std::vector<bt::yolo::Detection>& run(const bt::yolo::FrameView& frame,
                                                float confidence, float iou, std::size_t maximum,
                                                double& preprocess_ms, double& inference_ms, double& postprocess_ms)
    {
        const auto begin = std::chrono::steady_clock::now();
        const auto letterbox = preprocessor->run(frame, input_data_.data());
        const auto after_preprocess = std::chrono::steady_clock::now();
        session_->Run(Ort::RunOptions{nullptr}, &input_name_ptr_, &input_tensor_, 1,
                      &output_name_ptr_, &output_tensor_, 1);
        const auto after_inference = std::chrono::steady_clock::now();
        const auto& result = decoder.run(output_data_.data(), channels, candidates, letterbox,
                                         frame.width, frame.height, confidence, iou, maximum);
        const auto done = std::chrono::steady_clock::now();
        const auto milliseconds = [](auto a, auto b) {
            return std::chrono::duration<double, std::milli>(b - a).count();
        };
        preprocess_ms = milliseconds(begin, after_preprocess);
        inference_ms = milliseconds(after_preprocess, after_inference);
        postprocess_ms = milliseconds(after_inference, done);
        return result;
    }

    int width = 0;
    int height = 0;
    std::size_t channels = 0;
    std::size_t candidates = 0;
    std::vector<std::string> labels;
    std::unique_ptr<bt::yolo::Preprocessor> preprocessor;
    bt::yolo::Decoder decoder;

private:
    static std::vector<std::string> read_labels(const std::string& path)
    {
        std::ifstream input(path);
        if (!input) throw std::runtime_error("cannot open labels file: " + path);
        std::vector<std::string> labels;
        std::string line;
        while (std::getline(input, line)) {
            if (!line.empty() && line.back() == '\r') line.pop_back();
            if (line.empty()) throw std::runtime_error("labels file contains an empty label");
            labels.push_back(line);
        }
        if (!input.eof()) throw std::runtime_error("failed while reading labels file: " + path);
        return labels;
    }

    Ort::Env env_;
    Ort::SessionOptions options_;
    std::unique_ptr<Ort::Session> session_;
    Ort::MemoryInfo memory_;
    std::vector<int64_t> input_shape_;
    std::vector<int64_t> output_shape_;
    std::string input_name_;
    std::string output_name_;
    const char* input_name_ptr_ = nullptr;
    const char* output_name_ptr_ = nullptr;
    std::vector<float> input_data_;
    std::vector<float> output_data_;
    Ort::Value input_tensor_{nullptr};
    Ort::Value output_tensor_{nullptr};
};

}  // namespace

typedef struct _GstCpuYoloDetect {
    GstBaseTransform parent;
    GstVideoInfo video_info;
    gchar* model_file;
    gchar* labels_file;
    gint intra_op_threads;
    gdouble confidence_threshold;
    gdouble iou_threshold;
    guint max_detections;
    gboolean enabled;
    GMutex settings_mutex;
    YoloRuntime* runtime;
} GstCpuYoloDetect;

typedef struct _GstCpuYoloDetectClass { GstBaseTransformClass parent_class; } GstCpuYoloDetectClass;

#define GST_TYPE_CPU_YOLO_DETECT (gst_cpu_yolo_detect_get_type())
G_DEFINE_TYPE(GstCpuYoloDetect, gst_cpu_yolo_detect, GST_TYPE_BASE_TRANSFORM)

enum {
    PROP_0,
    PROP_MODEL_FILE,
    PROP_LABELS_FILE,
    PROP_INTRA_OP_THREADS,
    PROP_CONFIDENCE_THRESHOLD,
    PROP_IOU_THRESHOLD,
    PROP_MAX_DETECTIONS,
    PROP_ENABLED,
};

static GstStaticPadTemplate sink_template = GST_STATIC_PAD_TEMPLATE(
    "sink", GST_PAD_SINK, GST_PAD_ALWAYS,
    GST_STATIC_CAPS("video/x-raw,format=RGB,width=[1,MAX],height=[1,MAX]"));
static GstStaticPadTemplate src_template = GST_STATIC_PAD_TEMPLATE(
    "src", GST_PAD_SRC, GST_PAD_ALWAYS,
    GST_STATIC_CAPS("video/x-raw,format=RGB,width=[1,MAX],height=[1,MAX]"));

static void gst_cpu_yolo_detect_set_property(GObject* object, guint id, const GValue* value, GParamSpec* pspec)
{
    auto* self = reinterpret_cast<GstCpuYoloDetect*>(object);
    g_mutex_lock(&self->settings_mutex);
    switch (id) {
    case PROP_MODEL_FILE: g_free(self->model_file); self->model_file = g_value_dup_string(value); break;
    case PROP_LABELS_FILE: g_free(self->labels_file); self->labels_file = g_value_dup_string(value); break;
    case PROP_INTRA_OP_THREADS: self->intra_op_threads = g_value_get_int(value); break;
    case PROP_CONFIDENCE_THRESHOLD: self->confidence_threshold = g_value_get_double(value); break;
    case PROP_IOU_THRESHOLD: self->iou_threshold = g_value_get_double(value); break;
    case PROP_MAX_DETECTIONS: self->max_detections = g_value_get_uint(value); break;
    case PROP_ENABLED: self->enabled = g_value_get_boolean(value); break;
    default: g_mutex_unlock(&self->settings_mutex); G_OBJECT_WARN_INVALID_PROPERTY_ID(object, id, pspec); return;
    }
    g_mutex_unlock(&self->settings_mutex);
}

static void gst_cpu_yolo_detect_get_property(GObject* object, guint id, GValue* value, GParamSpec* pspec)
{
    auto* self = reinterpret_cast<GstCpuYoloDetect*>(object);
    g_mutex_lock(&self->settings_mutex);
    switch (id) {
    case PROP_MODEL_FILE: g_value_set_string(value, self->model_file); break;
    case PROP_LABELS_FILE: g_value_set_string(value, self->labels_file); break;
    case PROP_INTRA_OP_THREADS: g_value_set_int(value, self->intra_op_threads); break;
    case PROP_CONFIDENCE_THRESHOLD: g_value_set_double(value, self->confidence_threshold); break;
    case PROP_IOU_THRESHOLD: g_value_set_double(value, self->iou_threshold); break;
    case PROP_MAX_DETECTIONS: g_value_set_uint(value, self->max_detections); break;
    case PROP_ENABLED: g_value_set_boolean(value, self->enabled); break;
    default: g_mutex_unlock(&self->settings_mutex); G_OBJECT_WARN_INVALID_PROPERTY_ID(object, id, pspec); return;
    }
    g_mutex_unlock(&self->settings_mutex);
}

static gboolean gst_cpu_yolo_detect_start(GstBaseTransform* base)
{
    auto* self = reinterpret_cast<GstCpuYoloDetect*>(base);
    std::string model;
    std::string labels;
    int threads;
    g_mutex_lock(&self->settings_mutex);
    model = self->model_file ? self->model_file : "";
    labels = self->labels_file ? self->labels_file : "";
    threads = self->intra_op_threads;
    g_mutex_unlock(&self->settings_mutex);
    if (model.empty()) {
        GST_ELEMENT_ERROR(base, RESOURCE, NOT_FOUND, ("model-file is required"), (nullptr));
        return FALSE;
    }
    try {
        self->runtime = new YoloRuntime(model, labels, threads);
        GST_INFO_OBJECT(base, "loaded model input=%dx%d classes=%zu candidates=%zu",
                        self->runtime->width, self->runtime->height,
                        self->runtime->channels - 4, self->runtime->candidates);
        return TRUE;
    } catch (const std::exception& error) {
        GST_ELEMENT_ERROR(base, RESOURCE, OPEN_READ, ("failed to load YOLO model or labels"), ("%s", error.what()));
        return FALSE;
    }
}

static gboolean gst_cpu_yolo_detect_stop(GstBaseTransform* base)
{
    auto* self = reinterpret_cast<GstCpuYoloDetect*>(base);
    delete self->runtime;
    self->runtime = nullptr;
    return TRUE;
}

static gboolean gst_cpu_yolo_detect_set_caps(GstBaseTransform* base, GstCaps* input, GstCaps*)
{
    auto* self = reinterpret_cast<GstCpuYoloDetect*>(base);
    return gst_video_info_from_caps(&self->video_info, input) &&
           GST_VIDEO_INFO_FORMAT(&self->video_info) == GST_VIDEO_FORMAT_RGB;
}

static GstFlowReturn gst_cpu_yolo_detect_transform_ip(GstBaseTransform* base, GstBuffer* buffer)
{
    auto* self = reinterpret_cast<GstCpuYoloDetect*>(base);
    gboolean enabled;
    float confidence;
    float iou;
    guint maximum;
    g_mutex_lock(&self->settings_mutex);
    enabled = self->enabled;
    confidence = static_cast<float>(self->confidence_threshold);
    iou = static_cast<float>(self->iou_threshold);
    maximum = self->max_detections;
    g_mutex_unlock(&self->settings_mutex);
    if (!enabled) return GST_FLOW_OK;
    if (!self->runtime) {
        GST_ELEMENT_ERROR(base, CORE, FAILED, ("YOLO runtime is not initialized"), (nullptr));
        return GST_FLOW_ERROR;
    }
    if (!gst_buffer_is_writable(buffer)) {
        GST_ELEMENT_ERROR(base, STREAM, FAILED, ("in-place output buffer is not writable"), (nullptr));
        return GST_FLOW_ERROR;
    }

    GstVideoFrame frame;
    if (!gst_video_frame_map(&frame, &self->video_info, buffer, GST_MAP_READ)) {
        GST_ELEMENT_ERROR(base, RESOURCE, READ, ("failed to map RGB video frame"), (nullptr));
        return GST_FLOW_ERROR;
    }
    bool mapped = true;
    try {
        const bt::yolo::FrameView view{
            static_cast<const std::uint8_t*>(GST_VIDEO_FRAME_PLANE_DATA(&frame, 0)),
            GST_VIDEO_FRAME_WIDTH(&frame),
            GST_VIDEO_FRAME_HEIGHT(&frame),
            GST_VIDEO_FRAME_PLANE_STRIDE(&frame, 0)};
        double preprocess_ms, inference_ms, postprocess_ms;
        const auto& detections = self->runtime->run(view, confidence, iou, maximum,
                                                    preprocess_ms, inference_ms, postprocess_ms);
        gst_video_frame_unmap(&frame);
        mapped = false;

        for (std::size_t result_id = 0; result_id < detections.size(); ++result_id) {
            const auto& detection = detections[result_id];
            const auto& label = self->runtime->labels.at(detection.class_id);
            if (!bt::gstmeta::add_detection(
                    buffer, label.c_str(), static_cast<gint>(detection.class_id),
                    detection.x, detection.y, detection.width, detection.height,
                    detection.confidence, FALSE, static_cast<gint>(result_id)))
                throw std::runtime_error("failed to attach ROI detection metadata");
        }
        GST_LOG_OBJECT(base, "detections=%zu preprocess=%.3fms inference=%.3fms postprocess=%.3fms",
                       detections.size(), preprocess_ms, inference_ms, postprocess_ms);
        return GST_FLOW_OK;
    } catch (const std::exception& error) {
        if (mapped) gst_video_frame_unmap(&frame);
        GST_ELEMENT_ERROR(base, STREAM, FAILED, ("YOLO frame processing failed"), ("%s", error.what()));
        return GST_FLOW_ERROR;
    }
}

static void gst_cpu_yolo_detect_finalize(GObject* object)
{
    auto* self = reinterpret_cast<GstCpuYoloDetect*>(object);
    delete self->runtime;
    g_free(self->model_file);
    g_free(self->labels_file);
    g_mutex_clear(&self->settings_mutex);
    G_OBJECT_CLASS(gst_cpu_yolo_detect_parent_class)->finalize(object);
}

static void gst_cpu_yolo_detect_class_init(GstCpuYoloDetectClass* klass)
{
    auto* object_class = G_OBJECT_CLASS(klass);
    auto* element_class = GST_ELEMENT_CLASS(klass);
    auto* transform_class = GST_BASE_TRANSFORM_CLASS(klass);
    object_class->set_property = gst_cpu_yolo_detect_set_property;
    object_class->get_property = gst_cpu_yolo_detect_get_property;
    object_class->finalize = gst_cpu_yolo_detect_finalize;

    const auto ready = static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS | GST_PARAM_MUTABLE_READY);
    const auto playing = static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS | GST_PARAM_MUTABLE_PLAYING);
    g_object_class_install_property(object_class, PROP_MODEL_FILE,
        g_param_spec_string("model-file", "Model file", "Raw Ultralytics detection ONNX model", nullptr, ready));
    g_object_class_install_property(object_class, PROP_LABELS_FILE,
        g_param_spec_string("labels-file", "Labels file",
                            "Optional class labels, one per line; defaults to decimal class IDs", nullptr, ready));
    g_object_class_install_property(object_class, PROP_INTRA_OP_THREADS,
        g_param_spec_int("intra-op-threads", "Intra-op threads", "ONNX Runtime inference threads; zero uses its default",
                         0, G_MAXINT, 0, ready));
    g_object_class_install_property(object_class, PROP_CONFIDENCE_THRESHOLD,
        g_param_spec_double("confidence-threshold", "Confidence threshold", "Minimum best-class confidence",
                            0.0, 1.0, 0.4, playing));
    g_object_class_install_property(object_class, PROP_IOU_THRESHOLD,
        g_param_spec_double("iou-threshold", "IoU threshold", "Maximum same-class overlap retained by NMS",
                            0.0, 1.0, 0.7, playing));
    g_object_class_install_property(object_class, PROP_MAX_DETECTIONS,
        g_param_spec_uint("max-detections", "Maximum detections", "Maximum retained detections per frame",
                          1, G_MAXUINT, 100, playing));
    g_object_class_install_property(object_class, PROP_ENABLED,
        g_param_spec_boolean("enabled", "Enabled", "Run inference and attach detections", TRUE, playing));

    gst_element_class_set_static_metadata(element_class, "CPU YOLO detector", "Filter/Metadata/Video",
        "Runs raw Ultralytics ONNX inference and attaches ROI detection metadata", "bt_gst");
    gst_element_class_add_static_pad_template(element_class, &sink_template);
    gst_element_class_add_static_pad_template(element_class, &src_template);
    transform_class->start = GST_DEBUG_FUNCPTR(gst_cpu_yolo_detect_start);
    transform_class->stop = GST_DEBUG_FUNCPTR(gst_cpu_yolo_detect_stop);
    transform_class->set_caps = GST_DEBUG_FUNCPTR(gst_cpu_yolo_detect_set_caps);
    transform_class->transform_ip = GST_DEBUG_FUNCPTR(gst_cpu_yolo_detect_transform_ip);
}

static void gst_cpu_yolo_detect_init(GstCpuYoloDetect* self)
{
    gst_video_info_init(&self->video_info);
    g_mutex_init(&self->settings_mutex);
    self->confidence_threshold = 0.4;
    self->iou_threshold = 0.7;
    self->max_detections = 100;
    self->enabled = TRUE;
    gst_base_transform_set_in_place(GST_BASE_TRANSFORM(self), TRUE);
    gst_base_transform_set_passthrough(GST_BASE_TRANSFORM(self), FALSE);
}

static gboolean plugin_init(GstPlugin* plugin)
{
    GST_DEBUG_CATEGORY_INIT(cpu_yolo_debug, "cpuyolodetect", 0, "CPU YOLO detection");
    return gst_element_register(plugin, "cpuyolodetect", GST_RANK_NONE, GST_TYPE_CPU_YOLO_DETECT);
}

GST_PLUGIN_DEFINE(GST_VERSION_MAJOR, GST_VERSION_MINOR, cpuyolodetect,
                  "CPU Ultralytics YOLO detector", plugin_init, "1.0", "LGPL", "bt_gst",
                  "https://github.com/mayaboker/bt_ws")
