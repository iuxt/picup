import os
import io
import time
import uuid
from flask import Flask, request, jsonify
from PIL import Image, ImageDraw, ImageFont
import boto3
from botocore.exceptions import NoCredentialsError
import subprocess
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

app = Flask(__name__)

# S3 配置
S3_BUCKET = os.getenv('S3_BUCKET_NAME')
S3_REGION = os.getenv('AWS_REGION')
S3_ENDPOINT = os.getenv('S3_ENDPOINT_URL', None)

# 水印配置
WATERMARK_TEXT = os.getenv('WATERMARK_TEXT', 'PicUp')
WATERMARK_POSITION = os.getenv('WATERMARK_POSITION', 'bottom_right')
WATERMARK_COLOR = os.getenv('WATERMARK_COLOR', '#FFFFFF')

def get_clipboard_image():
    """获取剪贴板中的图片"""
    try:
        # 使用 pyobjc 库获取剪贴板图片
        from AppKit import NSPasteboard, NSImage
        import io
        
        # 获取系统剪贴板
        pasteboard = NSPasteboard.generalPasteboard()
        
        # 获取剪贴板项目
        items = pasteboard.pasteboardItems()
        if not items:
            return None
        
        # 遍历剪贴板项目
        for item in items:
            # 获取项目的所有数据类型
            types = item.types()
            
            # 尝试多种图片数据类型
            for data_type in ["public.png", "public.tiff", "public.image", "NSBitmapImageRep"]:
                if data_type in types:
                    try:
                        # 获取数据
                        data = item.dataForType_(data_type)
                        if data:
                            # 将 NSData 转换为字节流
                            bytes_data = data.bytes()
                            img_data = io.BytesIO(bytes_data)
                            
                            # 打开图片
                            return Image.open(img_data)
                    except Exception:
                        continue
        
        # 如果没有找到图片数据
        return None
    except Exception as e:
        print(f"获取剪贴板图片失败: {e}")
        return None

def add_watermark(image):
    """为图片添加水印"""
    try:
        # 创建可绘制对象
        draw = ImageDraw.Draw(image)
        
        # 获取图片尺寸
        image_width, image_height = image.size
        
        # 计算相对水印大小（基于图片对角线长度的一定比例）
        import math
        diagonal = math.sqrt(image_width ** 2 + image_height ** 2)
        # 水印大小为对角线长度的 1/30，最小 8px，最大 30px
        relative_size = max(8, min(30, int(diagonal / 30)))
        
        # 尝试使用系统字体
        try:
            font = ImageFont.truetype('/System/Library/Fonts/STHeiti Light.ttc', relative_size)
        except:
            font = ImageFont.load_default()
        
        # 计算水印位置
        # 使用 font.getbbox() 替代 draw.textsize() (Pillow 9.0+)
        bbox = font.getbbox(WATERMARK_TEXT)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        if WATERMARK_POSITION == 'bottom_right':
            x = image_width - text_width - 10
            y = image_height - text_height - 10
        elif WATERMARK_POSITION == 'bottom_left':
            x = 10
            y = image_height - text_height - 10
        elif WATERMARK_POSITION == 'top_right':
            x = image_width - text_width - 10
            y = 10
        elif WATERMARK_POSITION == 'top_left':
            x = 10
            y = 10
        else:  # 默认右下角
            x = image_width - text_width - 10
            y = image_height - text_height - 10
        
        # 添加水印
        draw.text((x, y), WATERMARK_TEXT, font=font, fill=WATERMARK_COLOR)
        
        return image
    except Exception as e:
        print(f"添加水印失败: {e}")
        return image

def upload_to_s3(image, filename):
    """上传图片到 S3"""
    try:
        # 检查必要的配置
        if not S3_BUCKET or not S3_REGION:
            print("S3 配置不完整")
            return None
        
        # 初始化 S3 客户端
        s3 = boto3.client(
            's3',
            region_name=S3_REGION,
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )
        
        # 将图片转换为字节流
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        
        # 生成年月文件夹前缀
        from datetime import datetime
        now = datetime.now()
        year_month = f"{now.year}/{now.month:02d}"
        
        # 生成带年月前缀的唯一文件名
        unique_filename = f"{year_month}/{int(time.time())}_{uuid.uuid4().hex}_{filename}"
        
        # 上传到 S3
        s3.upload_fileobj(
            img_byte_arr,
            S3_BUCKET,
            unique_filename,
            ExtraArgs={'ContentType': 'image/png'}
        )
        
        # 生成 URL
        if S3_ENDPOINT:
            # 自定义 S3 兼容存储
            url = f"{S3_ENDPOINT}/{S3_BUCKET}/{unique_filename}"
        else:
            # 标准 AWS S3
            url = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{unique_filename}"
        
        return url
    except NoCredentialsError:
        print("S3 凭证错误")
        return None
    except Exception as e:
        print(f"上传到 S3 失败: {e}")
        return None

def copy_to_clipboard(text):
    """将文本复制到剪贴板"""
    try:
        subprocess.run(['pbcopy'], input=text.encode('utf-8'), check=True)
        return True
    except Exception as e:
        print(f"复制到剪贴板失败: {e}")
        return False

def show_notification(title, message):
    """显示 macOS 通知"""
    try:
        script = f"display notification \"{message}\" with title \"{title}\""
        subprocess.run(['osascript', '-e', script], check=True)
        return True
    except Exception as e:
        print(f"显示通知失败: {e}")
        return False

@app.route('/upload', methods=['POST'])
def upload():
    """上传剪贴板图片到 S3"""
    try:
        # 获取剪贴板图片
        image = get_clipboard_image()
        if not image:
            print("剪贴板中没有图片")
            return jsonify({'success': False, 'message': '剪贴板中没有图片'}), 400
        
        # 添加水印
        watermarked_image = add_watermark(image)
        
        # 上传到 S3
        url = upload_to_s3(watermarked_image, 'clipboard.png')
        if not url:
            return jsonify({'success': False, 'message': '上传到 S3 失败'}), 500
        
        # 复制 URL 到剪贴板
        copy_to_clipboard(url)
        
        # 显示通知
        show_notification('上传成功', f'图片已上传到 S3\nURL 已复制到剪贴板')
        
        # 返回 PicGo 兼容的响应格式
        return jsonify({'success': True, 'result': url})
    except Exception as e:
        print(f"上传过程中出错: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """健康检查端点"""
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(debug=False, host='127.0.0.1', port=36677)