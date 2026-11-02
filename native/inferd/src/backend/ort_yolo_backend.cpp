#include "backend/ort_yolo_backend.h"

#include "prepost/yolo_letterbox.h"

#include <algorithm>
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
    if (dims.size() != 3) {
      out.error = "unexpected output rank";
      return out;
    }
    const bool channel_first = dims[1] < dims[2] && dims[1] <= 512;
    const int64_t rows = channel_first ? dims[2] : dims[1];
    const int64_t cols = channel_first ? dims[1] : dims[2];
    if (cols < 6 && !(meta_.task == "pose" && cols >= 5)) {
      out.error = "unexpected output shape";
      return out;
    }
    auto at = [&](int64_t r, int64_t c) -> float {
      if (channel_first) return data[c * rows + r];
      return data[r * cols + c];
    };
    std::unordered_set<int> allow;
    if (class_filter) {
      for (int c : *class_filter) allow.insert(c);
    }
    std::vector<std::string> labels;
    if (!meta_.labels.empty()) {
      std::string cur;
      auto push = [&]() {
        const auto a = cur.find_first_not_of(' ');
        const auto b = cur.find_last_not_of(' ');
        labels.push_back(a == std::string::npos ? std::string() : cur.substr(a, b - a + 1));
        cur.clear();
      };
      for (char ch : meta_.labels) {
        if (ch == ',') {
          push();
        } else {
          cur.push_back(ch);
        }
      }
      push();
    }
    auto put_label = [&](DetectionBox* box) {
      if (box->class_id >= 0 && box->class_id < static_cast<int>(labels.size())) {
        box->label = labels[static_cast<size_t>(box->class_id)];
      }
    };

    // 已做完 NMS 的导出：[1, N, 6] = xyxy, score, class，坐标在 letterbox 像素空间。
    const bool end2end = !channel_first && cols >= 6 && cols <= 7;
    if (end2end) {
      for (int64_t i = 0; i < rows; ++i) {
        const float score = at(i, 4);
        if (score < conf) continue;
        const int cls = static_cast<int>(at(i, 5));
        if (class_filter && !allow.empty() && !allow.count(cls)) continue;
        DetectionBox box;
        box.x1 = at(i, 0);
        box.y1 = at(i, 1);
        box.x2 = at(i, 2);
        box.y2 = at(i, 3);
        box.conf = score;
        box.class_id = cls;
        MapBoxToOriginal(&box.x1, &box.y1, &box.x2, &box.y2, lb);
        put_label(&box);
        out.boxes.push_back(std::move(box));
      }
      out.ok = true;
      return out;
    }

    int nc = meta_.num_classes > 0 ? meta_.num_classes : 80;
    if (meta_.task == "pose" && meta_.num_classes <= 0) nc = 1;
    if (cols < 4 + nc) nc = static_cast<int>(cols - 4);
    const int kpt_ch = static_cast<int>(cols) - 4 - nc;
    struct Cand {
      DetectionBox box;
      float area = 0;
    };
    std::vector<Cand> cands;
    cands.reserve(256);
    for (int64_t i = 0; i < rows; ++i) {
      float best = 0.f;
      int cls = 0;
      for (int c = 0; c < nc; ++c) {
        const float s = at(i, 4 + c);
        if (s > best) {
          best = s;
          cls = c;
        }
      }
      if (best < conf) continue;
      if (class_filter && !allow.empty() && !allow.count(cls)) continue;
      const float cx = at(i, 0);
      const float cy = at(i, 1);
      const float w = at(i, 2);
      const float h = at(i, 3);
      DetectionBox box;
      box.x1 = cx - w * 0.5f;
      box.y1 = cy - h * 0.5f;
      box.x2 = cx + w * 0.5f;
      box.y2 = cy + h * 0.5f;
      box.conf = best;
      box.class_id = cls;
      if (kpt_ch >= 3 && kpt_ch % 3 == 0) {
        box.keypoints.resize(static_cast<size_t>(kpt_ch));
        for (int k = 0; k < kpt_ch; ++k) box.keypoints[static_cast<size_t>(k)] = at(i, 4 + nc + k);
      }
      Cand cand;
      cand.area = std::max(0.f, box.x2 - box.x1) * std::max(0.f, box.y2 - box.y1);
      cand.box = std::move(box);
      cands.push_back(std::move(cand));
    }
    std::sort(cands.begin(), cands.end(),
              [](const Cand& a, const Cand& b) { return a.box.conf > b.box.conf; });
    std::vector<char> drop(cands.size(), 0);
    constexpr float kIou = 0.45f;
    for (size_t i = 0; i < cands.size(); ++i) {
      if (drop[i]) continue;
      const auto& a = cands[i].box;
      for (size_t j = i + 1; j < cands.size(); ++j) {
        if (drop[j] || cands[j].box.class_id != a.class_id) continue;
        const auto& b = cands[j].box;
        const float ix1 = std::max(a.x1, b.x1);
        const float iy1 = std::max(a.y1, b.y1);
        const float ix2 = std::min(a.x2, b.x2);
        const float iy2 = std::min(a.y2, b.y2);
        const float iw = std::max(0.f, ix2 - ix1);
        const float ih = std::max(0.f, iy2 - iy1);
        const float inter = iw * ih;
        const float uni = cands[i].area + cands[j].area - inter;
        if (uni > 0.f && inter / uni > kIou) drop[j] = 1;
      }
    }
    for (size_t i = 0; i < cands.size() && out.boxes.size() < 300; ++i) {
      if (drop[i]) continue;
      DetectionBox box = std::move(cands[i].box);
      for (size_t k = 0; k + 2 < box.keypoints.size(); k += 3) {
        MapPointToOriginal(&box.keypoints[k], &box.keypoints[k + 1], lb);
      }
      MapBoxToOriginal(&box.x1, &box.y1, &box.x2, &box.y2, lb);
      put_label(&box);
      out.boxes.push_back(std::move(box));
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
