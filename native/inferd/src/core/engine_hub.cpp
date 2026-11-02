#include "core/engine_hub.h"

namespace visionai::inferd {

EngineHub::EngineHub(std::string repo_root, std::string default_device)
    : repo(std::move(repo_root)), default_device(std::move(default_device)) {}

std::shared_ptr<OrtYoloBackend> EngineHub::Find(const std::string& name) {
  std::lock_guard<std::mutex> lock(models_mu_);
  auto it = models_.find(name);
  if (it == models_.end()) return nullptr;
  return it->second;
}

bool EngineHub::LoadExplicit(const ModelMeta& meta, std::string* err) {
  auto backend = std::make_shared<OrtYoloBackend>();
  if (!backend->Load(meta, default_device, err)) return false;
  {
    std::lock_guard<std::mutex> lock(models_mu_);
    models_[meta.name] = std::move(backend);
  }
  repo.MarkLoaded(meta);
  return true;
}

void EngineHub::Unload(const std::string& name) {
  {
    std::lock_guard<std::mutex> lock(models_mu_);
    models_.erase(name);
  }
  repo.MarkUnloaded(name);
}

std::vector<std::string> EngineHub::LoadedNames() const {
  return repo.LoadedNames();
}

}  // namespace visionai::inferd
