#!/usr/bin/env python3
"""Somfy Protect 2 MQTT"""
import argparse
import logging
import threading
from functools import partial
from signal import SIGINT, SIGTERM, signal

from exceptions import SomfyProtectInitError
from somfy_protect_2_mqtt import SomfyProtect2Mqtt
from utils import close_and_exit, setup_logger, read_config_file
from mqtt import init_mqtt
from somfy_protect.sso import init_sso
from somfy_protect.api import SomfyProtectApi
from somfy_protect.websocket import SomfyProtectWebsocket

VERSION = "0.2.1"


def somfy_protect_loop(somfy_protect_2_mqtt):
    """SomfyProtect 2 MQTT Loop"""
    try:
        somfy_protect_2_mqtt.loop()
    except Exception as exp:
        LOGGER.error(f"Force stopping Api {exp}")
        close_and_exit(somfy_protect_2_mqtt, 3)


def somfy_protect_wss_loop(somfy_protect_websocket):
    """SomfyProtect WSS Loop"""
    try:
        somfy_protect_websocket.run_forever()
    except Exception as exp:
        LOGGER.error(f"Force stopping WebSocket {exp}")
        close_and_exit(somfy_protect_websocket, 3)


if __name__ == "__main__":

    # Read Arguments
    PARSER = argparse.ArgumentParser()
    PARSER.add_argument(
        "--verbose", "-v", action="store_true", help="verbose mode"
    )
    PARSER.add_argument(
        "--configuration", "-c", type=str, help="config file path"
    )
    ARGS = PARSER.parse_args()
    DEBUG = ARGS.verbose
    CONFIG_FILE = ARGS.configuration

    # Setup Logger
    setup_logger(debug=DEBUG, filename="somfyProtect2Mqtt.log")
    LOGGER = logging.getLogger(__name__)
    LOGGER.info(f"Starting SomfyProtect2Mqtt {VERSION}")

    CONFIG = read_config_file(CONFIG_FILE)

    SSO = init_sso(config=CONFIG)
    API = SomfyProtectApi(sso=SSO)
    MQTT_CLIENT = init_mqtt(config=CONFIG, api=API)
    WSS = SomfyProtectWebsocket(
        sso=SSO, debug=DEBUG, config=CONFIG, mqtt_client=MQTT_CLIENT, api=API
    )

    try:
        SOMFY_PROTECT = SomfyProtect2Mqtt(
            api=API, mqtt_client=MQTT_CLIENT, config=CONFIG
        )

    except SomfyProtectInitError as exp:
        LOGGER.error(f"Unable to init: {exp}")
        close_and_exit(None, None, None, 1)

    # Trigger Ctrl-C
    signal(SIGINT, partial(close_and_exit, SOMFY_PROTECT, 0))
    signal(SIGTERM, partial(close_and_exit, SOMFY_PROTECT, 0))

    try:
        p1 = threading.Thread(target=somfy_protect_loop, args=(SOMFY_PROTECT,))
        p2 = threading.Thread(target=somfy_protect_wss_loop, args=(WSS,))
        p1.start()
        p2.start()
    except Exception as exp:
        LOGGER.error(f"Force stopping application {exp}")
        close_and_exit(SOMFY_PROTECT, 3)
