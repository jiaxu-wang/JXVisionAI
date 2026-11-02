#pragma once

#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace visionai::inferd {

struct FaceHitLocal {
  float x1 = 0, y1 = 0, x2 = 0, y2 = 0;
  float det_score = 0;
  std::vector<float> kps;  // 5 * (x, y)
  std::vector<float> embedding;
  bool has_attr = false;
  int gender = 0;
  int age = 0;
};

// SCRFD + ArcFace（+ 可选 GenderAge）。模型按路径缓存，多路共用。
class FaceBackend {
 public:
  bool Analyze(const uint8_t* bgr, int width, int height, const std::string& det_path,
               const std::string& embed_path, const std::string& genderage_path, float det_conf,
               int det_size, int max_faces, bool with_embedding, bool with_genderage,
               std::vector<FaceHitLocal>* faces, std::string* err);

 private:
  struct SessionHolder;
  std::shared_ptr<SessionHolder> SessionFor(const std::string& path, std::string* err);

  std::mutex mu_;
  std::vector<std::shared_ptr<SessionHolder>> sessions_;
};

}  // namespace visionai::inferd
