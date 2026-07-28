#!/usr/bin/env python3
"""YOLO模型训练脚本"""
import os
import argparse
from pathlib import Path
from ultralytics import YOLO


def create_data_yaml(data_dir, class_names, output_dir):
    """创建数据配置文件"""
    data_yaml_content = f"""path: {data_dir}
train: images/train
val: images/val
test: images/test

names:
"""
    for idx, name in enumerate(class_names):
        data_yaml_content += f"  {idx}: {name}\n"
    
    data_yaml_path = Path(output_dir) / 'data.yaml'
    with open(data_yaml_path, 'w', encoding='utf-8') as f:
        f.write(data_yaml_content)
    
    return str(data_yaml_path)


def train_model(config):
    """训练YOLO模型"""
    # 加载预训练模型
    model = YOLO(config['pretrained_model'])
    
    # 设置训练参数
    train_args = {
        'data': config['data_yaml'],
        'epochs': config['epochs'],
        'batch': config['batch_size'],
        'imgsz': config['img_size'],
        'device': config['device'],
        'workers': config['workers'],
        'project': config['project_dir'],
        'name': config['experiment_name'],
        'exist_ok': True,
        'pretrained': True,
        'optimizer': config.get('optimizer', 'auto'),
        'lr0': config.get('lr0', 0.01),
        'lrf': config.get('lrf', 0.01),
        'momentum': config.get('momentum', 0.937),
        'weight_decay': config.get('weight_decay', 0.0005),
        'warmup_epochs': config.get('warmup_epochs', 3.0),
        'warmup_momentum': config.get('warmup_momentum', 0.8),
        'warmup_bias_lr': config.get('warmup_bias_lr', 0.1),
        'box': config.get('box', 7.5),
        'cls': config.get('cls', 0.5),
        'dfl': config.get('dfl', 1.5),
        'pose': config.get('pose', 12.0),
        'kobj': config.get('kobj', 1.0),
        'label_smoothing': config.get('label_smoothing', 0.0),
        'nbs': config.get('nbs', 64),
        'overlap_mask': config.get('overlap_mask', True),
        'mask_ratio': config.get('mask_ratio', 4),
        'dropout': config.get('dropout', 0.0),
        'val': config.get('val', True),
        'plots': config.get('plots', True),
        'save': config.get('save', True),
        'save_period': config.get('save_period', -1),
        'cache': config.get('cache', False),
        'seed': config.get('seed', 0),
        'deterministic': config.get('deterministic', True),
        'single_cls': config.get('single_cls', False),
        'rect': config.get('rect', False),
        'cos_lr': config.get('cos_lr', False),
        'close_mosaic': config.get('close_mosaic', 10),
        'resume': config.get('resume', False),
        'amp': config.get('amp', True),
        'fraction': config.get('fraction', 1.0),
        'profile': config.get('profile', False),
        'freeze': config.get('freeze', None),
        'multi_scale': config.get('multi_scale', False),
    }
    
    print("=== 开始训练 ===")
    print(f"训练参数: {train_args}")
    
    # 开始训练
    results = model.train(**train_args)
    
    print("=== 训练完成 ===")
    return results


def main():
    parser = argparse.ArgumentParser(description='YOLO模型训练脚本')
    parser.add_argument('--data_yaml', type=str, required=True, help='数据配置文件路径')
    parser.add_argument('--pretrained_model', type=str, default='yolo26s.pt', help='预训练模型路径')
    parser.add_argument('--epochs', type=int, default=100, help='训练轮数')
    parser.add_argument('--batch_size', type=int, default=16, help='批次大小')
    parser.add_argument('--img_size', type=int, default=640, help='输入图像大小')
    parser.add_argument('--device', type=str, default='cpu', help='训练设备 (0=GPU, cpu=CPU)')
    parser.add_argument('--workers', type=int, default=8, help='数据加载工作进程数')
    parser.add_argument('--project_dir', type=str, default='outputs', help='项目输出目录')
    parser.add_argument('--experiment_name', type=str, default='train', help='实验名称')
    parser.add_argument('--optimizer', type=str, default='auto', help='优化器 (SGD, Adam, Adamax, auto)')
    parser.add_argument('--lr0', type=float, default=0.01, help='初始学习率')
    parser.add_argument('--cos_lr', action='store_true', help='使用余弦学习率调度')
    parser.add_argument('--resume', action='store_true', help='恢复训练')
    
    args = parser.parse_args()
    
    config = {
        'data_yaml': args.data_yaml,
        'pretrained_model': args.pretrained_model,
        'epochs': args.epochs,
        'batch_size': args.batch_size,
        'img_size': args.img_size,
        'device': args.device,
        'workers': args.workers,
        'project_dir': args.project_dir,
        'experiment_name': args.experiment_name,
        'optimizer': args.optimizer,
        'lr0': args.lr0,
        'cos_lr': args.cos_lr,
        'resume': args.resume,
    }
    
    # 确保输出目录存在
    Path(config['project_dir']).mkdir(parents=True, exist_ok=True)
    
    # 开始训练
    train_model(config)


if __name__ == '__main__':
    main()
