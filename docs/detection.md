# 检测与模型

## 检测类型总览

- **COCO 80 类**：索引 0–79，如 `0`=人物、`67`=手机，在「检测类型配置」中按类勾选
- **内置扩展**（独立键名）：

| 键名 | 中文名 | 说明 |
|------|--------|------|
| `call` | 打电话 | `make_call.onnx` 或 COCO+姿态 |
| `phone_play` | 玩手机 | COCO + 姿态 |
| `gather` | 人员聚集 | 仅 COCO person 框 |
| `face_recognition` | 人脸识别 | `buffalo_l` + 人脸库 |

- **训练专模**（动态）：由训练实验室部署到 `models/specialists/<key>/`，出现在检测类型列表中，可按流勾选；可在训练实验室或管理平台删除。

原 B 列表硬编码专模（吸烟、安全帽、眼镜、跌倒、火焰等）已从内置配置移除，改由 **训练实验室 → 部署专模** 路径上线。

---

## 打电话 / 玩手机

1. COCO 检出 person + cell phone，框重叠配对
2. 若启用 `pose_for_phone_enabled` 且 `pose_model` 可用：YOLO26-pose 区分贴耳（CALLING）与把玩（PLAY_PHONE）
3. 否则按手机竖直位置启发式区分

---

## 训练专模部署

1. 在 Web **训练实验室**（`/training`）选择场景模板或自定义项目，完成标注与训练
2. 测试集通过质量门禁后，点击「一键部署」：
   - **make_call**：复制权重到 `models/`，导出 ONNX，更新 `config.ini`（需重启）
   - **其他场景**（吸烟、安全帽、眼镜、自定义等）：部署到 `models/specialists/<key>/`，写入 `specialist.json`，**插件热加载**，无需重启
3. 在管理平台「检测类型配置」中为各视频流勾选对应专模键名

专模 `kind`：

- `scene`：全画面场景检测（可选 `class_ids`）
- `person_event`：人物关联事件（`positive_class_ids`）
- `violation`：合规/违规双类（`subject_class_ids` 违规，`comply_class_ids` 合规）

---

## 模型目录

- `models/`：YOLO 主模型、`make_call.onnx`、姿态模型、人脸识别 buffalo_l 等内置权重
- `models/specialists/<key>/`：训练实验室部署的专模（`model.pt` + `specialist.json`）

详见 [快速开始 - 准备模型（YOLO26）](getting-started.md#4-准备模型yolo26)。权重不入 Git，部署时自行下载或从训练管线导出。

训练与导出见 **`training_system/README.md`** 与 Web **训练实验室**（`/training`）：

- 默认预训练：**YOLO26s**（`models/yolo26s.pt`）
- 开训门槛：已审核 ≥50 张、每类 ≥30 框、独立 val/test ≥10
- 预标注写入草稿，须审核后才训练
- 部署门禁：测试集 mAP@0.5≥0.40 且 P/R≥0.35；`make_call` 自动导出 ONNX
- 安全帽 / 眼镜等 violation 模板：类别顺序须与模板一致（如 `0=no_helmet, 1=helmet`）

人脸识别实现细节见 [face_recognition_design.md](face_recognition_design.md).
