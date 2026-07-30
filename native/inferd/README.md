# visionai-inferd

C++ gRPC 推理守护进程（架构说明见 [`docs/architecture.md`](../../docs/architecture.md)）。

已通过 `[infer] backend=cpp` 接入 Python：`start.sh` 在检测到可执行文件时自动拉起；worker 经 UDS `unix:///tmp/visionai-inferd.sock` 送帧做主检，行为/画框/告警仍在 Python。

## 启用方式

1. 构建本目录可执行文件（见下）
2. 准备 `models/repo/primary/<version>/model.onnx`（及 `model.json`）
3. `config.ini`：

```ini
[infer]
backend = cpp
endpoint = unix:///tmp/visionai-inferd.sock
on_daemon_error = fail   # 或 fallback_python
```

4. `./stop.sh && ./start.sh`（日志：`logs/inferd.log`）

日常对比 YOLO26 档位精度时，用默认 `backend=python` 改 `[models] yolo_model` 即可，不必启 inferd。

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

默认监听：`unix:///tmp/visionai-inferd.sock`

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

就绪探针：应用启动后 `curl -s http://127.0.0.1:5000/readyz`（`backend=cpp` 时会检查 inferd）。

## 相关文档

- [系统架构](../../docs/architecture.md)
- [配置说明 · infer](../../docs/configuration.md#主检后端-infer可选)
- [快速开始](../../docs/getting-started.md)
