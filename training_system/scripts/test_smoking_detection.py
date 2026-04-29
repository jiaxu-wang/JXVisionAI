#!/usr/bin/env python3
"""
抽烟检测模型测试脚本
用于测试训练好的模型是否能够正确识别图片中的抽烟行为
"""
import os
import argparse
from ultralytics import YOLO
import cv2
from pathlib import Path


def test_smoking_detection(model_path, image_path, output_path=None, conf_threshold=0.2):
    """测试抽烟检测模型"""
    # 加载模型
    print(f"加载模型: {model_path}")
    model = YOLO(model_path)
    
    # 读取图片
    print(f"读取图片: {image_path}")
    image = cv2.imread(image_path)
    if image is None:
        print(f"错误: 无法读取图片 {image_path}")
        return False
    
    # 进行预测
    print(f"进行预测 (置信度阈值: {conf_threshold})...")
    results = model(image, conf=conf_threshold)
    
    # 分析结果
    smoking_detected = False
    cigarette_detected = False
    person_detected = False
    
    print("\n详细检测结果:")
    for result in results:
        boxes = result.boxes
        print(f"检测到 {len(boxes)} 个目标")
        for i, box in enumerate(boxes):
            class_id = int(box.cls[0])
            confidence = float(box.conf[0])
            
            # 获取类别名称
            class_name = model.names[class_id]
            
            print(f"目标 {i+1}: {class_name} (置信度: {confidence:.4f})")
            
            # 检查是否检测到相关类别
            if class_name == 'smoking':
                smoking_detected = True
            elif class_name == 'cigarette':
                cigarette_detected = True
            elif class_name == 'person':
                person_detected = True
    
    # 输出检测结果
    print("\n=== 检测结果 ===")
    print(f"是否检测到人物: {'是' if person_detected else '否'}")
    print(f"是否检测到抽烟行为: {'是' if smoking_detected else '否'}")
    print(f"是否检测到香烟: {'是' if cigarette_detected else '否'}")
    
    # 判断是否在抽烟
    if smoking_detected or (person_detected and cigarette_detected):
        print("\n结论: 图片中的人物正在抽烟")
        smoking = True
    else:
        print("\n结论: 图片中的人物没有在抽烟")
        smoking = False
    
    # 可视化结果（如果需要）
    if output_path:
        print(f"\n保存检测结果到: {output_path}")
        # 生成带标注的图像
        annotated_image = results[0].plot()
        # 保存图像
        cv2.imwrite(output_path, annotated_image)
        print("检测结果已保存")
    
    return smoking


def main():
    parser = argparse.ArgumentParser(description='抽烟检测模型测试脚本')
    parser.add_argument('--model', type=str, 
                        default='runs/detect/outputs/smoking_detection/weights/best.pt',
                        help='模型路径')
    parser.add_argument('--image', type=str, 
                        default='test_result.jpg',
                        help='测试图片路径')
    parser.add_argument('--output', type=str, 
                        default='smoking_detection_result.jpg',
                        help='输出结果图片路径')
    parser.add_argument('--conf', type=float, 
                        default=0.2, 
                        help='置信度阈值')
    
    args = parser.parse_args()
    
    # 测试模型
    test_smoking_detection(args.model, args.image, args.output, args.conf)


if __name__ == '__main__':
    main()
