#!/usr/bin/env python3
"""
自动标注脚本
使用预训练模型为抽烟图片生成标注文件
"""
import os
import argparse
from ultralytics import YOLO
from pathlib import Path


def auto_label_images(image_dir, output_dir, model_path='yolov8n.pt', confidence_threshold=0.5):
    """自动为图片生成标注文件"""
    # 加载预训练模型
    print(f"加载模型: {model_path}")
    model = YOLO(model_path)
    
    # 确保输出目录存在
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # 遍历图片文件
    image_files = [f for f in os.listdir(image_dir) if f.endswith(('.jpg', '.jpeg', '.png'))]
    print(f"找到 {len(image_files)} 张图片")
    
    for image_file in image_files:
        image_path = os.path.join(image_dir, image_file)
        print(f"处理图片: {image_file}")
        
        # 进行预测
        results = model(image_path)
        
        # 生成标注文件
        label_file = os.path.join(output_dir, f"{os.path.splitext(image_file)[0]}.txt")
        
        with open(label_file, 'w') as f:
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    class_id = int(box.cls[0])
                    confidence = float(box.conf[0])
                    
                    # 只保存高置信度的检测结果
                    if confidence >= confidence_threshold:
                        # 获取类别名称
                        class_name = model.names[class_id]
                        
                        # 转换为YOLO格式 (class_id x_center y_center width height)
                        # 坐标需要归一化到0-1范围
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        image_width = result.orig_shape[1]
                        image_height = result.orig_shape[0]
                        
                        x_center = (x1 + x2) / 2 / image_width
                        y_center = (y1 + y2) / 2 / image_height
                        width = (x2 - x1) / image_width
                        height = (y2 - y1) / image_height
                        
                        # 根据类别名称映射到我们的类别ID
                        # 0: person, 1: smoking, 2: cigarette
                        if class_name == 'person':
                            our_class_id = 0
                        elif class_name in ['cell phone', 'remote', 'bottle']:  # 可能是香烟的误识别
                            our_class_id = 2  # 暂时标记为香烟
                        else:
                            continue  # 跳过其他类别
                        
                        # 写入标注文件
                        f.write(f"{our_class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}\n")
        
        print(f"标注文件已生成: {label_file}")
    
    print("\n自动标注完成！")


def main():
    parser = argparse.ArgumentParser(description='自动标注脚本')
    parser.add_argument('--image_dir', type=str, default='data/raw', help='图片目录')
    parser.add_argument('--output_dir', type=str, default='data/raw', help='标注文件输出目录')
    parser.add_argument('--model', type=str, default='yolov8n.pt', help='预训练模型路径')
    parser.add_argument('--conf', type=float, default=0.5, help='置信度阈值')
    
    args = parser.parse_args()
    
    auto_label_images(args.image_dir, args.output_dir, args.model, args.conf)


if __name__ == '__main__':
    main()
