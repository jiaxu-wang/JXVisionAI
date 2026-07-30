#pragma once

#include "backend/inference_backend.h"

#include <atomic>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include "onnxruntime_cxx_api.h"

namespace visionai::inferd {

// Parallel ORT: pool of independent Ort::Session (each with its own mutex).
class OrtYoloBackend final : public IInferenceBackend {
 public:
  bool Load(const ModelMeta& meta, const std::string& device, std::string* err) override;
  void Unload() override;
  bool IsLoaded() const override;
  InferRawResult InferBgr(const uint8_t* bgr, int width, int height, float conf, int imgsz,
                          const std::vector<int>* class_filter) override;
  const ModelMeta* meta() const override;

  bool EnsureSessionSlot(const std::string& session_id, std::string* err);
  void DropSessionSlot(const std::string& session_id);
  InferRawResult InferBgrForSession(const std::string& session_id, const uint8_t* bgr, int width,
                                    int height, float conf, int imgsz,
                                    const std::vector<int>* class_filter);

 private:
  struct Slot {
    std::mutex mu;
    std::unique_ptr<Ort::Session> session;
  };

  void ClearUnlocked();
  InferRawResult RunOnSession(Ort::Session* session, const uint8_t* bgr, int width, int height,
                              float conf, int imgsz, const std::vector<int>* class_filter);
  bool CreateSessionLocked(std::unique_ptr<Ort::Session>* out, std::string* err);

  mutable std::mutex mu_;
  std::unique_ptr<Ort::Env> env_;
  std::vector<std::unique_ptr<Slot>> pool_;
  std::map<std::string, std::unique_ptr<Slot>> by_session_;
  ModelMeta meta_{};
  std::string device_;
  std::string model_path_;
  std::vector<std::string> input_names_;
  std::vector<std::string> output_names_;
  std::atomic<uint32_t> rr_{0};
  int pool_size_ = 4;
};

}  // namespace visionai::inferd
