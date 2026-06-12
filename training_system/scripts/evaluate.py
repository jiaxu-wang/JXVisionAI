#!/usr/bin/env python3
"""模型验证和评估脚本"""
import argparse
import json
from pathlib import Path
from ultralytics import YOLO
import cv2
import numpy as np


def evaluate_model(model_path, data_yaml, conf_threshold=0.25, iou_threshold=0.45, device='0'):
    """评估模型性能"""
    print("=== 开始模型评估 ===")
    print(f"模型路径: {model_path}")
    print(f"数据配置: {data_yaml}")
    print(f"置信度阈值: {conf_threshold}")
    print(f"IoU阈值: {iou_threshold}")
    
    # 加载模型
    model = YOLO(model_path)
    
    # 验证模型
    results = model.val(
        data=data_yaml,
        conf=conf_threshold,
        iou=iou_threshold,
        device=device,
        split='val',
        verbose=True
    )
    
    print("\n=== 评估结果 ===")
    print(f"mAP@0.5: {results.box.map50:.4f}")
    print(f"mAP@0.5:0.95: {results.box.map:.4f}")
    print(f"精确率 (Precision): {results.box.mp:.4f}")
    print(f"召回率 (Recall): {results.box.mr:.4f}")

    metrics = {
        "map50": float(results.box.map50),
        "map50_95": float(results.box.map),
        "precision": float(results.box.mp),
        "recall": float(results.box.mr),
    }
    return results, metrics


def test_on_image(model_path, image_path, conf_threshold=0.25, output_path=None):
    """在单张图像上测试模型"""
    print(f"=== 在图像 {image_path} 上测试 ===")
    
    model = YOLO(model_path)
    
    # 进行预测
    results = model.predict(
        source=image_path,
        conf=conf_threshold,
        save=False
    )
    
    # 绘制检测结果
    annotated_frame = results[0].plot()
    
    if output_path:
        cv2.imwrite(output_path, annotated_frame)
        print(f"检测结果已保存到: {output_path}")
    else:
        print("检测结果:")
        for box in results[0].boxes:
            cls = int(box.cls[0])
            conf = float(box.conf[0])
            label = model.names[cls]
            print(f"  - {label}: 置信度={conf:.4f}")
    
    return results


def test_on_video(model_path, video_path, conf_threshold=0.25, output_path=None):
    """在视频上测试模型"""
    print(f"=== 在视频 {video_path} 上测试 ===")
    
    model = YOLO(model_path)
    
    # 进行视频预测
    results = model.predict(
        source=video_path,
        conf=conf_threshold,
        save=output_path is not None,
        project=str(Path(output_path).parent) if output_path else None,
        name=Path(output_path).stem if output_path else None
    )
    
    print("视频测试完成")
    return results


def batch_test(model_path, test_dir, conf_threshold=0.25, output_dir=None):
    """批量测试图像"""
    print(f"=== 批量测试目录: {test_dir} ===")
    
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    model = YOLO(model_path)
    
    image_files = list(Path(test_dir).glob('*.jpg')) + list(Path(test_dir).glob('*.png'))
    
    for img_file in image_files:
        print(f"处理: {img_file.name}")
        output_path = str(Path(output_dir) / img_file.name) if output_dir else None
        test_on_image(model_path, str(img_file), conf_threshold, output_path)


def main():
    parser = argparse.ArgumentParser(description='模型验证和评估脚本')
    
    subparsers = parser.add_subparsers(title='子命令', dest='command')
    
    # 评估命令
    eval_parser = subparsers.add_parser('eval', help='评估模型性能')
    eval_parser.add_argument('--model', type=str, required=True, help='模型路径')
    eval_parser.add_argument('--data', type=str, required=True, help='数据配置文件')
    eval_parser.add_argument('--conf', type=float, default=0.25, help='置信度阈值')
    eval_parser.add_argument('--iou', type=float, default=0.45, help='IoU阈值')
    eval_parser.add_argument('--device', type=str, default='0', help='设备 (0=cpu, cpu=cpu)')
    eval_parser.add_argument('--json-out', type=str, default='', help='将指标写入 JSON 文件')
    
    # 测试图像命令
    test_img_parser = subparsers.add_parser('test_img', help='测试单张图像')
    test_img_parser.add_argument('--model', type=str, required=True, help='模型路径')
    test_img_parser.add_argument('--image', type=str, required=True, help='图像路径')
    test_img_parser.add_argument('--conf', type=float, default=0.25, help='置信度阈值')
    test_img_parser.add_argument('--output', type=str, help='输出图像路径')
    
    # 测试视频命令
    test_video_parser = subparsers.add_parser('test_video', help='测试视频')
    test_video_parser.add_argument('--model', type=str, required=True, help='模型路径')
    test_video_parser.add_argument('--video', type=str, required=True, help='视频路径')
    test_video_parser.add_argument('--conf', type=float, default=0.25, help='置信度阈值')
    test_video_parser.add_argument('--output', type=str, help='输出视频路径')
    
    # 批量测试命令
    batch_parser = subparsers.add_parser('batch', help='批量测试图像')
    batch_parser.add_argument('--model', type=str, required=True, help='模型路径')
    batch_parser.add_argument('--dir', type=str, required=True, help='图像目录')
    batch_parser.add_argument('--conf', type=float, default=0.25, help='置信度阈值')
    batch_parser.add_argument('--output_dir', type=str, help='输出目录')
    
    args = parser.parse_args()
    
    if args.command == 'eval':
        _results, metrics = evaluate_model(args.model, args.data, args.conf, args.iou, args.device)
        if args.json_out:
            out = Path(args.json_out)
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, 'w', encoding='utf-8') as f:
                json.dump(metrics, f, ensure_ascii=False, indent=2)
            print(f"指标已写入: {out}")
    elif args.command == 'test_img':
        test_on_image(args.model, args.image, args.conf, args.output)
    elif args.command == 'test_video':
        test_on_video(args.model, args.video, args.conf, args.output)
    elif args.command == 'batch':
        batch_test(args.model, args.dir, args.conf, args.output_dir)


if __name__ == '__main__':
    main()
