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
    """
    已禁用：翻转/旋转未同步变换 YOLO 标注，会污染训练集。
    请使用 Ultralytics 训练内置增强（train.py mosaic 等）。
    """
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


def remap_label_lines_smoking(src_label_path):
    """
    将 raw 标注转为单类 smoking(0)。
    原约定：0=person（丢弃），1=smoking，2=cigarette → 均映射为 0=smoking。
    """
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
                continue
            lines_out.append(f"0 {rest}")
    return lines_out


def remap_label_lines_legacy_person_cigarette(src_label_path):
    """旧版两类别 person(0)+cigarette(1)，仅用于 --remap-person-cigarette 兼容。"""
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


def remap_label_to_smoking(src_label_path, dst_label_path):
    """单类 smoking 映射；返回是否至少有一个框。"""
    lines_out = remap_label_lines_smoking(src_label_path)
    text = "\n".join(lines_out)
    if text:
        text += "\n"
    with open(dst_label_path, "w", encoding="utf-8") as f:
        f.write(text)
    return len(lines_out) > 0


def remap_label_person_cigarette(src_label_path, dst_label_path):
    """兼容旧参数：person+cigarette 两类别。"""
    lines_out = remap_label_lines_legacy_person_cigarette(src_label_path)
    text = "\n".join(lines_out)
    if text:
        text += "\n"
    with open(dst_label_path, "w", encoding="utf-8") as f:
        f.write(text)
    return len(lines_out) > 0


def list_trainable_images(raw_dir, remap_mode=None):
    """仅保留存在标注且标注有效的图像文件名。remap_mode: smoking | person_cigarette | None"""
    names = []
    for img_file in os.listdir(raw_dir):
        if not img_file.endswith(('.jpg', '.png', '.jpeg')):
            continue
        label_file = os.path.splitext(img_file)[0] + '.txt'
        src_label = os.path.join(raw_dir, label_file)
        if not os.path.exists(src_label) or os.path.getsize(src_label) == 0:
            continue
        if remap_mode == "smoking":
            if not remap_label_lines_smoking(src_label):
                continue
        elif remap_mode == "person_cigarette":
            if not remap_label_lines_legacy_person_cigarette(src_label):
                continue
        names.append(img_file)
    return names


def process_images(raw_dir, images_dir, labels_dir, config):
    """处理图像并复制到对应目录"""
    image_files = list_trainable_images(raw_dir, remap_mode=config.get('remap_mode'))
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
            remap_mode = config.get('remap_mode')
            if remap_mode == 'smoking':
                if not remap_label_to_smoking(src_label, dst_label):
                    continue
            elif remap_mode == 'person_cigarette':
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
                        print(
                            "警告: --augment 已禁用（不更新标注框）；"
                            "请依赖 Ultralytics 训练时内置增强。"
                        )
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
    parser.add_argument(
        '--augment',
        action='store_true',
        help='已禁用：请使用 Ultralytics 训练内置增强',
    )
    parser.add_argument('--target_size', type=int, default=640, help='目标图像大小')
    parser.add_argument('--train_ratio', type=float, default=0.7, help='训练集比例')
    parser.add_argument('--val_ratio', type=float, default=0.2, help='验证集比例')
    parser.add_argument(
        '--remap-to-smoking',
        action='store_true',
        help='将 raw 中 1=smoking / 2=cigarette 转为单类 smoking(0)，丢弃 person(0)',
    )
    parser.add_argument(
        '--remap-person-cigarette',
        action='store_true',
        help='（旧）转为 person(0)+cigarette(1)',
    )
    parser.add_argument(
        '--clean',
        action='store_true',
        help='清空 images/* 与 labels/* 下 train/val/test 中已有文件再划分',
    )
    
    args = parser.parse_args()
    
    remap_mode = None
    if args.remap_to_smoking:
        remap_mode = 'smoking'
    elif args.remap_person_cigarette:
        remap_mode = 'person_cigarette'

    config = {
        'preprocess': args.preprocess,
        'augment': False,
        'target_size': args.target_size,
        'train_ratio': args.train_ratio,
        'val_ratio': args.val_ratio,
        'remap_mode': remap_mode,
    }
    if args.augment:
        print("警告: --augment 已忽略，请使用 train.py 内置增强。")
    
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
