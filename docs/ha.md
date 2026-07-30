# 多 Worker HA 演练

启用流租约后，多台机器可同时运行 `python -m visionai.worker`，每路流仅由持有 Redis 租约的 worker 处理。

## 配置

各 worker 节点 `config.ini` 或环境变量：

```ini
# 建议写在 [basic] 或通过环境变量
# STREAM_LEASE_ENABLED=true
# STREAM_LEASE_TTL_SEC=30
# STREAM_LEASE_RENEW_SEC=10
# WORKER_ID=node-a-1
```

环境变量优先：

```bash
export STREAM_LEASE_ENABLED=true
export WORKER_ID=node-a
export REDIS_HOST=192.168.2.10
./start.sh   # 或只启 worker：python -m visionai.worker
```

API 只需跑一份（`python -m visionai.api`）。预览优先走 ZLM 播放 URL（`[zlm] enabled=true`），不依赖本机内存预览。

## 演练步骤

1. 节点 A、B 均启动 `visionai.worker` + 共享 Redis/MinIO/ZLM  
2. 观察日志：每路仅一个节点打印「开始处理视频流」  
3. `kill` 节点 A 的 worker  
4. 在 `STREAM_LEASE_TTL_SEC` 内，节点 B 应通过离线检测拿到租约并接管  
5. 确认告警继续写入 Redis、预览经 ZLM 仍可播  

## 注意

- 租约键：`{redis_key_prefix}stream_lease:{stream_id}`  
- 流在线状态键：`{redis_key_prefix}stream_runtime_status`（各 worker 写心跳，API 只读；与租约独立）  
- Redis 故障时租约逻辑降级为「本机全量处理」，避免全集群停检  
- 训练实验室仍建议只在 API 节点运行
