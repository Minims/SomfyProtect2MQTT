#!/usr/bin/env python3
"""Somfy Protect 2 MQTT"""
import argparse
import logging

# import os
# import subprocess
import threading
import time

from exceptions import SomfyProtectInitError
from somfy_protect_2_mqtt import SomfyProtect2Mqtt
from utils import close_and_exit, setup_logger, read_config_file
from mqtt import init_mqtt
from somfy_protect.sso import init_sso
from somfy_protect.api import SomfyProtectApi
from somfy_protect.websocket import SomfyProtectWebsocket

VERSION = "2024.3.0"
LOGGER = logging.getLogger(__name__)


def somfy_protect_loop(config, mqtt_client, api):
    """SomfyProtect 2 MQTT Loop"""
    try:
        somfy_protect_api = SomfyProtect2Mqtt(api=api, mqtt_client=mqtt_client, config=config)
        time.sleep(1)
        somfy_protect_api.loop()
    except SomfyProtectInitError as exc:
        LOGGER.error(f"Force stopping Api {exc}")
        if somfy_protect_api:
            close_and_exit(somfy_protect_api, 0)


def somfy_protect_wss_loop(sso, debug, config, mqtt_client, api):
    """SomfyProtect WSS Loop"""
    try:
        wss = SomfyProtectWebsocket(sso=sso, debug=debug, config=config, mqtt_client=mqtt_client, api=api)
        wss.run_forever()
    except Exception as exc:
        LOGGER.error(f"Force stopping WebSocket {exc}")
        if wss:
            close_and_exit(wss, 0)


if __name__ == "__main__":
    # Read Arguments
    PARSER = argparse.ArgumentParser()
    PARSER.add_argument("--verbose", "-v", action="store_true", help="verbose mode")
    PARSER.add_argument("--configuration", "-c", type=str, help="config file path")
    ARGS = PARSER.parse_args()
    DEBUG = ARGS.verbose
    CONFIG_FILE = ARGS.configuration

    # Setup Logger
    setup_logger(debug=DEBUG, filename="somfyProtect2Mqtt.log")
    LOGGER.info(f"Starting SomfyProtect2Mqtt {VERSION}")

    CONFIG = read_config_file(CONFIG_FILE)

    # set Debug level from config or with -v
    DEBUG = CONFIG.get("debug", DEBUG)
    LOG_LEVEL = logging.DEBUG if DEBUG else logging.INFO
    LOGGER.setLevel(level=LOG_LEVEL)

    SSO = init_sso(config=CONFIG)
    API = SomfyProtectApi(sso=SSO)
    MQTT_CLIENT = init_mqtt(config=CONFIG, api=API)

    # with open(os.devnull, "w", encoding="utf-8") as t:
    #     subprocess.Popen(["nohup", "python3", "-m", "http.server", "8080"], stdout=t, stderr=t)

    try:
        p1 = threading.Thread(
            target=somfy_protect_loop,
            args=(
                CONFIG,
                MQTT_CLIENT,
                API,
            ),
        )
        p2 = threading.Thread(
            target=somfy_protect_wss_loop,
            args=(
                SSO,
                DEBUG,
                CONFIG,
                MQTT_CLIENT,
                API,
            ),
        )
        p1.start()
        p2.start()
        while True:
            if not p2.is_alive():
                LOGGER.warning("Websocket is DEAD, restarting")
                p2 = threading.Thread(
                    target=somfy_protect_wss_loop,
                    args=(
                        SSO,
                        DEBUG,
                        CONFIG,
                        MQTT_CLIENT,
                        API,
                    ),
                )
                p2.start()

            if not p1.is_alive():
                LOGGER.warning("API is DEAD, restarting")
                p1 = threading.Thread(
                    target=somfy_protect_loop,
                    args=(
                        CONFIG,
                        MQTT_CLIENT,
                        API,
                    ),
                )
                p1.start()

            time.sleep(1)

    except Exception as exp:
        LOGGER.error(f"Force stopping application {exp}")
