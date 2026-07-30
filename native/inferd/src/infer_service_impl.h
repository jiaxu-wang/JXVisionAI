#pragma once

#include "core/engine_hub.h"
#include "visionai/infer/v1/infer.grpc.pb.h"

namespace visionai::inferd {

class InferServiceImpl final : public visionai::infer::v1::InferService::Service {
 public:
  explicit InferServiceImpl(EngineHub* hub);

  grpc::Status Live(grpc::ServerContext* context, const visionai::infer::v1::LiveRequest* request,
                    visionai::infer::v1::LiveResponse* response) override;

  grpc::Status Ready(grpc::ServerContext* context, const visionai::infer::v1::ReadyRequest* request,
                     visionai::infer::v1::ReadyResponse* response) override;

  grpc::Status ListModels(grpc::ServerContext* context,
                          const visionai::infer::v1::ListModelsRequest* request,
                          visionai::infer::v1::ListModelsResponse* response) override;

  grpc::Status LoadModel(grpc::ServerContext* context,
                         const visionai::infer::v1::LoadModelRequest* request,
                         visionai::infer::v1::LoadModelResponse* response) override;

  grpc::Status UnloadModel(grpc::ServerContext* context,
                           const visionai::infer::v1::UnloadModelRequest* request,
                           visionai::infer::v1::UnloadModelResponse* response) override;

  grpc::Status OpenSession(grpc::ServerContext* context,
                           const visionai::infer::v1::OpenSessionRequest* request,
                           visionai::infer::v1::OpenSessionResponse* response) override;

  grpc::Status UpdateSession(grpc::ServerContext* context,
                             const visionai::infer::v1::UpdateSessionRequest* request,
                             visionai::infer::v1::UpdateSessionResponse* response) override;

  grpc::Status CloseSession(grpc::ServerContext* context,
                            const visionai::infer::v1::CloseSessionRequest* request,
                            visionai::infer::v1::CloseSessionResponse* response) override;

  grpc::Status Infer(grpc::ServerContext* context, const visionai::infer::v1::InferRequest* request,
                     visionai::infer::v1::InferResponse* response) override;

 private:
  EngineHub* hub_;
};

}  // namespace visionai::inferd
