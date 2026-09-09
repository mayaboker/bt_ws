#include "yolo_core.hpp"

#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

static void require(bool condition, const char* message)
{
    if (!condition) throw std::runtime_error(message);
}

int main() try
{
    using namespace bt::yolo;

    // Two RGB pixels plus five bytes of row padding verifies stride handling.
    const std::vector<std::uint8_t> pixels{255, 0, 0, 0, 255, 0, 9, 9, 9, 9, 9};
    Preprocessor preprocessor(4, 4);
    std::vector<float> tensor(preprocessor.tensor_size());
    const auto box = preprocessor.run({pixels.data(), 2, 1, 11}, tensor.data());
    require(box.scale == 2.0F && box.resized_width == 4 && box.resized_height == 2 &&
            box.pad_x == 0 && box.pad_y == 1, "landscape letterbox geometry is incorrect");
    require(std::abs(tensor[0] - 114.0F / 255.0F) < 1e-6F, "letterbox fill is incorrect");
    const std::size_t plane = 16;
    require(tensor[4] > 0.9F && tensor[plane + 4] < 0.1F, "RGB planar conversion is incorrect");

    // [1, 6, 3]: three candidates and two classes. First two overlap in the
    // same class; third is the same box but another class and must survive NMS.
    constexpr std::size_t candidates = 3;
    std::vector<float> output(6 * candidates);
    output[0] = 2; output[1] = 2.1F; output[2] = 2;
    output[3] = 2; output[4] = 2.1F; output[5] = 2;
    output[6] = 2; output[7] = 2; output[8] = 2;
    output[9] = 2; output[10] = 2; output[11] = 2;
    output[12] = 0.9F; output[13] = 0.8F; output[14] = 0.1F;
    output[15] = 0.1F; output[16] = 0.2F; output[17] = 0.95F;
    Decoder decoder;
    const auto& detections = decoder.run(output.data(), 6, candidates, box, 2, 1, 0.4F, 0.5F, 100);
    require(detections.size() == 2, "per-class NMS result is incorrect");
    require(detections[0].class_id == 1 && detections[1].class_id == 0,
            "detections are not globally confidence ordered");

    output[0] = std::numeric_limits<float>::quiet_NaN();
    const auto& finite = decoder.run(output.data(), 6, candidates, box, 2, 1, 0.4F, 0.5F, 1);
    require(finite.size() == 1 && std::isfinite(finite[0].confidence),
            "non-finite rejection or max-detections is incorrect");

    std::cout << "PASS: RGB preprocessing, stride, letterbox, decode, NMS, and finite checks\n";
    return 0;
} catch (const std::exception& error) {
    std::cerr << "FAIL: " << error.what() << '\n';
    return 1;
}
