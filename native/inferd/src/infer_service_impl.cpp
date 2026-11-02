#include "infer_service_impl.h"

#include "version.h"

#include <chrono>
#include <cstdlib>

namespace visionai::inferd {
namespace {

visionai::infer::v1::Status MakeStatus(visionai::infer::v1::ErrorCode code,
                                       const std::string& message) {
  visionai::infer::v1::Status st;
  st.set_code(code);
  st.set_message(message);
  return st;
}

SessionConfigLocal FromProto(const visionai::infer::v1::SessionConfig& c) {
  SessionConfigLocal s;
  s.session_id = c.session_id();
  s.model_name = c.model_name().empty() ? "primary" : c.model_name();
  s.conf = c.conf() > 0 ? c.conf() : 0.25f;
  s.imgsz = c.imgsz() > 0 ? c.imgsz() : 640;
  for (int v : c.class_filter()) s.class_filter.push_back(v);
  return s;
}

}  // namespace

InferServiceImpl::InferServiceImpl(EngineHub* hub) : hub_(hub) {}

grpc::Status InferServiceImpl::Live(grpc::ServerContext*,
                                    const visionai::infer::v1::LiveRequest*,
                                    visionai::infer::v1::LiveResponse* response) {
  response->set_alive(true);
  response->set_server_version(kServerVersion);
  response->set_api_version(kApiVersion);
  return grpc::Status::OK;
}

grpc::Status InferServiceImpl::Ready(grpc::ServerContext*,
                                     const visionai::infer::v1::ReadyRequest*,
                                     visionai::infer::v1::ReadyResponse* response) {
  response->set_ready(true);
  *response->mutable_status() = MakeStatus(visionai::infer::v1::OK, "ready");
  for (const auto& n : hub_->LoadedNames()) response->add_loaded_models(n);
  return grpc::Status::OK;
}

grpc::Status InferServiceImpl::ListModels(grpc::ServerContext*,
                                          const visionai::infer::v1::ListModelsRequest*,
                                          visionai::infer::v1::ListModelsResponse* response) {
  *response->mutable_status() = MakeStatus(visionai::infer::v1::OK, "ok");
  for (const auto& m : hub_->repo.ListOnDisk()) {
    auto* spec = response->add_models();
    spec->set_name(m.name);
    spec->set_version(m.version);
    spec->set_format(m.format);
    spec->set_device(m.device);
    spec->set_path(m.path);
    (*spec->mutable_meta())["imgsz"] = std::to_string(m.imgsz);
    (*spec->mutable_meta())["task"] = m.task;
  }
  return grpc::Status::OK;
}

grpc::Status InferServiceImpl::LoadModel(grpc::ServerContext*,
                                         const visionai::infer::v1::LoadModelRequest* request,
                                         visionai::infer::v1::LoadModelResponse* response) {
  const auto& m = request->model();
  const std::string name = m.name().empty() ? "primary" : m.name();
  const std::string version = m.version().empty() ? "1" : m.version();
  if (!m.device().empty()) hub_->default_device = m.device();
  ModelMeta meta;
  if (!m.path().empty()) {
    meta.name = name;
    meta.version = version;
    meta.path = m.path();
    meta.format = m.format().empty() ? "onnx" : m.format();
    meta.task = "detect";
    meta.imgsz = 640;
    meta.num_classes = 80;
    const auto& kv = m.meta();
    if (kv.count("task")) meta.task = kv.at("task");
    if (kv.count("labels")) meta.labels = kv.at("labels");
    if (kv.count("imgsz")) meta.imgsz = std::atoi(kv.at("imgsz").c_str());
    if (kv.count("num_classes")) meta.num_classes = std::atoi(kv.at("num_classes").c_str());
  } else {
    auto resolved = hub_->repo.Resolve(name, version);
    if (!resolved) {
      *response->mutable_status() =
          MakeStatus(visionai::infer::v1::NOT_FOUND, "model not found: " + name + "/" + version);
      return grpc::Status::OK;
    }
    meta = *resolved;
  }
  std::string err;
  if (!hub_->LoadExplicit(meta, &err)) {
    *response->mutable_status() = MakeStatus(visionai::infer::v1::BACKEND_FAILURE, err);
    return grpc::Status::OK;
  }
  *response->mutable_status() = MakeStatus(visionai::infer::v1::OK, "loaded");
  return grpc::Status::OK;
}

grpc::Status InferServiceImpl::UnloadModel(grpc::ServerContext*,
                                           const visionai::infer::v1::UnloadModelRequest* request,
                                           visionai::infer::v1::UnloadModelResponse* response) {
  const std::string name = request->name().empty() ? "primary" : request->name();
  hub_->Unload(name);
  *response->mutable_status() = MakeStatus(visionai::infer::v1::OK, "unloaded");
  return grpc::Status::OK;
}

grpc::Status InferServiceImpl::OpenSession(grpc::ServerContext*,
                                           const visionai::infer::v1::OpenSessionRequest* request,
                                           visionai::infer::v1::OpenSessionResponse* response) {
  const auto& c = request->config();
  if (c.session_id().empty()) {
    *response->mutable_status() =
        MakeStatus(visionai::infer::v1::INVALID_ARGUMENT, "session_id required (stream id)");
    return grpc::Status::OK;
  }
  if (!hub_->Find(c.model_name().empty() ? "primary" : c.model_name())) {
    *response->mutable_status() =
        MakeStatus(visionai::infer::v1::NOT_READY, "model not loaded");
    return grpc::Status::OK;
  }
  hub_->sessions.Upsert(FromProto(c));
  *response->mutable_status() = MakeStatus(visionai::infer::v1::OK, "opened");
  return grpc::Status::OK;
}

grpc::Status InferServiceImpl::UpdateSession(
    grpc::ServerContext*, const visionai::infer::v1::UpdateSessionRequest* request,
    visionai::infer::v1::UpdateSessionResponse* response) {
  const auto& c = request->config();
  if (c.session_id().empty()) {
    *response->mutable_status() =
        MakeStatus(visionai::infer::v1::INVALID_ARGUMENT, "session_id required");
    return grpc::Status::OK;
  }
  hub_->sessions.Upsert(FromProto(c));
  *response->mutable_status() = MakeStatus(visionai::infer::v1::OK, "updated");
  return grpc::Status::OK;
}

grpc::Status InferServiceImpl::CloseSession(grpc::ServerContext*,
                                            const visionai::infer::v1::CloseSessionRequest* request,
                                            visionai::infer::v1::CloseSessionResponse* response) {
  if (request->session_id().empty()) {
    *response->mutable_status() =
        MakeStatus(visionai::infer::v1::INVALID_ARGUMENT, "session_id required");
    return grpc::Status::OK;
  }
  if (!hub_->sessions.Remove(request->session_id())) {
    *response->mutable_status() = MakeStatus(visionai::infer::v1::NOT_FOUND, "session not found");
    return grpc::Status::OK;
  }
  *response->mutable_status() = MakeStatus(visionai::infer::v1::OK, "closed");
  return grpc::Status::OK;
}

grpc::Status InferServiceImpl::Infer(grpc::ServerContext*,
                                     const visionai::infer::v1::InferRequest* request,
                                     visionai::infer::v1::InferResponse* response) {
  response->set_frame_id(request->frame_id());
  auto sess = hub_->sessions.Get(request->session_id());
  if (!sess) {
    *response->mutable_status() = MakeStatus(visionai::infer::v1::NOT_FOUND, "session not found");
    return grpc::Status::OK;
  }
  auto backend = hub_->Find(sess->model_name);
  if (!backend || !backend->IsLoaded()) {
    *response->mutable_status() = MakeStatus(visionai::infer::v1::NOT_READY, "model not loaded");
    return grpc::Status::OK;
  }

  const auto& img = request->image();
  if (img.channels() != 3 || img.layout() != "HWC" || img.color() != "BGR" ||
      img.dtype() != "UINT8" || img.width() <= 0 || img.height() <= 0 ||
      static_cast<int>(img.data().size()) != img.width() * img.height() * 3) {
    *response->mutable_status() =
        MakeStatus(visionai::infer::v1::INVALID_ARGUMENT, "invalid ImageTensor (expect BGR HWC UINT8)");
    return grpc::Status::OK;
  }

  const auto* filter =
      sess->class_filter.empty() ? nullptr : &sess->class_filter;
  auto raw = backend->InferBgr(reinterpret_cast<const uint8_t*>(img.data().data()), img.width(),
                               img.height(), sess->conf, sess->imgsz, filter);
  if (!raw.ok) {
    *response->mutable_status() =
        MakeStatus(visionai::infer::v1::BACKEND_FAILURE, raw.error);
    return grpc::Status::OK;
  }
  response->set_infer_ms(raw.infer_ms);
  for (const auto& b : raw.boxes) {
    auto* d = response->add_detections();
    d->set_x1(b.x1);
    d->set_y1(b.y1);
    d->set_x2(b.x2);
    d->set_y2(b.y2);
    d->set_class_id(b.class_id);
    d->set_conf(b.conf);
    d->set_label(b.label);
    d->set_model_name(sess->model_name);
    for (float k : b.keypoints) d->add_keypoint(k);
  }
  *response->mutable_status() = MakeStatus(visionai::infer::v1::OK, "ok");
  return grpc::Status::OK;
}

grpc::Status InferServiceImpl::AnalyzeFace(grpc::ServerContext*,
                                           const visionai::infer::v1::AnalyzeFaceRequest* request,
                                           visionai::infer::v1::AnalyzeFaceResponse* response) {
  const auto& img = request->image();
  if (img.channels() != 3 || img.layout() != "HWC" || img.color() != "BGR" ||
      img.dtype() != "UINT8" || img.width() <= 0 || img.height() <= 0 ||
      static_cast<int>(img.data().size()) != img.width() * img.height() * 3) {
    *response->mutable_status() =
        MakeStatus(visionai::infer::v1::INVALID_ARGUMENT, "invalid ImageTensor (expect BGR HWC UINT8)");
    return grpc::Status::OK;
  }
  std::vector<FaceHitLocal> hits;
  std::string err;
  const auto t0 = std::chrono::steady_clock::now();
  const bool ok = faces_.Analyze(
      reinterpret_cast<const uint8_t*>(img.data().data()), img.width(), img.height(),
      request->det_model(), request->embed_model(), request->genderage_model(), request->det_conf(),
      request->det_size(), request->max_faces(), request->with_embedding(), request->with_genderage(),
      &hits, &err);
  const auto t1 = std::chrono::steady_clock::now();
  response->set_infer_ms(std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count());
  if (!ok) {
    *response->mutable_status() = MakeStatus(visionai::infer::v1::BACKEND_FAILURE, err);
    return grpc::Status::OK;
  }
  for (const auto& h : hits) {
    auto* f = response->add_faces();
    f->set_x1(h.x1);
    f->set_y1(h.y1);
    f->set_x2(h.x2);
    f->set_y2(h.y2);
    f->set_det_score(h.det_score);
    for (float k : h.kps) f->add_kps(k);
    for (float e : h.embedding) f->add_embedding(e);
    f->set_has_attr(h.has_attr);
    f->set_gender(h.gender);
    f->set_age(h.age);
  }
  *response->mutable_status() = MakeStatus(visionai::infer::v1::OK, "ok");
  return grpc::Status::OK;
}

}  // namespace visionai::inferd
