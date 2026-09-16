# 刀具检测专模

- 键：`knife`（scene）
- 权重：`Subh775/Threat-Detection-YOLOv8n`（`weights/best.pt`）
- 启用类：仅 `knife`（class_id=3）。`Gun` / `explosion` / `grenade` 不告警。

权重不入 Git。下载并登记：

```bash
./env/bin/python scripts/download_weapon_specialists.py
```
