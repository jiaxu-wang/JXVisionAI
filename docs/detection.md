# 检测与模型

## 检测类型总览

- **COCO 80 类**：索引 0–79，如 `0`=人物、`67`=手机，在「检测类型配置」中按类勾选
- **扩展行为**（独立键名）：

| 键名 | 中文名 | 模型 |
|------|--------|------|
| `call` | 打电话 | `make_call.onnx` 或 COCO+姿态 |
| `phone_play` | 玩手机 | COCO + 姿态 |
| `gather` | 人员聚集 | 仅 COCO person 框 |
| `smoking` | 吸烟 | `smoking_detection.pt` 或 ViT ONNX |
| `face` | 人脸检测 | `face_detection.onnx` |
| `face_recognition` | **人脸识别** | `buffalo_l` + 人脸库 |
| `no_glasses` | **未戴眼镜** | `glasses_detection.pt`（0=未戴，1=已戴） |
| `fall` / `flame` / `mask` 等 | 各扩展 | 对应 `models/*` |

训练实验室场景模板 **「未戴眼镜」** 可训可一键部署；完整步骤见 [training-glasses-guide.md](training-glasses-guide.md)。

---

## 吸烟

- **YOLO 直连**（`smoking_yolo_direct=true`，推荐）：`smoking_detection.pt` 单类检测
- **ViT ONNX**（备用）：人物裁剪 + 二分类，可配合香烟 YOLO 门控减误报

---

## 打电话 / 玩手机

1. COCO 检出 person + cell phone，框重叠配对
2. 若启用 `pose_for_phone_enabled` 且 `pose_model` 可用：YOLOv8-pose 区分贴耳（CALLING）与把玩（PLAY_PHONE）
3. 否则按手机竖直位置启发式区分

---

## 模型目录

所有权重放在 `models/`，详见 [快速开始 - 模型准备](getting-started.md#4-准备模型)。权重不入 Git，部署时自行下载或从训练管线导出。

训练与导出见 **`training_system/README.md`** 与 Web **训练实验室**（`/training`）：

- 默认预训练：**YOLOv8s**（`yolov8s.pt`）
- 开训门槛：已审核 ≥50 张、每类 ≥30 框、独立 val/test ≥10
- 预标注写入草稿，须审核后才训练
- 部署门禁：测试集 mAP@0.5≥0.40 且 P/R≥0.35；`make_call` 自动导出 ONNX
- 安全帽类别契约：`0=no_helmet`（违规）、`1=helmet`（合规）

人脸识别实现细节见 [face_recognition_design.md](face_recognition_design.md)。
