#!/usr/bin/env python3
"""Somfy Protect 2 MQTT"""
import argparse
import logging
import signal
import sys
import threading
import time

from constants import WEBSOCKET_RECONNECT
from exceptions import SomfyProtectInitError
from mqtt import init_mqtt
from somfy_protect.api import SomfyProtectApi
from somfy_protect.sso import init_sso
from somfy_protect.websocket import SomfyProtectWebsocket
from somfy_protect_2_mqtt import SomfyProtect2Mqtt
from utils import close_and_exit, read_config_file, setup_logger

VERSION = "2026.2.0"
LOGGER = logging.getLogger(__name__)

# Global flag for shutdown
shutdown_event = threading.Event()


def signal_handler(sig, _frame):
    """Handle shutdown signals"""
    LOGGER.info(f"Received signal {sig}, shutting down gracefully...")
    shutdown_event.set()
    sys.exit(0)


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
    wss = None
    try:
        wss = SomfyProtectWebsocket(sso=sso, debug=debug, config=config, mqtt_client=mqtt_client, api=api)
        wss.run_forever()
    except (OSError, RuntimeError) as e:
        LOGGER.error(f"Force stopping WebSocket {e}")
        if wss:
            wss.close()
    finally:
        if wss:
            wss.close()


if __name__ == "__main__":
    # Read Arguments
    PARSER = argparse.ArgumentParser()
    PARSER.add_argument("--verbose", "-v", action="store_true", help="verbose mode")
    PARSER.add_argument("--configuration", "-c", type=str, help="config file path")
    ARGS = PARSER.parse_args()
    DEBUG = ARGS.verbose
    CONFIG_FILE = ARGS.configuration

    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

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
        last_wss_restart = 0.0
        while True:
            if shutdown_event.is_set():
                LOGGER.info("Shutdown requested, stopping threads...")
                break

            if not p2.is_alive():
                now = time.monotonic()
                elapsed = now - last_wss_restart
                if elapsed < WEBSOCKET_RECONNECT:
                    time.sleep(WEBSOCKET_RECONNECT - elapsed)
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
                last_wss_restart = time.monotonic()

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

    except (OSError, RuntimeError) as e:
        LOGGER.error(f"Force stopping application {e}")
