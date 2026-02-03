"""Add Watermark on Snapshot"""

import logging
import os

from PIL import Image, ImageDraw, ImageFont

LOGGER = logging.getLogger(__name__)


def insert_watermark(file: str, watermark: str):
    """Insert a watermark text on an image file.
    
    Args:
        file: Path to the image file
        watermark: Text to add as watermark
    """
    with Image.open(fp=file) as image:
        watermark_image = image.copy()
        draw = ImageDraw.Draw(watermark_image)
        width, _ = image.size
        font = ImageFont.truetype(f"{os.path.dirname(__file__)}/arial.ttf", 22)
        draw.text((width - 210, 0), watermark, fill=(0, 0, 0), font=font)
        watermark_image.save(file)
