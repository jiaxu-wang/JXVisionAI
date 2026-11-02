#pragma once

#include "backend/ort_yolo_backend.h"
#include "core/model_repository.h"
#include "core/session_manager.h"

#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace visionai::inferd {

// 进程内共用的推理状态。每个模型名一份 ORT 会话池，多路流共用。
struct EngineHub {
  explicit EngineHub(std::string repo_root, std::string default_device);

  ModelRepository repo;
  SessionManager sessions;
  std::string default_device;

  std::shared_ptr<OrtYoloBackend> Find(const std::string& name);
  bool LoadExplicit(const ModelMeta& meta, std::string* err);
  void Unload(const std::string& name);
  std::vector<std::string> LoadedNames() const;

 private:
  std::mutex models_mu_;
  std::map<std::string, std::shared_ptr<OrtYoloBackend>> models_;
};

}  // namespace visionai::inferd
