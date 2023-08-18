"""Add Watermark on Snapshot"""
from PIL import Image, ImageDraw, ImageFont


def insert_watermark(file: str, watermark: str):
    image = Image.open(file)
    watermark_image = image.copy()
    draw = ImageDraw.Draw(watermark_image)
    width, _ = image.size
    font = ImageFont.truetype("Arial.ttf", 24)
    draw.text((width - 210, 0), watermark, fill=(0, 0, 0), font=font)
    print("OK")
    watermark_image.save(file)
