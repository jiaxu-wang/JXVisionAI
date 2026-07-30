#include "backend/ort_yolo_backend.h"

#include "prepost/yolo_letterbox.h"

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <unordered_set>

namespace visionai::inferd {

namespace {
int ResolvePoolSize() {
  const char* e = std::getenv("VISIONAI_INFERD_POOL");
  if (!e || !*e) return 4;
  int n = std::atoi(e);
  if (n < 1) n = 1;
  if (n > 32) n = 32;
  return n;
}
}  // namespace

bool OrtYoloBackend::CreateSessionLocked(std::unique_ptr<Ort::Session>* out, std::string* err) {
  try {
    Ort::SessionOptions opts;
    opts.SetIntraOpNumThreads(1);
    opts.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
    *out = std::make_unique<Ort::Session>(*env_, model_path_.c_str(), opts);
    return true;
  } catch (const std::exception& e) {
    if (err) *err = e.what();
    return false;
  }
}

bool OrtYoloBackend::Load(const ModelMeta& meta, const std::string& device, std::string* err) {
  std::lock_guard<std::mutex> lock(mu_);
  try {
    ClearUnlocked();
    env_ = std::make_unique<Ort::Env>(ORT_LOGGING_LEVEL_WARNING, "visionai-inferd");
    device_ = device.empty() ? "cpu" : device;
    model_path_ = meta.path;
    meta_ = meta;
    meta_.device = device_;
    pool_size_ = ResolvePoolSize();

    std::unique_ptr<Ort::Session> probe;
    if (!CreateSessionLocked(&probe, err)) {
      ClearUnlocked();
      return false;
    }
    Ort::AllocatorWithDefaultOptions alloc;
    input_names_.clear();
    output_names_.clear();
    for (size_t i = 0; i < probe->GetInputCount(); ++i) {
      auto name = probe->GetInputNameAllocated(i, alloc);
      input_names_.emplace_back(name.get());
    }
    for (size_t i = 0; i < probe->GetOutputCount(); ++i) {
      auto name = probe->GetOutputNameAllocated(i, alloc);
      output_names_.emplace_back(name.get());
    }

    pool_.clear();
    pool_.reserve(static_cast<size_t>(pool_size_));
    {
      auto slot = std::make_unique<Slot>();
      slot->session = std::move(probe);
      pool_.push_back(std::move(slot));
    }
    for (int i = 1; i < pool_size_; ++i) {
      auto slot = std::make_unique<Slot>();
      if (!CreateSessionLocked(&slot->session, err)) {
        ClearUnlocked();
        return false;
      }
      pool_.push_back(std::move(slot));
    }
    return true;
  } catch (const std::exception& e) {
    ClearUnlocked();
    if (err) *err = e.what();
    return false;
  }
}

void OrtYoloBackend::ClearUnlocked() {
  by_session_.clear();
  pool_.clear();
  env_.reset();
  input_names_.clear();
  output_names_.clear();
  model_path_.clear();
}

void OrtYoloBackend::Unload() {
  std::lock_guard<std::mutex> lock(mu_);
  ClearUnlocked();
}

bool OrtYoloBackend::IsLoaded() const {
  std::lock_guard<std::mutex> lock(mu_);
  return !pool_.empty() && static_cast<bool>(pool_[0]->session);
}

const ModelMeta* OrtYoloBackend::meta() const {
  std::lock_guard<std::mutex> lock(mu_);
  return pool_.empty() ? nullptr : &meta_;
}

bool OrtYoloBackend::EnsureSessionSlot(const std::string& session_id, std::string* err) {
  if (session_id.empty()) return false;
  std::lock_guard<std::mutex> lock(mu_);
  if (pool_.empty() || !env_) {
    if (err) *err = "model not loaded";
    return false;
  }
  if (by_session_.count(session_id)) return true;
  auto slot = std::make_unique<Slot>();
  if (!CreateSessionLocked(&slot->session, err)) return false;
  by_session_[session_id] = std::move(slot);
  return true;
}

void OrtYoloBackend::DropSessionSlot(const std::string& session_id) {
  std::lock_guard<std::mutex> lock(mu_);
  by_session_.erase(session_id);
}

InferRawResult OrtYoloBackend::RunOnSession(Ort::Session* session, const uint8_t* bgr, int width,
                                            int height, float conf, int imgsz,
                                            const std::vector<int>* class_filter) {
  InferRawResult out;
  if (!session) {
    out.error = "model not loaded";
    return out;
  }
  if (!bgr || width <= 0 || height <= 0) {
    out.error = "invalid image";
    return out;
  }
  if (imgsz <= 0) imgsz = meta_.imgsz > 0 ? meta_.imgsz : 640;

  try {
    LetterboxInfo lb;
    auto nchw = LetterboxBgrToNchw(bgr, width, height, imgsz, &lb);
    std::array<int64_t, 4> shape{1, 3, imgsz, imgsz};
    Ort::MemoryInfo mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    Ort::Value input = Ort::Value::CreateTensor<float>(mem, nchw.data(), nchw.size(), shape.data(),
                                                       shape.size());

    const char* in_names[] = {input_names_[0].c_str()};
    const char* out_names[] = {output_names_[0].c_str()};

    const auto t0 = std::chrono::steady_clock::now();
    auto outputs = session->Run(Ort::RunOptions{nullptr}, in_names, &input, 1, out_names, 1);
    const auto t1 = std::chrono::steady_clock::now();
    out.infer_ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();

    float* data = outputs[0].GetTensorMutableData<float>();
    auto info = outputs[0].GetTensorTypeAndShapeInfo();
    auto dims = info.GetShape();
    if (dims.size() != 3 || dims[2] < 6) {
      out.error = "unexpected output shape";
      return out;
    }
    const int64_t n = dims[1];
    std::unordered_set<int> allow;
    if (class_filter) {
      for (int c : *class_filter) allow.insert(c);
    }

    for (int64_t i = 0; i < n; ++i) {
      const float* row = data + i * dims[2];
      const float score = row[4];
      if (score < conf) continue;
      const int cls = static_cast<int>(row[5]);
      if (class_filter && !allow.empty() && !allow.count(cls)) continue;
      DetectionBox box;
      box.x1 = row[0];
      box.y1 = row[1];
      box.x2 = row[2];
      box.y2 = row[3];
      box.conf = score;
      box.class_id = cls;
      MapBoxToOriginal(&box.x1, &box.y1, &box.x2, &box.y2, lb);
      out.boxes.push_back(box);
    }
    out.ok = true;
    return out;
  } catch (const std::exception& e) {
    out.error = e.what();
    return out;
  }
}

InferRawResult OrtYoloBackend::InferBgr(const uint8_t* bgr, int width, int height, float conf,
                                        int imgsz, const std::vector<int>* class_filter) {
  Slot* slot = nullptr;
  {
    std::lock_guard<std::mutex> lock(mu_);
    if (pool_.empty()) {
      InferRawResult out;
      out.error = "model not loaded";
      return out;
    }
    const uint32_t i = rr_.fetch_add(1) % static_cast<uint32_t>(pool_.size());
    slot = pool_[i].get();
  }
  std::lock_guard<std::mutex> slot_lock(slot->mu);
  return RunOnSession(slot->session.get(), bgr, width, height, conf, imgsz, class_filter);
}

InferRawResult OrtYoloBackend::InferBgrForSession(const std::string& session_id, const uint8_t* bgr,
                                                  int width, int height, float conf, int imgsz,
                                                  const std::vector<int>* class_filter) {
  Slot* slot = nullptr;
  {
    std::lock_guard<std::mutex> lock(mu_);
    auto it = by_session_.find(session_id);
    if (it != by_session_.end()) {
      slot = it->second.get();
    }
  }
  if (!slot) {
    // fallback to pool
    return InferBgr(bgr, width, height, conf, imgsz, class_filter);
  }
  std::lock_guard<std::mutex> slot_lock(slot->mu);
  return RunOnSession(slot->session.get(), bgr, width, height, conf, imgsz, class_filter);
}

}  // namespace visionai::inferd
