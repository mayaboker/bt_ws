#include "yolo_core.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace bt::yolo {
namespace {

float intersection_over_union(const Detection& a, const Detection& b)
{
    const int left = std::max(a.x, b.x);
    const int top = std::max(a.y, b.y);
    const int right = std::min(a.x + a.width, b.x + b.width);
    const int bottom = std::min(a.y + a.height, b.y + b.height);
    const int intersection_width = std::max(0, right - left);
    const int intersection_height = std::max(0, bottom - top);
    const double intersection = double(intersection_width) * intersection_height;
    const double area_a = double(a.width) * a.height;
    const double area_b = double(b.width) * b.height;
    const double union_area = area_a + area_b - intersection;
    return union_area > 0.0 ? static_cast<float>(intersection / union_area) : 0.0F;
}

std::uint8_t sample_bilinear(const FrameView& frame, float x, float y, int channel)
{
    x = std::clamp(x, 0.0F, static_cast<float>(frame.width - 1));
    y = std::clamp(y, 0.0F, static_cast<float>(frame.height - 1));
    const int x0 = static_cast<int>(std::floor(x));
    const int y0 = static_cast<int>(std::floor(y));
    const int x1 = std::min(x0 + 1, frame.width - 1);
    const int y1 = std::min(y0 + 1, frame.height - 1);
    const float wx = x - x0;
    const float wy = y - y0;
    const auto pixel = [&](int px, int py) {
        return float(frame.data[std::ptrdiff_t(py) * frame.stride + px * 3 + channel]);
    };
    const float top = pixel(x0, y0) + (pixel(x1, y0) - pixel(x0, y0)) * wx;
    const float bottom = pixel(x0, y1) + (pixel(x1, y1) - pixel(x0, y1)) * wx;
    return static_cast<std::uint8_t>(std::clamp(std::lround(top + (bottom - top) * wy), 0L, 255L));
}

}  // namespace

Preprocessor::Preprocessor(int model_width, int model_height)
    : model_width_(model_width), model_height_(model_height)
{
    if (model_width <= 0 || model_height <= 0)
        throw std::invalid_argument("model dimensions must be positive");
}

std::size_t Preprocessor::tensor_size() const
{
    return std::size_t(model_width_) * model_height_ * 3;
}

Letterbox Preprocessor::run(const FrameView& source, float* nchw) const
{
    if (!source.data || !nchw || source.width <= 0 || source.height <= 0 ||
        source.stride < std::ptrdiff_t(source.width) * 3)
        throw std::invalid_argument("invalid packed RGB frame");

    Letterbox box;
    box.scale = std::min(float(model_width_) / source.width, float(model_height_) / source.height);
    box.resized_width = std::max(1, static_cast<int>(std::lround(source.width * box.scale)));
    box.resized_height = std::max(1, static_cast<int>(std::lround(source.height * box.scale)));
    box.resized_width = std::min(box.resized_width, model_width_);
    box.resized_height = std::min(box.resized_height, model_height_);
    box.pad_x = (model_width_ - box.resized_width) / 2;
    box.pad_y = (model_height_ - box.resized_height) / 2;

    const std::size_t plane = std::size_t(model_width_) * model_height_;
    std::fill(nchw, nchw + plane * 3, 114.0F / 255.0F);
    for (int dy = 0; dy < box.resized_height; ++dy) {
        const float sy = (float(dy) + 0.5F) / box.scale - 0.5F;
        for (int dx = 0; dx < box.resized_width; ++dx) {
            const float sx = (float(dx) + 0.5F) / box.scale - 0.5F;
            const std::size_t destination = std::size_t(dy + box.pad_y) * model_width_ + dx + box.pad_x;
            for (int channel = 0; channel < 3; ++channel)
                nchw[std::size_t(channel) * plane + destination] =
                    sample_bilinear(source, sx, sy, channel) / 255.0F;
        }
    }
    return box;
}

const std::vector<Detection>& Decoder::run(
    const float* output,
    std::size_t channels,
    std::size_t candidates,
    const Letterbox& letterbox,
    int source_width,
    int source_height,
    float confidence_threshold,
    float iou_threshold,
    std::size_t max_detections)
{
    if (!output || channels < 5 || candidates == 0 || source_width <= 0 || source_height <= 0 ||
        !std::isfinite(letterbox.scale) || letterbox.scale <= 0.0F ||
        !std::isfinite(confidence_threshold) || confidence_threshold < 0.0F || confidence_threshold > 1.0F ||
        !std::isfinite(iou_threshold) || iou_threshold < 0.0F || iou_threshold > 1.0F)
        throw std::invalid_argument("invalid YOLO decoder input");

    candidates_.clear();
    detections_.clear();
    candidates_.reserve(std::min<std::size_t>(candidates, 4096));
    const std::size_t classes = channels - 4;
    for (std::size_t candidate = 0; candidate < candidates; ++candidate) {
        float best_score = -std::numeric_limits<float>::infinity();
        int best_class = -1;
        for (std::size_t class_id = 0; class_id < classes; ++class_id) {
            const float score = output[(4 + class_id) * candidates + candidate];
            if (!std::isfinite(score)) continue;
            if (score > best_score) {
                best_score = score;
                best_class = static_cast<int>(class_id);
            }
        }
        const float center_x = output[candidate];
        const float center_y = output[candidates + candidate];
        const float width = output[2 * candidates + candidate];
        const float height = output[3 * candidates + candidate];
        if (best_class < 0 || best_score < confidence_threshold ||
            !std::isfinite(center_x) || !std::isfinite(center_y) ||
            !std::isfinite(width) || !std::isfinite(height) || width <= 0.0F || height <= 0.0F)
            continue;

        float left = (center_x - width * 0.5F - letterbox.pad_x) / letterbox.scale;
        float top = (center_y - height * 0.5F - letterbox.pad_y) / letterbox.scale;
        float right = (center_x + width * 0.5F - letterbox.pad_x) / letterbox.scale;
        float bottom = (center_y + height * 0.5F - letterbox.pad_y) / letterbox.scale;
        left = std::clamp(left, 0.0F, float(source_width));
        top = std::clamp(top, 0.0F, float(source_height));
        right = std::clamp(right, 0.0F, float(source_width));
        bottom = std::clamp(bottom, 0.0F, float(source_height));
        const int x = static_cast<int>(std::floor(left));
        const int y = static_cast<int>(std::floor(top));
        const int x2 = static_cast<int>(std::ceil(right));
        const int y2 = static_cast<int>(std::ceil(bottom));
        if (x2 > x && y2 > y)
            candidates_.push_back({best_class, best_score, x, y, x2 - x, y2 - y});
    }

    std::sort(candidates_.begin(), candidates_.end(), [](const Detection& a, const Detection& b) {
        return a.confidence > b.confidence;
    });
    detections_.reserve(std::min(max_detections, candidates_.size()));
    for (const auto& candidate : candidates_) {
        const bool suppressed = std::any_of(detections_.begin(), detections_.end(), [&](const Detection& kept) {
            return candidate.class_id == kept.class_id && intersection_over_union(candidate, kept) > iou_threshold;
        });
        if (!suppressed) {
            detections_.push_back(candidate);
            if (detections_.size() >= max_detections) break;
        }
    }
    return detections_;
}

}  // namespace bt::yolo
