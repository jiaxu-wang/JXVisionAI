# YOLO模型训练系统（legacy CLI）

> **推荐路径**：生产环境请优先使用 Web **训练实验室**（管理端 `/training`）——采图、标注、门禁、一键部署专模到 `models/specialists/<key>/` 并自动注册检测类型。  
> 本目录为 **离线 CLI** 工具链，适合批量脚本、本地实验或与训练实验室并行使用。

完整的YOLO模型训练、验证和部署系统，支持从数据准备到模型部署的完整流程。

## 目录结构

```
training_system/
├── data/                    # 数据目录
│   ├── raw/                 # 原始数据（图像+标注）
│   ├── processed/           # 处理后的数据
│   ├── images/              # 图像数据集
│   │   ├── train/           # 训练集图像
│   │   ├── val/             # 验证集图像
│   │   └── test/            # 测试集图像
│   └── labels/              # 标注文件
│       ├── train/           # 训练集标注
│       ├── val/             # 验证集标注
│       └── test/             # 测试集标注
├── scripts/                 # 脚本目录
│   ├── prepare_data.py      # 数据准备脚本
│   ├── train.py             # 模型训练脚本
│   ├── evaluate.py          # 模型验证和评估脚本
│   └── export.py            # 模型导出和部署脚本
├── configs/                 # 配置文件目录
│   └── smoking_detection.yaml # 吸烟检测配置示例
├── models/                  # 模型目录
├── outputs/                 # 训练输出目录
└── README.md                # 本文档
```

## 快速开始

### 1. 环境准备

确保已安装所需依赖：
```bash
cd /home/wjx/code/python/JXVisionAI
source env/bin/activate
pip install ultralytics opencv-python numpy pyyaml
```

### 2. 数据准备

将标注好的图像和YOLO格式的标注文件放入 `data/raw/` 目录：

```
data/raw/
├── image1.jpg
├── image1.txt
├── image2.jpg
├── image2.txt
└── ...
```

YOLO标注格式：
```
class_id x_center y_center width height
```
坐标为归一化值（0-1之间）

### 3. 数据预处理和划分

```bash
cd training_system
python scripts/prepare_data.py \
    --raw_dir data/raw \
    --preprocess \
    --augment \
    --target_size 640 \
    --train_ratio 0.7 \
    --val_ratio 0.2
```

### 4. 创建数据配置文件

在 `configs/` 目录创建 `data.yaml` 文件：

```yaml
path: /home/wjx/code/python/JXVisionAI/training_system/data
train: images/train
val: images/val
test: images/test

names:
  0: person
  1: smoking
  2: cigarette
```

### 5. 开始训练

```bash
python scripts/train.py \
    --data_yaml configs/data.yaml \
    --pretrained_model ../models/yolo26s.pt \
    --epochs 100 \
    --batch_size 16 \
    --img_size 640 \
    --device 0 \
    --experiment_name smoking_detection \
    --cos_lr
```

### 6. 评估模型

```bash
# 在验证集上评估
python scripts/evaluate.py eval \
    --model outputs/smoking_detection/weights/best.pt \
    --data configs/data.yaml \
    --conf 0.25 \
    --iou 0.45

# 在单张图像上测试
python scripts/evaluate.py test_img \
    --model outputs/smoking_detection/weights/best.pt \
    --image test_image.jpg \
    --conf 0.25 \
    --output result.jpg
```

### 7. 导出和部署模型

```bash
# 检查模型类别
python scripts/export.py check \
    --model outputs/smoking_detection/weights/best.pt

# 导出为ONNX格式
python scripts/export.py export \
    --model outputs/smoking_detection/weights/best.pt \
    --format onnx \
    --imgsz 640

# 仅复制权重文件到项目根（不注册检测类型）
python scripts/export.py deploy \
    --model outputs/smoking_detection/weights/best.pt \
    --target_dir ../ \
    --model_name smoking_detection.pt
```

### 8. 在 JXVisionAI 中使用新模型

**生产环境（推荐）**：

1. Web **训练实验室**（`/training`）标注、训练与 **一键部署**；或  
2. 同一页左侧 **导入现成专模**：上传社区/平台 YOLO `.pt`，登记 `key`/`kind` 后上线  

产物均写入 `models/specialists/<key>/`（`model.pt` + `specialist.json`），检测类型自动出现在 **检测配置** 列表，**热加载、一般无需重启**。说明见 `docs/detection.md`。

**CLI `export.py deploy`**：仅将 `.pt` 复制到指定目录，**不会** 写入 `specialist.json`，也**不会** 注册为检测类型。若要用 CLI 训练的权重上线，请用训练实验室「导入现成专模」、或手动整理专模目录，或导入训练实验室项目后再点部署。

打电话能力已下线；需要时在训练实验室自训或导入 YOLO 专模。其余场景（吸烟、安全帽、未戴眼镜、自定义等）均部署为 **专模**，不在 `config.ini` 中为每项单独配路径。

## 详细使用说明

### 数据准备脚本 (prepare_data.py)

**功能**：
- 图像预处理（调整大小）
- 数据增强（翻转、亮度调整、旋转）
- 数据集划分（训练集、验证集、测试集）

**参数说明**：
- `--raw_dir`: 原始数据目录（默认：data/raw）
- `--preprocess`: 是否预处理图像
- `--augment`: 是否数据增强（仅训练集）
- `--target_size`: 目标图像大小（默认：640）
- `--train_ratio`: 训练集比例（默认：0.7）
- `--val_ratio`: 验证集比例（默认：0.2）

**使用示例**：
```bash
# 基本使用
python scripts/prepare_data.py

# 完整参数
python scripts/prepare_data.py \
    --raw_dir data/raw \
    --preprocess \
    --augment \
    --target_size 640 \
    --train_ratio 0.7 \
    --val_ratio 0.2
```

### 模型训练脚本 (train.py)

**功能**：
- 从预训练模型开始训练
- 支持多种训练参数配置
- 自动保存最佳模型和最后模型
- 生成训练曲线图

**参数说明**：
- `--data_yaml`: 数据配置文件路径（必需）
- `--pretrained_model`: 预训练模型路径（默认：`../models/yolo26s.pt` 或 `yolo26s.pt`）
- `--epochs`: 训练轮数（默认：100）
- `--batch_size`: 批次大小（默认：16）
- `--img_size`: 输入图像大小（默认：640）
- `--device`: 训练设备（0=GPU, cpu=CPU，默认：0）
- `--workers`: 数据加载工作进程数（默认：8）
- `--project_dir`: 项目输出目录（默认：outputs）
- `--experiment_name`: 实验名称（默认：train）
- `--optimizer`: 优化器（auto, SGD, Adam, Adamax，默认：auto）
- `--lr0`: 初始学习率（默认：0.01）
- `--cos_lr`: 使用余弦学习率调度
- `--resume`: 恢复训练

**使用示例**：
```bash
# 基本训练
python scripts/train.py --data_yaml configs/data.yaml

# 完整参数
python scripts/train.py \
    --data_yaml configs/data.yaml \
    --pretrained_model ../models/yolo26s.pt \
    --epochs 200 \
    --batch_size 32 \
    --img_size 640 \
    --device 0 \
    --workers 16 \
    --project_dir outputs \
    --experiment_name custom_detection \
    --optimizer Adam \
    --lr0 0.001 \
    --cos_lr
```

### 模型验证和评估脚本 (evaluate.py)

**功能**：
- 在验证集上评估模型性能
- 在单张图像上测试模型
- 在视频上测试模型
- 批量测试图像

**子命令**：

1. **eval** - 评估模型性能
   ```bash
   python scripts/evaluate.py eval \
       --model path/to/model.pt \
       --data configs/data.yaml \
       --conf 0.25 \
       --iou 0.45 \
       --device 0
   ```

2. **test_img** - 测试单张图像
   ```bash
   python scripts/evaluate.py test_img \
       --model path/to/model.pt \
       --image test.jpg \
       --conf 0.25 \
       --output result.jpg
   ```

3. **test_video** - 测试视频
   ```bash
   python scripts/evaluate.py test_video \
       --model path/to/model.pt \
       --video test.mp4 \
       --conf 0.25 \
       --output output.mp4
   ```

4. **batch** - 批量测试图像
   ```bash
   python scripts/evaluate.py batch \
       --model path/to/model.pt \
       --dir test_images/ \
       --conf 0.25 \
       --output_dir results/
   ```

### 模型导出和部署脚本 (export.py)

**功能**：
- 导出模型为多种格式
- 部署模型到指定目录
- 检查模型支持的类别

**子命令**：

1. **check** - 检查模型类别
   ```bash
   python scripts/export.py check --model path/to/model.pt
   ```

2. **export** - 导出模型
   ```bash
   python scripts/export.py export \
       --model path/to/model.pt \
       --format onnx \
       --imgsz 640 \
       --simplify \
       --device 0
   ```

   支持的格式：onnx, torchscript, engine, coreml, saved_model, pb, tflite, edgetpu, tfjs, paddle

3. **deploy** - 部署模型
   ```bash
   python scripts/export.py deploy \
       --model path/to/model.pt \
       --target_dir ../ \
       --model_name custom_model.pt
   ```

## 配置文件示例

参见 `configs/smoking_detection.yaml` 作为参考配置。

## 最佳实践

### 数据准备
1. 确保数据质量：标注准确、图像清晰
2. 数据多样性：涵盖不同场景、光照、角度
3. 数据量：至少1000张标注图像
4. 正负样本平衡：确保各类别样本数量均衡

### 训练策略
1. 从预训练模型开始：使用 `models/yolo26s.pt`（YOLO26）
2. 学习率调整：从较小的学习率开始（0.001-0.01）
3. 批次大小：根据GPU内存调整（16-64）
4. 训练轮数：100-300轮，观察验证集指标

### 模型选择
- **yolo26n.pt**：最轻量，速度最快
- **yolo26s.pt**：默认推荐，速度与精度平衡
- **yolo26m.pt**：更大模型，准确率更高，需要更多算力

## 常见问题

### Q: 训练时出现CUDA内存不足怎么办？
A: 减小batch_size或img_size，或使用CPU训练（--device cpu）

### Q: 如何判断模型训练完成？
A: 观察验证集mAP指标，当连续多个epoch不再提升时可以停止训练

### Q: 模型准确率不够高怎么办？
A: 
1. 增加训练数据量
2. 改进标注质量
3. 使用更大的模型（yolo26m）
4. 调整超参数（学习率、批次大小等）
5. 进行数据增强

### Q: 如何将训练好的模型集成到JXVisionAI？
A: 
1. **推荐**：在 Web 训练实验室导入数据或关联项目 → 训练 → **一键部署为专模**
2. CLI 路径：`export.py deploy` 仅复制文件；须再通过训练实验室部署或手动维护 `models/specialists/<key>/`
3. 仅 `make_call` 使用内置 deploy（改 `config.ini` + 重启）

## 技术支持

如有问题，请检查：
1. 环境是否正确激活（source env/bin/activate）
2. 依赖是否完整安装
3. 数据格式是否正确
4. 配置文件路径是否正确
