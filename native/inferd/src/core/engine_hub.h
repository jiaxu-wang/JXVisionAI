#pragma once

#include "backend/ort_yolo_backend.h"
#include "core/model_repository.h"
#include "core/session_manager.h"

#include <memory>
#include <string>

namespace visionai::inferd {

// Process-wide inference state shared by gRPC service.
struct EngineHub {
  explicit EngineHub(std::string repo_root, std::string default_device);

  ModelRepository repo;
  SessionManager sessions;
  OrtYoloBackend primary;  // Phase1: single primary slot
  std::string default_device;

  bool LoadPrimary(const std::string& name, const std::string& version, std::string* err);
};

}  // namespace visionai::inferd
