#!/usr/bin/env python3
"""Somfy Protect 2 MQTT"""
import argparse
import logging
from functools import partial
from signal import SIGINT, SIGTERM, signal

from exceptions import SomfyProtectInitError
from somfy_protect_2_mqtt import SomfyProtect2Mqtt
from utils import close_and_exit, setup_logger, read_config_file


if __name__ == "__main__":

    # Read Arguments
    PARSER = argparse.ArgumentParser()
    PARSER.add_argument(
        "--verbose", "-v", action="store_true", help="verbose mode"
    )
    ARGS = PARSER.parse_args()

    # Setup Logger
    setup_logger(debug=ARGS.verbose, filename="somfyProtect2Mqtt.log")
    LOGGER = logging.getLogger(__name__)
    LOGGER.info(f"Starting SomfyProtect2Mqtt")

    # Load Configuration File
    CONFIG = read_config_file("config/config.yaml")

    try:
        SOMFY_PROTECT = SomfyProtect2Mqtt(CONFIG)

    except SomfyProtectInitError as exp:
        LOGGER.error(f"Unable to init: {exp}")
        close_and_exit(None, None, None, 1)

    # Trigger Ctrl-C
    signal(SIGINT, partial(close_and_exit, SOMFY_PROTECT, 0))
    signal(SIGTERM, partial(close_and_exit, SOMFY_PROTECT, 0))

    try:
        SOMFY_PROTECT.loop()

    except Exception as exp:
        LOGGER.error(f"Exception catched: {repr(exp)}")
        LOGGER.error("Force stopping application")
        close_and_exit(SOMFY_PROTECT, 3)
