#include "core/model_repository.h"

#include "core/json_mini.h"

#include <filesystem>
#include <fstream>
#include <sstream>

namespace fs = std::filesystem;

namespace visionai::inferd {
namespace {

std::string ReadAll(const fs::path& p) {
  std::ifstream in(p);
  std::ostringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

}  // namespace

ModelRepository::ModelRepository(std::string root) : root_(std::move(root)) {}

std::vector<ModelMeta> ModelRepository::ListOnDisk() const {
  std::vector<ModelMeta> out;
  const fs::path root(root_);
  if (!fs::is_directory(root)) return out;

  for (const auto& name_ent : fs::directory_iterator(root)) {
    if (!name_ent.is_directory()) continue;
    const std::string name = name_ent.path().filename().string();
    for (const auto& ver_ent : fs::directory_iterator(name_ent.path())) {
      if (!ver_ent.is_directory()) continue;
      const std::string version = ver_ent.path().filename().string();
      auto meta = Resolve(name, version);
      if (meta) out.push_back(*meta);
    }
  }
  return out;
}

std::optional<ModelMeta> ModelRepository::Resolve(const std::string& name,
                                                  const std::string& version) const {
  const fs::path dir = fs::path(root_) / name / version;
  const fs::path onnx = dir / "model.onnx";
  const fs::path json = dir / "model.json";
  if (!fs::is_regular_file(onnx)) return std::nullopt;

  ModelMeta m;
  m.name = name;
  m.version = version;
  m.path = fs::absolute(onnx).string();
  m.format = "onnx";
  m.task = "detect";
  m.imgsz = 640;
  m.num_classes = 80;
  m.backend = "onnxruntime";

  if (fs::is_regular_file(json)) {
    const std::string body = ReadAll(json);
    m.name = JsonGetString(body, "name", m.name);
    m.version = JsonGetString(body, "version", m.version);
    m.format = JsonGetString(body, "format", m.format);
    m.task = JsonGetString(body, "task", m.task);
    m.labels = JsonGetString(body, "labels", m.labels);
    m.backend = JsonGetString(body, "backend", m.backend);
    m.imgsz = JsonGetInt(body, "imgsz", m.imgsz);
    m.num_classes = JsonGetInt(body, "num_classes", m.num_classes);
  }
  return m;
}

void ModelRepository::MarkLoaded(const ModelMeta& meta) {
  std::lock_guard<std::mutex> lock(mu_);
  loaded_[meta.name] = meta;
}

void ModelRepository::MarkUnloaded(const std::string& name) {
  std::lock_guard<std::mutex> lock(mu_);
  loaded_.erase(name);
}

std::vector<std::string> ModelRepository::LoadedNames() const {
  std::lock_guard<std::mutex> lock(mu_);
  std::vector<std::string> names;
  names.reserve(loaded_.size());
  for (const auto& kv : loaded_) names.push_back(kv.first);
  return names;
}

bool ModelRepository::IsLoaded(const std::string& name) const {
  std::lock_guard<std::mutex> lock(mu_);
  return loaded_.count(name) > 0;
}

}  // namespace visionai::inferd
