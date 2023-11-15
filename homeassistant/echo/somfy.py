#!/usr/bin/env python3
"""
Somfy Protect 2 MQTT Camera Stream with go2rtc
https://github.com/AlexxIT/go2rtc/wiki/Source-Echo-examples#install-python-libraries
"""

import logging
import sys

LOGGER = logging.getLogger(__name__)
FOLDER = "/homeassistant/somfyProtect2mqtt"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s",
    handlers=[
        logging.FileHandler(filename=f"{FOLDER}/somfy.log"),
    ],
)

LOGGER.info("Start")
try:
    with open(f"{FOLDER}/stream_url_{sys.argv[1]}", "r", encoding="utf-8") as url:
        print(f"ffmpeg:{url.read()}#video=copy")
        LOGGER.info(f"ffmpeg:{url.read()}#video=copy")
except FileNotFoundError as exc:
    LOGGER.warning(exc)
