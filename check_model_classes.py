from ultralytics import YOLO

# 检查yolo26n.pt模型
print("=== 检查 yolo26n.pt 模型 ===")
model_n = YOLO('yolo26n.pt')
classes_n = model_n.names
print(f"类别数量: {len(classes_n)}")
print("支持的类别:")
for i, class_name in classes_n.items():
    print(f"  {i}: {class_name}")

print("\n=== 检查 yolo26s.pt 模型 ===")
# 检查yolo26s.pt模型
model_s = YOLO('yolo26s.pt')
classes_s = model_s.names
print(f"类别数量: {len(classes_s)}")
print("支持的类别:")
for i, class_name in classes_s.items():
    print(f"  {i}: {class_name}")
