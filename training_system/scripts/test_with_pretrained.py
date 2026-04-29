#!/usr/bin/env python3
"""
使用预训练模型测试抽烟检测
"""
import cv2
from ultralytics import YOLO


def test_with_pretrained(image_path):
    """使用预训练模型测试抽烟检测"""
    # 加载预训练的YOLOv8模型
    print("加载预训练模型...")
    model = YOLO('yolov8n.pt')  # 使用nano模型，速度快
    
    # 读取图片
    print(f"读取图片: {image_path}")
    image = cv2.imread(image_path)
    if image is None:
        print(f"错误: 无法读取图片 {image_path}")
        return
    
    # 进行预测
    print("进行预测...")
    results = model(image)
    
    # 分析结果
    print("\n检测结果:")
    for result in results:
        boxes = result.boxes
        for box in boxes:
            class_id = int(box.cls[0])
            confidence = float(box.conf[0])
            class_name = model.names[class_id]
            
            # 只显示高置信度的结果
            if confidence > 0.5:
                print(f"{class_name}: {confidence:.2f}")
    
    # 生成带标注的图像
    annotated_image = results[0].plot()
    output_path = 'pretrained_detection_result.jpg'
    cv2.imwrite(output_path, annotated_image)
    print(f"\n标注结果已保存到: {output_path}")


def main():
    image_path = 'data/raw/xiyandenanrentupian_13227680.jpg'
    test_with_pretrained(image_path)


if __name__ == '__main__':
    main()
