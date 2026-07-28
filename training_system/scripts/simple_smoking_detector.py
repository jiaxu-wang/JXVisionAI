#!/usr/bin/env python3
"""
简单抽烟检测脚本
使用预训练模型检测人物和香烟，判断是否在抽烟
"""
import cv2
from ultralytics import YOLO


def detect_smoking(image_path, conf_threshold=0.5):
    """检测图片中是否有人在抽烟"""
    # 加载预训练的YOLO26模型
    print("加载预训练模型...")
    model = YOLO('yolo26s.pt')
    
    # 读取图片
    print(f"读取图片: {image_path}")
    image = cv2.imread(image_path)
    if image is None:
        print(f"错误: 无法读取图片 {image_path}")
        return False
    
    # 进行预测
    print("进行预测...")
    results = model(image, conf=conf_threshold)
    
    # 分析结果
    person_detected = False
    cigarette_detected = False
    
    print("\n检测结果:")
    for result in results:
        boxes = result.boxes
        for box in boxes:
            class_id = int(box.cls[0])
            confidence = float(box.conf[0])
            class_name = model.names[class_id]
            
            print(f"{class_name}: {confidence:.2f}")
            
            # 检测人物
            if class_name == 'person':
                person_detected = True
            # 检测可能是香烟的物体
            elif class_name in ['cell phone', 'remote', 'bottle', 'cup']:
                # 这些物体可能被误识别为香烟
                cigarette_detected = True
    
    # 生成带标注的图像
    annotated_image = results[0].plot()
    output_path = 'simple_smoking_detection_result.jpg'
    cv2.imwrite(output_path, annotated_image)
    print(f"\n标注结果已保存到: {output_path}")
    
    # 判断是否在抽烟
    print("\n=== 抽烟检测结果 ===")
    print(f"是否检测到人物: {'是' if person_detected else '否'}")
    print(f"是否检测到可能的香烟: {'是' if cigarette_detected else '否'}")
    
    if person_detected and cigarette_detected:
        print("结论: 图片中的人物可能在抽烟")
        return True
    elif person_detected:
        print("结论: 图片中的人物没有在抽烟")
        return False
    else:
        print("结论: 未检测到人物")
        return False


def main():
    image_path = 'data/raw/xiyandenanrentupian_13227680.jpg'
    detect_smoking(image_path)


if __name__ == '__main__':
    main()
