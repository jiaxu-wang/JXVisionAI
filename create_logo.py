from PIL import Image, ImageDraw, ImageFont

# 创建一个200x200的图片
img = Image.new('RGB', (200, 200), color=(33, 150, 243))
d = ImageDraw.Draw(img)

# 绘制渐变背景
for i in range(200):
    for j in range(200):
        r = 33 + int((19 - 33) * i / 200)
        g = 150 + int((139 - 150) * i / 200)
        b = 243 + int((178 - 243) * i / 200)
        d.point((i, j), fill=(r, g, b))

# 绘制相机图标
d.ellipse((50, 50, 150, 150), outline=(255, 255, 255), width=5)
d.ellipse((70, 70, 130, 130), outline=(255, 255, 255), width=3)
d.rectangle((90, 90, 110, 110), fill=(255, 255, 255))
d.rectangle((80, 120, 120, 140), fill=(255, 255, 255))

# 绘制AI文字
try:
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 24)
except:
    font = ImageFont.load_default()

d.text((60, 160), "VisionAI", fill=(255, 255, 255), font=font)

# 保存图片
img.save('static/images/logo.jpg')
print("Logo created successfully at static/images/logo.jpg")