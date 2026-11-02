#include "backend/face_backend.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>

#include "onnxruntime_cxx_api.h"

namespace visionai::inferd {

struct OrtPack {
  Ort::Env env{ORT_LOGGING_LEVEL_WARNING, "visionai-face"};
  std::unique_ptr<Ort::Session> session;
  std::string input_name;
  std::vector<std::string> output_names;
  std::mutex mu;
};

namespace {

constexpr int kStrides[3] = {8, 16, 32};
constexpr float kArcDst[5][2] = {
    {38.2946f, 51.6963f}, {73.5318f, 51.5014f}, {56.0252f, 71.7366f},
    {41.5493f, 92.3655f}, {70.7299f, 92.2041f},
};

float SampleBilinear(const std::vector<float>& img, int w, int h, float x, float y, int ch) {
  x = std::max(0.f, std::min(static_cast<float>(w - 1), x));
  y = std::max(0.f, std::min(static_cast<float>(h - 1), y));
  const int x0 = static_cast<int>(std::floor(x));
  const int y0 = static_cast<int>(std::floor(y));
  const int x1 = std::min(w - 1, x0 + 1);
  const int y1 = std::min(h - 1, y0 + 1);
  const float fx = x - static_cast<float>(x0);
  const float fy = y - static_cast<float>(y0);
  auto at = [&](int xx, int yy) { return img[(static_cast<size_t>(yy) * w + xx) * 3 + ch]; };
  return at(x0, y0) * (1 - fx) * (1 - fy) + at(x1, y0) * fx * (1 - fy) +
         at(x0, y1) * (1 - fx) * fy + at(x1, y1) * fx * fy;
}

void WarpBgr(const uint8_t* src, int sw, int sh, const float M[2][3], int dw, int dh,
             std::vector<uint8_t>* dst) {
  dst->assign(static_cast<size_t>(dw * dh * 3), 0);
  const float a = M[0][0];
  const float b = M[0][1];
  const float tx = M[0][2];
  const float c = M[1][0];
  const float d = M[1][1];
  const float ty = M[1][2];
  const float det = a * d - b * c;
  if (std::fabs(det) < 1e-8f) return;
  const float ia = d / det;
  const float ib = -b / det;
  const float ic = -c / det;
  const float id = a / det;
  for (int y = 0; y < dh; ++y) {
    for (int x = 0; x < dw; ++x) {
      const float x2 = static_cast<float>(x) - tx;
      const float y2 = static_cast<float>(y) - ty;
      const float sx = ia * x2 + ib * y2;
      const float sy = ic * x2 + id * y2;
      if (sx < -1 || sy < -1 || sx > sw || sy > sh) continue;
      const int x0 = std::max(0, std::min(sw - 1, static_cast<int>(std::floor(sx))));
      const int y0 = std::max(0, std::min(sh - 1, static_cast<int>(std::floor(sy))));
      const int x1 = std::min(sw - 1, x0 + 1);
      const int y1 = std::min(sh - 1, y0 + 1);
      const float fx = sx - static_cast<float>(x0);
      const float fy = sy - static_cast<float>(y0);
      uint8_t* o = dst->data() + (static_cast<size_t>(y) * dw + x) * 3;
      for (int ch = 0; ch < 3; ++ch) {
        auto at = [&](int xx, int yy) {
          return src[(static_cast<size_t>(yy) * sw + xx) * 3 + ch];
        };
        const float v = at(x0, y0) * (1 - fx) * (1 - fy) + at(x1, y0) * fx * (1 - fy) +
                        at(x0, y1) * (1 - fx) * fy + at(x1, y1) * fx * fy;
        o[ch] = static_cast<uint8_t>(std::max(0.f, std::min(255.f, v)));
      }
    }
  }
}

bool SolveSimilarity(const float src[5][2], float M[2][3]) {
  // x' = a*x - b*y + tx, y' = b*x + a*y + ty
  double ata[4][4] = {};
  double atb[4] = {};
  for (int i = 0; i < 5; ++i) {
    const double x = src[i][0];
    const double y = src[i][1];
    const double xp = kArcDst[i][0];
    const double yp = kArcDst[i][1];
    const double row1[4] = {x, -y, 1, 0};
    const double row2[4] = {y, x, 0, 1};
    for (int r = 0; r < 4; ++r) {
      atb[r] += row1[r] * xp + row2[r] * yp;
      for (int c = 0; c < 4; ++c) ata[r][c] += row1[r] * row1[c] + row2[r] * row2[c];
    }
  }
  for (int col = 0; col < 4; ++col) {
    int piv = col;
    for (int r = col + 1; r < 4; ++r)
      if (std::fabs(ata[r][col]) > std::fabs(ata[piv][col])) piv = r;
    if (std::fabs(ata[piv][col]) < 1e-8) return false;
    if (piv != col) {
      for (int c = 0; c < 4; ++c) std::swap(ata[col][c], ata[piv][c]);
      std::swap(atb[col], atb[piv]);
    }
    const double div = ata[col][col];
    for (int c = col; c < 4; ++c) ata[col][c] /= div;
    atb[col] /= div;
    for (int r = 0; r < 4; ++r) {
      if (r == col) continue;
      const double f = ata[r][col];
      for (int c = col; c < 4; ++c) ata[r][c] -= f * ata[col][c];
      atb[r] -= f * atb[col];
    }
  }
  const double a = atb[0];
  const double b = atb[1];
  M[0][0] = static_cast<float>(a);
  M[0][1] = static_cast<float>(-b);
  M[0][2] = static_cast<float>(atb[2]);
  M[1][0] = static_cast<float>(b);
  M[1][1] = static_cast<float>(a);
  M[1][2] = static_cast<float>(atb[3]);
  return true;
}

std::vector<float> ResizeBgr(const uint8_t* src, int sw, int sh, int x1, int y1, int x2, int y2,
                             int dw, int dh) {
  std::vector<float> out(static_cast<size_t>(dw * dh * 3), 0.f);
  const int rw = std::max(1, x2 - x1);
  const int rh = std::max(1, y2 - y1);
  for (int y = 0; y < dh; ++y) {
    const float sy = y1 + (static_cast<float>(y) + 0.5f) * rh / dh - 0.5f;
    for (int x = 0; x < dw; ++x) {
      const float sx = x1 + (static_cast<float>(x) + 0.5f) * rw / dw - 0.5f;
      const int ix = std::max(0, std::min(sw - 1, static_cast<int>(std::round(sx))));
      const int iy = std::max(0, std::min(sh - 1, static_cast<int>(std::round(sy))));
      const uint8_t* p = src + (static_cast<size_t>(iy) * sw + ix) * 3;
      float* o = out.data() + (static_cast<size_t>(y) * dw + x) * 3;
      o[0] = p[0];
      o[1] = p[1];
      o[2] = p[2];
    }
  }
  return out;
}

}  // namespace

struct FaceBackend::SessionHolder : OrtPack {
  std::string path;
};

std::shared_ptr<FaceBackend::SessionHolder> FaceBackend::SessionFor(const std::string& path,
                                                                        std::string* err) {
  for (auto& s : sessions_) {
    if (s->path == path) return s;
  }
  try {
    auto holder = std::make_shared<SessionHolder>();
    holder->path = path;
    Ort::SessionOptions opts;
    opts.SetIntraOpNumThreads(1);
    opts.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
    holder->session = std::make_unique<Ort::Session>(holder->env, path.c_str(), opts);
    Ort::AllocatorWithDefaultOptions alloc;
    auto in = holder->session->GetInputNameAllocated(0, alloc);
    holder->input_name = in.get();
    for (size_t i = 0; i < holder->session->GetOutputCount(); ++i) {
      auto name = holder->session->GetOutputNameAllocated(i, alloc);
      holder->output_names.emplace_back(name.get());
    }
    sessions_.push_back(holder);
    return holder;
  } catch (const std::exception& e) {
    if (err) *err = e.what();
    return nullptr;
  }
}

bool FaceBackend::Analyze(const uint8_t* bgr, int width, int height, const std::string& det_path,
                          const std::string& embed_path, const std::string& genderage_path,
                          float det_conf, int det_size, int max_faces, bool with_embedding,
                          bool with_genderage, std::vector<FaceHitLocal>* faces, std::string* err) {
  if (!faces) return false;
  faces->clear();
  if (!bgr || width <= 0 || height <= 0 || det_path.empty()) {
    if (err) *err = "invalid face request";
    return false;
  }
  if (det_size <= 0) det_size = 640;
  if (max_faces <= 0) max_faces = 5;
  if (det_conf <= 0) det_conf = 0.5f;

  std::lock_guard<std::mutex> lock(mu_);
  auto det = SessionFor(det_path, err);
  if (!det) return false;

  const float scale = std::min(static_cast<float>(det_size) / height, static_cast<float>(det_size) / width);
  const int nw = std::max(1, static_cast<int>(width * scale));
  const int nh = std::max(1, static_cast<int>(height * scale));
  std::vector<float> blob(static_cast<size_t>(3 * det_size * det_size), 0.f);
  for (int y = 0; y < nh; ++y) {
    const int sy = std::min(height - 1, static_cast<int>(y / scale));
    for (int x = 0; x < nw; ++x) {
      const int sx = std::min(width - 1, static_cast<int>(x / scale));
      const uint8_t* p = bgr + (static_cast<size_t>(sy) * width + sx) * 3;
      const size_t base = static_cast<size_t>(y) * det_size + x;
      for (int ch = 0; ch < 3; ++ch) {
        blob[static_cast<size_t>(ch) * det_size * det_size + base] =
            (static_cast<float>(p[ch]) - 127.5f) / 128.f;
      }
    }
  }

  std::array<int64_t, 4> shape{1, 3, det_size, det_size};
  Ort::MemoryInfo mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
  Ort::Value input = Ort::Value::CreateTensor<float>(mem, blob.data(), blob.size(), shape.data(), 4);
  std::vector<const char*> out_names;
  out_names.reserve(det->output_names.size());
  for (const auto& n : det->output_names) out_names.push_back(n.c_str());
  const char* in_name = det->input_name.c_str();
  std::vector<Ort::Value> outputs;
  {
    std::lock_guard<std::mutex> sl(det->mu);
    outputs = det->session->Run(Ort::RunOptions{nullptr}, &in_name, &input, 1, out_names.data(),
                                out_names.size());
  }
  if (outputs.size() < 9) {
    if (err) *err = "scrfd outputs < 9";
    return false;
  }

  struct Raw {
    float x1, y1, x2, y2, score;
    float kps[10];
  };
  std::vector<Raw> raws;
  for (int si = 0; si < 3; ++si) {
    const int stride = kStrides[si];
    const int gw = det_size / stride;
    const int gh = det_size / stride;
    float* scores = outputs[si].GetTensorMutableData<float>();
    float* bboxes = outputs[3 + si].GetTensorMutableData<float>();
    float* kpso = outputs[6 + si].GetTensorMutableData<float>();
    const int ngrid = gw * gh;
    const int nscore = static_cast<int>(outputs[si].GetTensorTypeAndShapeInfo().GetElementCount());
    const int nbbox = static_cast<int>(outputs[3 + si].GetTensorTypeAndShapeInfo().GetElementCount() / 4);
    const int nkps = static_cast<int>(outputs[6 + si].GetTensorTypeAndShapeInfo().GetElementCount() / 10);
    const int n = std::min(ngrid * 2, std::min(nscore, std::min(nbbox, nkps)));
    for (int j = 0; j < n; ++j) {
      const float sc = scores[j];
      if (sc < det_conf) continue;
      const int cell = j / 2;
      const int gx = cell % gw;
      const int gy = cell / gw;
      const float cx = (gx + 0.5f) * stride;
      const float cy = (gy + 0.5f) * stride;
      const float* bd = bboxes + static_cast<size_t>(j) * 4;
      const float* kd = kpso + static_cast<size_t>(j) * 10;
      Raw r;
      r.x1 = (cx - bd[0] * stride) / scale;
      r.y1 = (cy - bd[1] * stride) / scale;
      r.x2 = (cx + bd[2] * stride) / scale;
      r.y2 = (cy + bd[3] * stride) / scale;
      r.x1 = std::max(0.f, std::min(static_cast<float>(width - 1), r.x1));
      r.y1 = std::max(0.f, std::min(static_cast<float>(height - 1), r.y1));
      r.x2 = std::max(0.f, std::min(static_cast<float>(width - 1), r.x2));
      r.y2 = std::max(0.f, std::min(static_cast<float>(height - 1), r.y2));
      if (r.x2 <= r.x1 || r.y2 <= r.y1) continue;
      r.score = sc;
      for (int k = 0; k < 5; ++k) {
        r.kps[k * 2] = std::max(0.f, std::min(static_cast<float>(width - 1), (cx + kd[k * 2] * stride) / scale));
        r.kps[k * 2 + 1] =
            std::max(0.f, std::min(static_cast<float>(height - 1), (cy + kd[k * 2 + 1] * stride) / scale));
      }
      raws.push_back(r);
    }
  }
  std::sort(raws.begin(), raws.end(), [](const Raw& a, const Raw& b) { return a.score > b.score; });
  std::vector<char> drop(raws.size(), 0);
  for (size_t i = 0; i < raws.size(); ++i) {
    if (drop[i]) continue;
    for (size_t j = i + 1; j < raws.size(); ++j) {
      if (drop[j]) continue;
      const float ix1 = std::max(raws[i].x1, raws[j].x1);
      const float iy1 = std::max(raws[i].y1, raws[j].y1);
      const float ix2 = std::min(raws[i].x2, raws[j].x2);
      const float iy2 = std::min(raws[i].y2, raws[j].y2);
      const float inter = std::max(0.f, ix2 - ix1) * std::max(0.f, iy2 - iy1);
      const float a1 = (raws[i].x2 - raws[i].x1) * (raws[i].y2 - raws[i].y1);
      const float a2 = (raws[j].x2 - raws[j].x1) * (raws[j].y2 - raws[j].y1);
      const float uni = a1 + a2 - inter;
      if (uni > 0.f && inter / uni > 0.4f) drop[j] = 1;
    }
  }

  std::shared_ptr<SessionHolder> emb;
  if (with_embedding && !embed_path.empty()) {
    emb = SessionFor(embed_path, err);
    if (!emb) return false;
  }
  std::shared_ptr<SessionHolder> ga;
  if (with_genderage && !genderage_path.empty()) {
    ga = SessionFor(genderage_path, err);
  }

  int kept = 0;
  for (size_t i = 0; i < raws.size() && kept < max_faces; ++i) {
    if (drop[i]) continue;
    ++kept;
    FaceHitLocal hit;
    hit.x1 = raws[i].x1;
    hit.y1 = raws[i].y1;
    hit.x2 = raws[i].x2;
    hit.y2 = raws[i].y2;
    hit.det_score = raws[i].score;
    hit.kps.assign(raws[i].kps, raws[i].kps + 10);

    if (emb) {
      float src[5][2];
      for (int k = 0; k < 5; ++k) {
        src[k][0] = raws[i].kps[k * 2];
        src[k][1] = raws[i].kps[k * 2 + 1];
      }
      float M[2][3];
      std::vector<uint8_t> aligned;
      if (!SolveSimilarity(src, M)) {
        aligned.resize(112 * 112 * 3);
        auto resized = ResizeBgr(bgr, width, height, static_cast<int>(hit.x1), static_cast<int>(hit.y1),
                                 static_cast<int>(hit.x2), static_cast<int>(hit.y2), 112, 112);
        for (size_t p = 0; p < aligned.size(); ++p) aligned[p] = static_cast<uint8_t>(resized[p]);
      } else {
        WarpBgr(bgr, width, height, M, 112, 112, &aligned);
      }
      std::vector<float> eblob(3 * 112 * 112);
      for (int y = 0; y < 112; ++y) {
        for (int x = 0; x < 112; ++x) {
          const uint8_t* p = aligned.data() + (static_cast<size_t>(y) * 112 + x) * 3;
          const size_t base = static_cast<size_t>(y) * 112 + x;
          eblob[base] = (static_cast<float>(p[2]) - 127.5f) / 127.5f;
          eblob[112 * 112 + base] = (static_cast<float>(p[1]) - 127.5f) / 127.5f;
          eblob[2 * 112 * 112 + base] = (static_cast<float>(p[0]) - 127.5f) / 127.5f;
        }
      }
      std::array<int64_t, 4> eshape{1, 3, 112, 112};
      Ort::Value ein = Ort::Value::CreateTensor<float>(mem, eblob.data(), eblob.size(), eshape.data(), 4);
      const char* ein_name = emb->input_name.c_str();
      std::vector<const char*> eouts;
      for (const auto& n : emb->output_names) eouts.push_back(n.c_str());
      std::vector<Ort::Value> eout;
      {
        std::lock_guard<std::mutex> sl(emb->mu);
        eout = emb->session->Run(Ort::RunOptions{nullptr}, &ein_name, &ein, 1, eouts.data(), eouts.size());
      }
      float* vec = eout[0].GetTensorMutableData<float>();
      const size_t nvec = eout[0].GetTensorTypeAndShapeInfo().GetElementCount();
      hit.embedding.assign(vec, vec + nvec);
      double norm = 0;
      for (float v : hit.embedding) norm += static_cast<double>(v) * v;
      norm = std::sqrt(norm);
      if (norm > 1e-8) {
        for (float& v : hit.embedding) v = static_cast<float>(v / norm);
      }
    }

    if (ga) {
      const float bw = hit.x2 - hit.x1;
      const float bh = hit.y2 - hit.y1;
      const float center_x = (hit.x1 + hit.x2) * 0.5f;
      const float center_y = (hit.y1 + hit.y2) * 0.5f;
      const float gscale = 96.f / (std::max(bw, bh) * 1.5f + 1e-6f);
      float GM[2][3] = {{gscale, 0.f, 48.f - center_x * gscale},
                        {0.f, gscale, 48.f - center_y * gscale}};
      std::vector<uint8_t> gimg;
      WarpBgr(bgr, width, height, GM, 96, 96, &gimg);
      std::vector<float> gblob(3 * 96 * 96);
      for (int y = 0; y < 96; ++y) {
        for (int x = 0; x < 96; ++x) {
          const uint8_t* p = gimg.data() + (static_cast<size_t>(y) * 96 + x) * 3;
          const size_t base = static_cast<size_t>(y) * 96 + x;
          gblob[base] = p[2];
          gblob[96 * 96 + base] = p[1];
          gblob[2 * 96 * 96 + base] = p[0];
        }
      }
      std::array<int64_t, 4> gshape{1, 3, 96, 96};
      Ort::Value gin = Ort::Value::CreateTensor<float>(mem, gblob.data(), gblob.size(), gshape.data(), 4);
      const char* gin_name = ga->input_name.c_str();
      std::vector<const char*> gouts;
      for (const auto& n : ga->output_names) gouts.push_back(n.c_str());
      try {
        std::vector<Ort::Value> gout;
        {
          std::lock_guard<std::mutex> sl(ga->mu);
          gout = ga->session->Run(Ort::RunOptions{nullptr}, &gin_name, &gin, 1, gouts.data(), gouts.size());
        }
        float* pred = gout[0].GetTensorMutableData<float>();
        hit.gender = pred[1] > pred[0] ? 1 : 0;
        int age = static_cast<int>(std::lround(pred[2] * 100.f));
        if (age < 0) age = 0;
        if (age > 120) age = 120;
        hit.age = age;
        hit.has_attr = true;
      } catch (const std::exception&) {
        hit.has_attr = false;
      }
    }
    faces->push_back(std::move(hit));
  }
  return true;
}

}  // namespace visionai::inferd
