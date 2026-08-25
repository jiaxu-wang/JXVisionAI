# 检测与模型

## 能力分层

| 层 | 说明 | 如何启用 |
|----|------|----------|
| **主检 COCO 80** | YOLO26 预训练，索引 0–79 | 各流「检测类型配置」勾选对应类 |
| **内置扩展** | 玩手机 / 聚集 / 人脸识别 / 车牌识别 | 同上勾选独立键名 |
| **外置专模（导入）** | 社区/平台现成 YOLO 权重，自行提供 | 训练实验室 → **导入现成专模** |
| **自训专模** | 本平台标注训练后部署 | 训练实验室 → 一键部署 |

主检与专模**并行**：不要用行业多类模型替换 `[models] yolo_model`。

---

## 检测类型总览

- **COCO 80 类**：索引 0–79，如 `0`=人物、`67`=手机，在「检测类型配置」中按类勾选
- **内置扩展**（独立键名）：

| 键名 | 中文名 | 说明 |
|------|--------|------|
| `phone_play` | 玩手机 | COCO person + cellphone 重叠 + 可选姿态 |
| `gather` | 人员聚集 | 仅 COCO person 框 |
| `face_recognition` | 人脸识别 | `buffalo_l` + 人脸库 |
| `plate_recognition` | 车牌识别 | 专模 `plate` 检测框 + RapidOCR 读号 + 车牌库 |

- **专模**（动态，`models/specialists/<key>/`）：
  - **自训**：训练实验室达标后「一键部署」
  - **导入**：训练实验室「导入现成专模」上传 `.pt` / `.onnx` 并填写元数据  
  部署/导入后出现在检测类型列表，可按流勾选；可在训练实验室或管理平台删除。

原 B 列表硬编码专模（吸烟、安全帽、眼镜、跌倒、火焰等）已从内置配置移除，改由 **导入现成权重** 或 **训练实验室部署** 上线。

> **打电话已下线**：不再提供内置 `call` / `make_call` 或默认 `phone_call` 专模。需要时用训练实验室「自定义」自训，或导入 YOLO 检测权重为 `person_event` 专模（key 可用 `phone_call`）。

---

## 玩手机

1. COCO 检出 person + cell phone，框重叠配对  
2. 若启用 `pose_for_phone_enabled` 且 `pose_model` 可用：YOLO26-pose 用手机中心相对手腕/身前距离辅助判定「玩手机」  
3. 否则按手机竖直位置等启发式区分  

姿态相关阈值见 `config.ini` `[models]`：`phone_play_wrist_ratio`、`phone_vertical_boundary`、`phone_pose_kp_min_conf` 等。

---

## 导入现成专模（社区 / 平台权重）

适用于 Hugging Face、[Ultralytics Platform](https://platform.ultralytics.com/) 等处下载的 **Ultralytics YOLO 检测** 权重。

1. 打开 Web **训练实验室**（`/training`）左侧 **导入现成专模**
2. 选择 `.pt` 或 `.onnx`，可选点 **读取类别** 预检类别名
3. 填写：
   - **key**：小写字母开头，仅 `a-z0-9_`（如 `hardhat`），不可与 COCO 数字键或内置扩展键冲突
   - **中文名 / kind**：
     - `person_event`：人物关联事件（如吸烟），默认告警类 `positive_class_ids=0`
     - `violation`：合规/违规双类（如安全帽），默认 `subject=0`（违规）、`comply=1`（合规）
     - `scene`：全画面场景类
   - 阈值 `conf` / `score_threshold` / `min_duration_sec`（可按现场再调）
4. 点 **导入并上线** → 写入 `models/specialists/<key>/`（`model.pt` + `specialist.json`），**热加载，一般无需重启**
5. 管理平台 **检测配置** → **检测类型配置** → 勾选该专模 → **保存检测配置**

约束：

- 须为 YOLO **detect** 权重；类别索引必须与所选 `kind` 约定一致
- 同名 `key` 会备份旧权重后覆盖
- API：`POST /api/training/specialists/inspect`、`POST /api/training/specialists/import`（见 [api.md](api.md)）

也可手工放置目录后写 `specialist.json`，或调用 `visionai.config.specialists.deploy_specialist(..., origin="imported")`。

---

## 训练专模部署

1. 在 Web **训练实验室**（`/training`）选择场景模板或自定义项目，完成标注与训练  
2. 测试集通过质量门禁后，点击「一键部署」：部署到 `models/specialists/<key>/`，写入 `specialist.json`，**插件热加载**，一般无需重启  
3. 在管理平台「检测类型配置」中为各视频流勾选对应专模键名  

内置部署目标（旧 `make_call` → `models/make_call.onnx`）已移除；请一律走专模路径。

专模 `kind`：

- `scene`：全画面场景检测（可选 `class_ids`）
- `person_event`：人物关联事件（`positive_class_ids`）
- `violation`：合规/违规双类（`subject_class_ids` 违规，`comply_class_ids` 合规）

场景模板示例：吸烟、安全帽、未戴眼镜、自定义等（以训练实验室左侧列表为准）。

---

## 模型目录

- `models/`：YOLO 主模型、姿态模型、人脸识别 buffalo_l 等  
- `models/specialists/<key>/`：专模（自训或导入；`model.pt` / `model.onnx` + `specialist.json`；`origin` 为 `trained` / `imported`）

详见 [快速开始 - 准备模型（YOLO26）](getting-started.md#4-准备模型yolo26)。权重不入 Git，部署时自行下载或从训练管线导出。

训练与导出见 **`training_system/README.md`** 与 Web **训练实验室**（`/training`）：

- 默认预训练：**YOLO26s**（`models/yolo26s.pt`）
- 开训门槛：已审核 ≥50 张、每类 ≥30 框、独立 val/test ≥10
- 预标注写入草稿，须审核后才训练
- 部署门禁：测试集 mAP@0.5≥0.40 且 P/R≥0.35
- 安全帽 / 眼镜等 violation 模板：类别顺序须与模板一致（如 `0=no_helmet, 1=helmet`）

人脸识别：SCRFD 检测 + ArcFace 特征，库在 Redis，照片在 MinIO；操作见 [user-guide.md](user-guide.md)。

---

## 车牌识别（OCR + 车牌库）

与专模 `plate`（仅 blue/green/yellow 颜色类）不同，内置扩展 **`plate_recognition`** 流程为：

1. 用 `models/specialists/plate/` 检出车牌框  
2. RapidOCR 读号并规范化（去空格、大写、I/O 易混修正）  
3. 查询 Redis 车牌库 → 按流配置触发 **库内（known）/ 陌生（unknown）** 告警  

画框标签显示读到的号码（如 `浙F351TK`）。若同时勾选专模 `plate` 与 `plate_recognition`，运行时**只跑车牌识别**，避免重复告警。

依赖：`rapidocr_onnxruntime`（见 `requirements.txt`）。操作见 [user-guide.md](user-guide.md#车牌识别)。
