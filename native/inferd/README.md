# visionai-inferd

C++ gRPC 推理守护进程。运行时的 YOLO 检测、姿态、人脸检测 / 特征和性别年龄都只走这里。训练、标注、车牌 OCR 仍在 Python。

`./start.sh` 和 `./scripts/install_linux.sh start` 会拉起本进程。套接字在仓库 `run/visionai-inferd.sock`。Docker 把 `./run` 挂到 `/app/run`，容器里的 endpoint 是 `unix:///app/run/visionai-inferd.sock`。

`.pt` 第一次被用到时由 Ultralytics 导出成旁边的 `.onnx`，之后逐帧不再加载 PyTorch。

## 依赖

同机 Linux（WSL / 云服务器）：

- CMake ≥ 3.16、C++17 编译器
- `protobuf-compiler`、`libprotobuf-dev`
- `libgrpc++-dev`、`protobuf-compiler-grpc`

Ubuntu 示例：

```bash
sudo apt-get update
sudo apt-get install -y cmake build-essential pkg-config \
  protobuf-compiler libprotobuf-dev libgrpc++-dev protobuf-compiler-grpc
```

也可用 Docker（需当前用户在 `docker` 组，或 root 执行）：

```bash
./native/inferd/scripts/build_docker.sh
./native/inferd/scripts/verify_live.sh
```

## 本机构建（已安装 apt 依赖时）

```bash
cd native/inferd
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j"$(nproc)"
./build/visionai-inferd --version
```

`start.sh` 会依次查找 `native/inferd/build-user/visionai-inferd`、`native/inferd/build/visionai-inferd`。

## 手工验证 Live

默认监听：仓库下 `run/visionai-inferd.sock`

```bash
# 终端 A
./native/inferd/build/visionai-inferd --uds /tmp/visionai-inferd.sock --repo models/repo

# 终端 B
./native/inferd/build/visionai-inferd --check-live /tmp/visionai-inferd.sock
```

通过标准：

- `Live.alive=true`
- `api_version=v1`
- `server_version` 非空

就绪探针：应用启动后 `curl -s http://127.0.0.1:5000/readyz`（inferd 不在时 ready 为 false）。

## 相关文档

- [系统架构](../../docs/architecture.md)
- [配置说明 · infer](../../docs/configuration.md#主检后端-infer可选)
- [快速开始](../../docs/getting-started.md)
