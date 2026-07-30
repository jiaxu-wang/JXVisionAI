#include "core/engine_hub.h"

namespace visionai::inferd {

EngineHub::EngineHub(std::string repo_root, std::string default_device)
    : repo(std::move(repo_root)), default_device(std::move(default_device)) {}

bool EngineHub::LoadPrimary(const std::string& name, const std::string& version, std::string* err) {
  auto meta = repo.Resolve(name, version);
  if (!meta) {
    if (err) *err = "model not found in repository: " + name + "/" + version;
    return false;
  }
  std::string local_err;
  if (!primary.Load(*meta, default_device, &local_err)) {
    if (err) *err = local_err;
    return false;
  }
  repo.MarkLoaded(*meta);
  return true;
}

}  // namespace visionai::inferd
