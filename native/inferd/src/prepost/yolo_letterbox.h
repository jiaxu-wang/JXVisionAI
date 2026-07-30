#pragma once

#include <cstdint>
#include <vector>

namespace visionai::inferd {

struct LetterboxInfo {
  int src_w = 0;
  int src_h = 0;
  int dst = 640;
  float gain = 1.f;
  float pad_x = 0.f;
  float pad_y = 0.f;
};

// BGR HWC uint8 -> NCHW float32 RGB normalized 0..1 with letterbox (Ultralytics-style).
std::vector<float> LetterboxBgrToNchw(const uint8_t* bgr, int width, int height, int imgsz,
                                      LetterboxInfo* info);

// Map box from letterbox/network space back to original image pixels.
void MapBoxToOriginal(float* x1, float* y1, float* x2, float* y2, const LetterboxInfo& info);

}  // namespace visionai::inferd
