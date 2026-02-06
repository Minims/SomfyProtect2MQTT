"""Add Watermark on Snapshot"""

import logging
import os

from PIL import Image, ImageDraw, ImageFont

LOGGER = logging.getLogger(__name__)


def insert_watermark(file: str, watermark: str) -> None:
    """Insert a text watermark into an image file.

    Args:
        file (str): Image file path.
        watermark (str): Watermark text to draw.
    """
    image = Image.open(
        fp=file,
    )
    watermark_image = image.copy()
    draw = ImageDraw.Draw(watermark_image)
    width, _ = image.size
    font = ImageFont.truetype(f"{os.path.dirname(__file__)}/arial.ttf", 22)
    draw.text((width - 210, 0), watermark, fill=(0, 0, 0), font=font)
    watermark_image.save(file)
