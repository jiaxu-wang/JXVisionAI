#include <atomic>
#include <chrono>
#include <csignal>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include <grpcpp/grpcpp.h>
#include <unistd.h>

#include "core/engine_hub.h"
#include "infer_service_impl.h"
#include "version.h"
#include "visionai/infer/v1/infer.grpc.pb.h"

namespace {

std::atomic<bool> g_shutdown{false};
void OnSignal(int) { g_shutdown.store(true); }

struct Options {
  std::string uds = "unix:///tmp/visionai-inferd.sock";
  std::string repo = "models/repo";
  std::string device = "cpu";
  bool autoload_primary = true;
  bool check_live = false;
  bool check_s2 = false;
  bool check_infer = false;
  std::string test_image;  // raw BGR dump: path.meta next to path with "W H"
};

void PrintUsage(const char* argv0) {
  std::cerr
      << "Usage: " << argv0 << " [options]\n"
      << "  --uds PATH           UDS path (default /tmp/visionai-inferd.sock)\n"
      << "  --repo DIR           model repository root\n"
      << "  --device cpu|cuda:0  default device string\n"
      << "  --no-autoload        do not LoadModel(primary/1) on start\n"
      << "  --check-live [PATH]  Live probe\n"
      << "  --check-s2 [PATH]    Ready/ListModels/LoadModel gate\n"
      << "  --check-infer PATH   OpenSession+Infer on raw BGR file (needs .meta WxH)\n"
      << "  --version\n";
}

std::string NormalizeUdsUri(std::string path_or_uri) {
  if (path_or_uri.rfind("unix:", 0) == 0) return path_or_uri;
  return "unix://" + path_or_uri;
}

std::string UdsFilesystemPath(const std::string& uri) {
  const std::string prefix = "unix://";
  if (uri.rfind(prefix, 0) != 0) return uri;
  return uri.substr(prefix.size());
}

std::unique_ptr<visionai::infer::v1::InferService::Stub> MakeStub(const std::string& uds) {
  auto ch = grpc::CreateChannel(uds, grpc::InsecureChannelCredentials());
  return visionai::infer::v1::InferService::NewStub(ch);
}

int RunCheckLive(const std::string& uds) {
  auto stub = MakeStub(uds);
  visionai::infer::v1::LiveRequest req;
  visionai::infer::v1::LiveResponse resp;
  grpc::ClientContext ctx;
  ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(3));
  auto st = stub->Live(&ctx, req, &resp);
  if (!st.ok() || !resp.alive() || resp.api_version() != visionai::inferd::kApiVersion) {
    std::cerr << "Live failed\n";
    return 1;
  }
  std::cout << "Live OK server_version=" << resp.server_version()
            << " api_version=" << resp.api_version() << "\n";
  return 0;
}

int RunCheckS2(const std::string& uds) {
  auto stub = MakeStub(uds);
  {
    visionai::infer::v1::ReadyRequest req;
    visionai::infer::v1::ReadyResponse resp;
    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
    auto st = stub->Ready(&ctx, req, &resp);
    if (!st.ok()) {
      std::cerr << "Ready RPC failed\n";
      return 1;
    }
    if (!resp.ready()) {
      // try load
      visionai::infer::v1::LoadModelRequest lreq;
      lreq.mutable_model()->set_name("primary");
      lreq.mutable_model()->set_version("1");
      visionai::infer::v1::LoadModelResponse lresp;
      grpc::ClientContext lctx;
      lctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(30));
      auto lst = stub->LoadModel(&lctx, lreq, &lresp);
      if (!lst.ok() || lresp.status().code() != visionai::infer::v1::OK) {
        std::cerr << "LoadModel failed: " << lresp.status().message() << "\n";
        return 1;
      }
    }
  }
  {
    visionai::infer::v1::ReadyRequest req;
    visionai::infer::v1::ReadyResponse resp;
    grpc::ClientContext ctx;
    auto st = stub->Ready(&ctx, req, &resp);
    if (!st.ok() || !resp.ready()) {
      std::cerr << "Ready not true after load\n";
      return 1;
    }
    std::cout << "Ready OK loaded=";
    for (const auto& n : resp.loaded_models()) std::cout << n << " ";
    std::cout << "\n";
  }
  {
    visionai::infer::v1::ListModelsRequest req;
    visionai::infer::v1::ListModelsResponse resp;
    grpc::ClientContext ctx;
    auto st = stub->ListModels(&ctx, req, &resp);
    if (!st.ok() || resp.status().code() != visionai::infer::v1::OK) {
      std::cerr << "ListModels failed\n";
      return 1;
    }
    bool found = false;
    for (const auto& m : resp.models()) {
      if (m.name() == "primary") found = true;
    }
    if (!found) {
      std::cerr << "ListModels missing primary\n";
      return 1;
    }
    std::cout << "ListModels OK count=" << resp.models_size() << "\n";
  }
  std::cout << "S2 verification PASSED\n";
  return 0;
}

int RunCheckInfer(const std::string& uds, const std::string& image_path) {
  std::ifstream meta(image_path + ".meta");
  int w = 0, h = 0;
  if (!(meta >> w >> h) || w <= 0 || h <= 0) {
    std::cerr << "Need " << image_path << ".meta with: WIDTH HEIGHT\n";
    return 1;
  }
  std::ifstream in(image_path, std::ios::binary);
  std::vector<char> buf((std::istreambuf_iterator<char>(in)), {});
  if (static_cast<int>(buf.size()) != w * h * 3) {
    std::cerr << "BGR size mismatch\n";
    return 1;
  }

  auto stub = MakeStub(uds);
  {
    visionai::infer::v1::OpenSessionRequest req;
    req.mutable_config()->set_session_id("s3-test");
    req.mutable_config()->set_model_name("primary");
    req.mutable_config()->set_conf(0.25f);
    req.mutable_config()->set_imgsz(640);
    visionai::infer::v1::OpenSessionResponse resp;
    grpc::ClientContext ctx;
    stub->OpenSession(&ctx, req, &resp);
    if (resp.status().code() != visionai::infer::v1::OK) {
      std::cerr << "OpenSession failed\n";
      return 1;
    }
  }
  visionai::infer::v1::InferRequest req;
  req.set_session_id("s3-test");
  req.set_frame_id(1);
  auto* img = req.mutable_image();
  img->set_width(w);
  img->set_height(h);
  img->set_channels(3);
  img->set_layout("HWC");
  img->set_color("BGR");
  img->set_dtype("UINT8");
  img->set_data(buf.data(), buf.size());
  visionai::infer::v1::InferResponse resp;
  grpc::ClientContext ctx;
  ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(30));
  auto st = stub->Infer(&ctx, req, &resp);
  if (!st.ok() || resp.status().code() != visionai::infer::v1::OK) {
    std::cerr << "Infer failed: " << resp.status().message() << "\n";
    return 1;
  }
  std::cout << "Infer OK dets=" << resp.detections_size() << " infer_ms=" << resp.infer_ms()
            << "\n";
  for (int i = 0; i < std::min(5, resp.detections_size()); ++i) {
    const auto& d = resp.detections(i);
    std::cout << "  cls=" << d.class_id() << " conf=" << d.conf() << " box=[" << d.x1() << ","
              << d.y1() << "," << d.x2() << "," << d.y2() << "]\n";
  }

  // S4: second session + close
  {
    visionai::infer::v1::OpenSessionRequest req2;
    req2.mutable_config()->set_session_id("s4-test");
    req2.mutable_config()->set_conf(0.9f);
    visionai::infer::v1::OpenSessionResponse resp2;
    grpc::ClientContext ctx2;
    stub->OpenSession(&ctx2, req2, &resp2);
  }
  {
    visionai::infer::v1::CloseSessionRequest creq;
    creq.set_session_id("s4-test");
    visionai::infer::v1::CloseSessionResponse cresp;
    grpc::ClientContext cctx;
    stub->CloseSession(&cctx, creq, &cresp);
    visionai::infer::v1::InferRequest ireq = req;
    ireq.set_session_id("s4-test");
    visionai::infer::v1::InferResponse iresp;
    grpc::ClientContext ictx;
    stub->Infer(&ictx, ireq, &iresp);
    if (iresp.status().code() != visionai::infer::v1::NOT_FOUND) {
      std::cerr << "expected NOT_FOUND after CloseSession\n";
      return 1;
    }
  }
  std::cout << "S3/S4 verification PASSED\n";
  return 0;
}

int RunServer(const Options& opt) {
  const std::string sock_path = UdsFilesystemPath(opt.uds);
  ::unlink(sock_path.c_str());

  visionai::inferd::EngineHub hub(opt.repo, opt.device);
  if (opt.autoload_primary) {
    std::string err;
    if (!hub.LoadPrimary("primary", "1", &err)) {
      std::cerr << "autoload primary failed: " << err << " (server still starts; use LoadModel)\n";
    } else {
      std::cout << "autoload primary OK device=" << opt.device << "\n";
    }
  }

  visionai::inferd::InferServiceImpl service(&hub);
  grpc::ServerBuilder builder;
  builder.AddListeningPort(opt.uds, grpc::InsecureServerCredentials());
  builder.RegisterService(&service);
  std::unique_ptr<grpc::Server> server(builder.BuildAndStart());
  if (!server) {
    std::cerr << "Failed to start on " << opt.uds << "\n";
    return 1;
  }

  g_shutdown.store(false);
  std::signal(SIGINT, OnSignal);
  std::signal(SIGTERM, OnSignal);
  std::thread stopper([&server]() {
    while (!g_shutdown.load()) std::this_thread::sleep_for(std::chrono::milliseconds(50));
    server->Shutdown();
  });

  std::cout << "visionai-inferd " << visionai::inferd::kServerVersion << " listening on "
            << opt.uds << " repo=" << opt.repo << "\n";
  server->Wait();
  stopper.join();
  ::unlink(sock_path.c_str());
  std::cout << "visionai-inferd stopped\n";
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  Options opt;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    if (arg == "-h" || arg == "--help") {
      PrintUsage(argv[0]);
      return 0;
    }
    if (arg == "--version") {
      std::cout << visionai::inferd::kServerVersion << " api=" << visionai::inferd::kApiVersion
                << "\n";
      return 0;
    }
    if (arg == "--uds" && i + 1 < argc) {
      opt.uds = NormalizeUdsUri(argv[++i]);
      continue;
    }
    if (arg == "--repo" && i + 1 < argc) {
      opt.repo = argv[++i];
      continue;
    }
    if (arg == "--device" && i + 1 < argc) {
      opt.device = argv[++i];
      continue;
    }
    if (arg == "--no-autoload") {
      opt.autoload_primary = false;
      continue;
    }
    if (arg == "--check-live") {
      opt.check_live = true;
      if (i + 1 < argc && argv[i + 1][0] != '-') opt.uds = NormalizeUdsUri(argv[++i]);
      continue;
    }
    if (arg == "--check-s2") {
      opt.check_s2 = true;
      if (i + 1 < argc && argv[i + 1][0] != '-') opt.uds = NormalizeUdsUri(argv[++i]);
      continue;
    }
    if (arg == "--check-infer" && i + 1 < argc) {
      opt.check_infer = true;
      opt.test_image = argv[++i];
      continue;
    }
    std::cerr << "Unknown: " << arg << "\n";
    PrintUsage(argv[0]);
    return 2;
  }

  if (opt.check_live) return RunCheckLive(opt.uds);
  if (opt.check_s2) return RunCheckS2(opt.uds);
  if (opt.check_infer) return RunCheckInfer(opt.uds, opt.test_image);
  return RunServer(opt);
}
