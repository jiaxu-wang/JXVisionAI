#pragma once

#include "core/model_repository.h"

#include <cstdint>
#include <string>
#include <vector>

namespace visionai::inferd {

struct DetectionBox {
  float x1 = 0, y1 = 0, x2 = 0, y2 = 0;
  int class_id = -1;
  float conf = 0;
};

struct InferRawResult {
  bool ok = false;
  std::string error;
  std::vector<DetectionBox> boxes;
  int64_t infer_ms = 0;
};

class IInferenceBackend {
 public:
  virtual ~IInferenceBackend() = default;
  virtual bool Load(const ModelMeta& meta, const std::string& device, std::string* err) = 0;
  virtual void Unload() = 0;
  virtual bool IsLoaded() const = 0;
  virtual InferRawResult InferBgr(const uint8_t* bgr, int width, int height, float conf,
                                   int imgsz, const std::vector<int>* class_filter) = 0;
  virtual const ModelMeta* meta() const = 0;
};

}  // namespace visionai::inferd
