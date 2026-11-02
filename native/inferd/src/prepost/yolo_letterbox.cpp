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
  const int pad_x = static_cast<int>(std::round(lb.pad_x - 0.1f));
  const int pad_y = static_cast<int>(std::round(lb.pad_y - 0.1f));
  auto sample = [&](int sx, int sy, int ch) -> float {
    sx = std::max(0, std::min(width - 1, sx));
    sy = std::max(0, std::min(height - 1, sy));
    const uint8_t* p = bgr + (static_cast<size_t>(sy) * width + sx) * 3;
    // ch: 0=R 1=G 2=B，源图是 BGR
    const int src_ch = ch == 0 ? 2 : (ch == 2 ? 0 : 1);
    return p[src_ch] / 255.f;
  };
  for (int y = 0; y < new_h; ++y) {
    const float sy = (static_cast<float>(y) + 0.5f) / r - 0.5f;
    const int y0 = static_cast<int>(std::floor(sy));
    const float fy = sy - static_cast<float>(y0);
    const int dy = y + pad_y;
    if (dy < 0 || dy >= imgsz) continue;
    for (int x = 0; x < new_w; ++x) {
      const float sx = (static_cast<float>(x) + 0.5f) / r - 0.5f;
      const int x0 = static_cast<int>(std::floor(sx));
      const float fx = sx - static_cast<float>(x0);
      const int dx = x + pad_x;
      if (dx < 0 || dx >= imgsz) continue;
      const size_t base = static_cast<size_t>(dy) * imgsz + dx;
      for (int ch = 0; ch < 3; ++ch) {
        const float v00 = sample(x0, y0, ch);
        const float v01 = sample(x0 + 1, y0, ch);
        const float v10 = sample(x0, y0 + 1, ch);
        const float v11 = sample(x0 + 1, y0 + 1, ch);
        const float v = v00 * (1 - fx) * (1 - fy) + v01 * fx * (1 - fy) + v10 * (1 - fx) * fy +
                        v11 * fx * fy;
        nchw[static_cast<size_t>(ch) * imgsz * imgsz + base] = v;
      }
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

void MapPointToOriginal(float* x, float* y, const LetterboxInfo& info) {
  auto map1 = [&](float v, float pad, int src_max) {
    float o = (v - pad) / info.gain;
    return std::max(0.f, std::min(static_cast<float>(src_max - 1), o));
  };
  *x = map1(*x, info.pad_x, info.src_w);
  *y = map1(*y, info.pad_y, info.src_h);
}

}  // namespace visionai::inferd
