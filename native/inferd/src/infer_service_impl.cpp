#include "infer_service_impl.h"

#include "version.h"

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
  const bool ready = hub_->primary.IsLoaded();
  response->set_ready(ready);
  if (ready) {
    *response->mutable_status() = MakeStatus(visionai::infer::v1::OK, "ready");
    for (const auto& n : hub_->repo.LoadedNames()) response->add_loaded_models(n);
  } else {
    *response->mutable_status() =
        MakeStatus(visionai::infer::v1::NOT_READY, "no model loaded");
  }
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
  if (name != "primary") {
    *response->mutable_status() =
        MakeStatus(visionai::infer::v1::UNSUPPORTED, "only primary supported in Phase1");
    return grpc::Status::OK;
  }
  if (!m.device().empty()) hub_->default_device = m.device();
  std::string err;
  if (!hub_->LoadPrimary(name, version, &err)) {
    const auto code = err.find("not found") != std::string::npos
                          ? visionai::infer::v1::NOT_FOUND
                          : visionai::infer::v1::BACKEND_FAILURE;
    *response->mutable_status() = MakeStatus(code, err);
    return grpc::Status::OK;
  }
  *response->mutable_status() = MakeStatus(visionai::infer::v1::OK, "loaded");
  return grpc::Status::OK;
}

grpc::Status InferServiceImpl::UnloadModel(grpc::ServerContext*,
                                           const visionai::infer::v1::UnloadModelRequest* request,
                                           visionai::infer::v1::UnloadModelResponse* response) {
  const std::string name = request->name().empty() ? "primary" : request->name();
  if (name != "primary") {
    *response->mutable_status() =
        MakeStatus(visionai::infer::v1::UNSUPPORTED, "only primary supported in Phase1");
    return grpc::Status::OK;
  }
  hub_->primary.Unload();
  hub_->repo.MarkUnloaded("primary");
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
  hub_->sessions.Upsert(FromProto(c));
  std::string serr;
  hub_->primary.EnsureSessionSlot(c.session_id(), &serr);
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
  hub_->primary.DropSessionSlot(request->session_id());
  *response->mutable_status() = MakeStatus(visionai::infer::v1::OK, "closed");
  return grpc::Status::OK;
}

grpc::Status InferServiceImpl::Infer(grpc::ServerContext*,
                                     const visionai::infer::v1::InferRequest* request,
                                     visionai::infer::v1::InferResponse* response) {
  response->set_frame_id(request->frame_id());
  if (!hub_->primary.IsLoaded()) {
    *response->mutable_status() = MakeStatus(visionai::infer::v1::NOT_READY, "model not loaded");
    return grpc::Status::OK;
  }
  auto sess = hub_->sessions.Get(request->session_id());
  if (!sess) {
    *response->mutable_status() = MakeStatus(visionai::infer::v1::NOT_FOUND, "session not found");
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
  auto raw = hub_->primary.InferBgrForSession(
      request->session_id(), reinterpret_cast<const uint8_t*>(img.data().data()), img.width(),
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
    d->set_model_name(sess->model_name);
  }
  *response->mutable_status() = MakeStatus(visionai::infer::v1::OK, "ok");
  return grpc::Status::OK;
}

}  // namespace visionai::inferd
