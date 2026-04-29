#!/usr/bin/env python3
"""数据准备脚本：图像预处理和数据集划分"""
import os
import shutil
import random
import argparse
from pathlib import Path
import cv2
import numpy as np


def resize_image(image, target_size=640):
    """调整图像大小，保持宽高比"""
    h, w = image.shape[:2]
    scale = target_size / max(h, w)
    new_w = int(w * scale)
    new_h = int(h * scale)
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return resized


def augment_image(image):
    """数据增强：随机翻转、亮度调整等"""
    # 随机水平翻转
    if random.random() > 0.5:
        image = cv2.flip(image, 1)
    
    # 随机亮度调整
    if random.random() > 0.5:
        alpha = random.uniform(0.8, 1.2)
        image = cv2.convertScaleAbs(image, alpha=alpha, beta=0)
    
    # 随机旋转（小角度）
    if random.random() > 0.7:
        h, w = image.shape[:2]
        center = (w // 2, h // 2)
        angle = random.uniform(-10, 10)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        image = cv2.warpAffine(image, M, (w, h))
    
    return image


def convert_bbox_to_yolo(bbox, img_width, img_height):
    """将边界框坐标转换为YOLO格式"""
    x_min, y_min, x_max, y_max = bbox
    x_center = (x_min + x_max) / 2 / img_width
    y_center = (y_min + y_max) / 2 / img_height
    width = (x_max - x_min) / img_width
    height = (y_max - y_min) / img_height
    return x_center, y_center, width, height


def split_dataset(image_files, train_ratio=0.7, val_ratio=0.2):
    """划分训练集、验证集和测试集"""
    image_files = list(image_files)
    random.shuffle(image_files)
    
    total = len(image_files)
    train_end = int(total * train_ratio)
    val_end = train_end + int(total * val_ratio)
    
    train_files = image_files[:train_end]
    val_files = image_files[train_end:val_end]
    test_files = image_files[val_end:]
    
    print(f"数据集划分: 训练集={len(train_files)}, 验证集={len(val_files)}, 测试集={len(test_files)}")
    
    return train_files, val_files, test_files


def remap_label_lines(src_label_path):
    """解析 raw 标注，返回两类别 YOLO 行列表（0=person，1=cigarette）。"""
    lines_out = []
    with open(src_label_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            cls = int(float(parts[0]))
            rest = " ".join(parts[1:])
            if cls == 0:
                lines_out.append(f"0 {rest}")
            elif cls == 1:
                continue
            elif cls == 2:
                lines_out.append(f"1 {rest}")
    return lines_out


def remap_label_person_cigarette(src_label_path, dst_label_path):
    """
    将旧版三类别标注转为两类别：0=person，1=cigarette。
    原约定：0=person，1=smoking（与人物框重复，丢弃），2=cigarette。
    返回写入后是否至少有一个检测框。
    """
    lines_out = remap_label_lines(src_label_path)
    text = "\n".join(lines_out)
    if text:
        text += "\n"
    with open(dst_label_path, "w", encoding="utf-8") as f:
        f.write(text)
    return len(lines_out) > 0


def list_trainable_images(raw_dir, remap_person_cigarette=False):
    """仅保留存在标注且标注有效的图像文件名。"""
    names = []
    for img_file in os.listdir(raw_dir):
        if not img_file.endswith(('.jpg', '.png', '.jpeg')):
            continue
        label_file = os.path.splitext(img_file)[0] + '.txt'
        src_label = os.path.join(raw_dir, label_file)
        if not os.path.exists(src_label) or os.path.getsize(src_label) == 0:
            continue
        if remap_person_cigarette:
            lines_out = remap_label_lines(src_label)
            if not lines_out:
                continue
        names.append(img_file)
    return names


def process_images(raw_dir, images_dir, labels_dir, config):
    """处理图像并复制到对应目录"""
    image_files = list_trainable_images(
        raw_dir,
        remap_person_cigarette=config.get('remap_person_cigarette', False),
    )
    if not image_files:
        print("错误: 没有可用的已标注图像，请检查 raw 目录中的 .jpg 与 .txt")
        return
    print(f"有效样本数: {len(image_files)}")
    train_files, val_files, test_files = split_dataset(
        image_files,
        train_ratio=config.get('train_ratio', 0.7),
        val_ratio=config.get('val_ratio', 0.2),
    )
    
    def copy_files(files, split):
        for img_file in files:
            src_img = os.path.join(raw_dir, img_file)
            label_file = os.path.splitext(img_file)[0] + '.txt'
            src_label = os.path.join(raw_dir, label_file)
            dst_img = os.path.join(images_dir, split, img_file)
            dst_label = os.path.join(labels_dir, split, label_file)

            if not os.path.exists(src_label):
                continue
            if config.get('remap_person_cigarette', False):
                if not remap_label_person_cigarette(src_label, dst_label):
                    continue
            else:
                shutil.copy2(src_label, dst_label)

            # 复制图像
            if config.get('preprocess', False):
                img = cv2.imread(src_img)
                if img is not None:
                    img = resize_image(img, config.get('target_size', 640))
                    if config.get('augment', False) and split == 'train':
                        img = augment_image(img)
                    cv2.imwrite(dst_img, img)
            else:
                shutil.copy2(src_img, dst_img)
    
    copy_files(train_files, 'train')
    copy_files(val_files, 'val')
    copy_files(test_files, 'test')


def main():
    parser = argparse.ArgumentParser(description='数据准备脚本')
    parser.add_argument('--config', type=str, default='configs/default.yaml', help='配置文件路径')
    parser.add_argument('--raw_dir', type=str, default='data/raw', help='原始数据目录')
    parser.add_argument('--preprocess', action='store_true', help='是否预处理图像')
    parser.add_argument('--augment', action='store_true', help='是否数据增强（仅训练集）')
    parser.add_argument('--target_size', type=int, default=640, help='目标图像大小')
    parser.add_argument('--train_ratio', type=float, default=0.7, help='训练集比例')
    parser.add_argument('--val_ratio', type=float, default=0.2, help='验证集比例')
    parser.add_argument(
        '--remap-person-cigarette',
        action='store_true',
        help='将 raw 中 0/1/2 类标注转为 person(0)+cigarette(1)，并跳过无有效框的样本',
    )
    parser.add_argument(
        '--clean',
        action='store_true',
        help='清空 images/* 与 labels/* 下 train/val/test 中已有文件再划分',
    )
    
    args = parser.parse_args()
    
    config = {
        'preprocess': args.preprocess,
        'augment': args.augment,
        'target_size': args.target_size,
        'train_ratio': args.train_ratio,
        'val_ratio': args.val_ratio,
        'remap_person_cigarette': args.remap_person_cigarette,
    }
    
    base_dir = Path(__file__).parent.parent
    raw_dir = base_dir / args.raw_dir
    images_dir = base_dir / 'data' / 'images'
    labels_dir = base_dir / 'data' / 'labels'
    
    # 确保目录存在
    for split in ['train', 'val', 'test']:
        (images_dir / split).mkdir(parents=True, exist_ok=True)
        (labels_dir / split).mkdir(parents=True, exist_ok=True)
        if args.clean:
            for folder in (images_dir / split, labels_dir / split):
                for p in folder.iterdir():
                    p.unlink()
    
    print("=== 开始数据准备 ===")
    process_images(str(raw_dir), str(images_dir), str(labels_dir), config)
    print("=== 数据准备完成 ===")


if __name__ == '__main__':
    main()
