#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace bt::yolo {

struct FrameView {
    const std::uint8_t* data = nullptr;
    int width = 0;
    int height = 0;
    std::ptrdiff_t stride = 0;
};

struct Letterbox {
    float scale = 1.0F;
    int pad_x = 0;
    int pad_y = 0;
    int resized_width = 0;
    int resized_height = 0;
};

struct Detection {
    int class_id = 0;
    float confidence = 0.0F;
    int x = 0;
    int y = 0;
    int width = 0;
    int height = 0;
};

class Preprocessor {
public:
    Preprocessor(int model_width, int model_height);
    std::size_t tensor_size() const;
    Letterbox run(const FrameView& source, float* nchw) const;

private:
    int model_width_;
    int model_height_;
};

class Decoder {
public:
    const std::vector<Detection>& run(
        const float* output,
        std::size_t channels,
        std::size_t candidates,
        const Letterbox& letterbox,
        int source_width,
        int source_height,
        float confidence_threshold,
        float iou_threshold,
        std::size_t max_detections);

private:
    std::vector<Detection> candidates_;
    std::vector<Detection> detections_;
};

}  // namespace bt::yolo
