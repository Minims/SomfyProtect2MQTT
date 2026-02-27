#!/usr/bin/env python3
"""Somfy Protect 2 MQTT"""
import argparse
import logging
import signal
import threading
import time

from constants import WEBSOCKET_RECONNECT
from exceptions import SomfyProtectInitError
from mqtt import init_mqtt
from somfy_protect.api import SomfyProtectApi
from somfy_protect.sso import init_sso
from somfy_protect.websocket import SomfyProtectWebsocket
from somfy_protect_2_mqtt import SomfyProtect2Mqtt
from utils import read_config_file, setup_logger

VERSION = "2026.3.0"
LOGGER = logging.getLogger(__name__)

# Global flag for shutdown
shutdown_event = threading.Event()


def signal_handler(sig, _frame):
    """Handle shutdown signals"""
    LOGGER.info(f"Received signal {sig}, shutting down gracefully...")
    shutdown_event.set()


def somfy_protect_loop(config, mqtt_client, api):
    """SomfyProtect 2 MQTT Loop"""
    somfy_protect_api = None
    try:
        somfy_protect_api = SomfyProtect2Mqtt(api=api, mqtt_client=mqtt_client, config=config)
        time.sleep(1)
        somfy_protect_api.loop(shutdown_event=shutdown_event)
    except SomfyProtectInitError as e:
        LOGGER.exception(f"Unable to initialize API loop: {e}")
        shutdown_event.set()
    except (OSError, RuntimeError, ValueError) as e:
        LOGGER.exception(f"API loop stopped unexpectedly: {e}")


def _start_api_thread(config, mqtt_client, api):
    return threading.Thread(
        target=somfy_protect_loop,
        args=(
            config,
            mqtt_client,
            api,
        ),
        name="somfy-api-loop",
    )


def somfy_protect_wss_loop(sso, debug, config, mqtt_client, api, ws_state):
    """SomfyProtect WSS Loop"""
    websocket_client = None
    try:
        websocket_client = SomfyProtectWebsocket(sso=sso, debug=debug, config=config, mqtt_client=mqtt_client, api=api)
        ws_state["instance"] = websocket_client
        websocket_client.run_forever()
    except (OSError, RuntimeError) as e:
        if not shutdown_event.is_set():
            LOGGER.exception(f"WebSocket loop stopped unexpectedly: {e}")
    finally:
        if websocket_client:
            websocket_client.close()
        ws_state["instance"] = None


def _start_wss_thread(sso, debug, config, mqtt_client, api, ws_state):
    return threading.Thread(
        target=somfy_protect_wss_loop,
        args=(
            sso,
            debug,
            config,
            mqtt_client,
            api,
            ws_state,
        ),
        name="somfy-websocket-loop",
    )


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
    if SSO is None:
        raise SomfyProtectInitError("Unable to initialize SSO")
    API = SomfyProtectApi(sso=SSO)
    MQTT_CLIENT = init_mqtt(config=CONFIG, api=API)

    p1 = None
    p2 = None
    websocket_state = {"instance": None}
    API_RESTART_BACKOFF = 5.0

    try:
        p1 = _start_api_thread(
            CONFIG,
            MQTT_CLIENT,
            API,
        )
        p2 = _start_wss_thread(
            SSO,
            DEBUG,
            CONFIG,
            MQTT_CLIENT,
            API,
            websocket_state,
        )
        p1.start()
        p2.start()
        last_wss_restart = time.monotonic()
        last_api_restart = time.monotonic()
        while not shutdown_event.wait(1):
            if not p2.is_alive():
                now = time.monotonic()
                elapsed = now - last_wss_restart
                delay = max(0.0, WEBSOCKET_RECONNECT - elapsed)
                if delay > 0:
                    LOGGER.info(f"WebSocket restart delayed by {delay:.1f}s")
                    if shutdown_event.wait(delay):
                        break
                LOGGER.warning("Websocket is DEAD, restarting")
                p2 = _start_wss_thread(
                    SSO,
                    DEBUG,
                    CONFIG,
                    MQTT_CLIENT,
                    API,
                    websocket_state,
                )
                p2.start()
                last_wss_restart = time.monotonic()

            if not p1.is_alive():
                now = time.monotonic()
                elapsed = now - last_api_restart
                delay = max(0.0, API_RESTART_BACKOFF - elapsed)
                if delay > 0:
                    LOGGER.info(f"API restart delayed by {delay:.1f}s")
                    if shutdown_event.wait(delay):
                        break
                LOGGER.warning("API is DEAD, restarting")
                p1 = _start_api_thread(
                    CONFIG,
                    MQTT_CLIENT,
                    API,
                )
                p1.start()
                last_api_restart = time.monotonic()

        LOGGER.info("Shutdown requested, stopping threads...")
    except (OSError, RuntimeError, ValueError) as e:
        LOGGER.exception(f"Force stopping application {e}")
    finally:
        shutdown_event.set()
        active_websocket = websocket_state.get("instance")
        if active_websocket:
            active_websocket.close()

        if p1 and p1.is_alive():
            p1.join(timeout=10)
        if p2 and p2.is_alive():
            p2.join(timeout=10)

        MQTT_CLIENT.shutdown()
        LOGGER.info("Application stopped")
