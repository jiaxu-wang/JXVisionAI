#!/usr/bin/env python3
"""模型导出和部署脚本"""
import argparse
import shutil
from pathlib import Path
from ultralytics import YOLO


def export_model(model_path, format='onnx', imgsz=640, simplify=True, device='0'):
    """导出模型为指定格式"""
    print(f"=== 导出模型: {model_path} ===")
    print(f"目标格式: {format}")
    
    # 加载模型
    model = YOLO(model_path)
    
    # 导出模型
    exported_path = model.export(
        format=format,
        imgsz=imgsz,
        simplify=simplify,
        device=device,
        dynamic=False,
        opset=12,
        workspace=4
    )
    
    print(f"模型已导出到: {exported_path}")
    return exported_path


def deploy_model(model_path, target_dir, model_name=None):
    """部署模型到目标目录"""
    print(f"=== 部署模型 ===")
    
    source_path = Path(model_path)
    if not source_path.exists():
        raise FileNotFoundError(f"模型文件不存在: {model_path}")
    
    target_path = Path(target_dir)
    target_path.mkdir(parents=True, exist_ok=True)
    
    # 确定目标文件名
    if model_name:
        dest_file = target_path / model_name
    else:
        dest_file = target_path / source_path.name
    
    # 复制模型文件
    shutil.copy2(source_path, dest_file)
    
    print(f"模型已部署到: {dest_file}")
    
    # 同时复制类别信息
    model = YOLO(model_path)
    class_names = model.names
    class_file = target_path / f"{dest_file.stem}_classes.txt"
    
    with open(class_file, 'w', encoding='utf-8') as f:
        for idx, name in class_names.items():
            f.write(f"{idx}: {name}\n")
    
    print(f"类别信息已保存到: {class_file}")
    return str(dest_file)


def check_model_classes(model_path):
    """检查模型支持的类别"""
    print(f"=== 检查模型类别 ===")
    
    model = YOLO(model_path)
    classes = model.names
    
    print(f"模型类别数量: {len(classes)}")
    print("支持的类别:")
    for idx, name in classes.items():
        print(f"  {idx}: {name}")
    
    return classes


def main():
    parser = argparse.ArgumentParser(description='模型导出和部署脚本')
    
    subparsers = parser.add_subparsers(title='子命令', dest='command')
    
    # 导出命令
    export_parser = subparsers.add_parser('export', help='导出模型')
    export_parser.add_argument('--model', type=str, required=True, help='模型路径')
    export_parser.add_argument('--format', type=str, default='onnx', 
                            choices=['onnx', 'torchscript', 'engine', 'coreml', 'saved_model', 
                                     'pb', 'tflite', 'edgetpu', 'tfjs', 'paddle'],
                            help='导出格式')
    export_parser.add_argument('--imgsz', type=int, default=640, help='输入图像大小')
    export_parser.add_argument('--simplify', action='store_true', default=True, help='简化模型')
    export_parser.add_argument('--device', type=str, default='0', help='设备 (0=GPU, cpu=CPU)')
    
    # 部署命令
    deploy_parser = subparsers.add_parser('deploy', help='部署模型')
    deploy_parser.add_argument('--model', type=str, required=True, help='模型路径')
    deploy_parser.add_argument('--target_dir', type=str, required=True, help='目标目录')
    deploy_parser.add_argument('--model_name', type=str, help='目标模型文件名')
    
    # 检查类别命令
    check_parser = subparsers.add_parser('check', help='检查模型类别')
    check_parser.add_argument('--model', type=str, required=True, help='模型路径')
    
    args = parser.parse_args()
    
    if args.command == 'export':
        export_model(args.model, args.format, args.imgsz, args.simplify, args.device)
    elif args.command == 'deploy':
        deploy_model(args.model, args.target_dir, args.model_name)
    elif args.command == 'check':
        check_model_classes(args.model)


if __name__ == '__main__':
    main()
