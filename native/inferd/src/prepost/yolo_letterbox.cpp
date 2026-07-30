#include "prepost/yolo_letterbox.h"

#include <algorithm>
#include <cmath>

namespace visionai::inferd {

std::vector<float> LetterboxBgrToNchw(const uint8_t* bgr, int width, int height, int imgsz,
                                      LetterboxInfo* info) {
  LetterboxInfo lb;
  lb.src_w = width;
  lb.src_h = height;
  lb.dst = imgsz;
  const float r = std::min(static_cast<float>(imgsz) / height, static_cast<float>(imgsz) / width);
  lb.gain = r;
  const int new_w = static_cast<int>(std::round(width * r));
  const int new_h = static_cast<int>(std::round(height * r));
  lb.pad_x = (imgsz - new_w) * 0.5f;
  lb.pad_y = (imgsz - new_h) * 0.5f;
  if (info) *info = lb;

  std::vector<float> nchw(static_cast<size_t>(3 * imgsz * imgsz), 114.f / 255.f);

  // Nearest-neighbor resize + pad (good enough for gate; bilinear later if needed).
  for (int y = 0; y < new_h; ++y) {
    const int sy = std::min(height - 1, static_cast<int>(y / r));
    for (int x = 0; x < new_w; ++x) {
      const int sx = std::min(width - 1, static_cast<int>(x / r));
      const int dx = static_cast<int>(std::floor(x + lb.pad_x));
      const int dy = static_cast<int>(std::floor(y + lb.pad_y));
      if (dx < 0 || dy < 0 || dx >= imgsz || dy >= imgsz) continue;
      const uint8_t* p = bgr + (static_cast<size_t>(sy) * width + sx) * 3;
      const size_t base = static_cast<size_t>(dy) * imgsz + dx;
      nchw[base] = p[2] / 255.f;                      // R
      nchw[imgsz * imgsz + base] = p[1] / 255.f;      // G
      nchw[2 * imgsz * imgsz + base] = p[0] / 255.f;  // B
    }
  }
  return nchw;
}

void MapBoxToOriginal(float* x1, float* y1, float* x2, float* y2, const LetterboxInfo& info) {
  auto map1 = [&](float v, float pad, int src_max) {
    float o = (v - pad) / info.gain;
    return std::max(0.f, std::min(static_cast<float>(src_max - 1), o));
  };
  *x1 = map1(*x1, info.pad_x, info.src_w);
  *x2 = map1(*x2, info.pad_x, info.src_w);
  *y1 = map1(*y1, info.pad_y, info.src_h);
  *y2 = map1(*y2, info.pad_y, info.src_h);
}

}  // namespace visionai::inferd
