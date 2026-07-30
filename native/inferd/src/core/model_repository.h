#pragma once

#include <map>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace visionai::inferd {

struct ModelMeta {
  std::string name;
  std::string version;
  std::string format;
  std::string task;
  std::string path;  // absolute path to model.onnx
  std::string device;
  int imgsz = 640;
  int num_classes = 80;
  std::string labels;
  std::string backend;
};

class ModelRepository {
 public:
  explicit ModelRepository(std::string root);

  const std::string& root() const { return root_; }

  // Scan repo directories (does not load into ORT).
  std::vector<ModelMeta> ListOnDisk() const;

  std::optional<ModelMeta> Resolve(const std::string& name, const std::string& version) const;

  void MarkLoaded(const ModelMeta& meta);
  void MarkUnloaded(const std::string& name);
  std::vector<std::string> LoadedNames() const;
  bool IsLoaded(const std::string& name) const;

 private:
  std::string root_;
  mutable std::mutex mu_;
  std::map<std::string, ModelMeta> loaded_;
};

}  // namespace visionai::inferd
