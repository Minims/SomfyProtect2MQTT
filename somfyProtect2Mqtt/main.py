#!/usr/bin/env python3
"""Somfy Protect 2 MQTT"""
import argparse
import logging
import signal
import threading
import time

from exceptions import SomfyProtectInitError
from somfy_protect_2_mqtt import SomfyProtect2Mqtt
from utils import close_and_exit, setup_logger, read_config_file
from mqtt import init_mqtt
from somfy_protect.sso import init_sso
from somfy_protect.api import SomfyProtectApi
from somfy_protect.websocket import SomfyProtectWebsocket
from business.mqtt import shutdown_executor

VERSION = "2026.1.1"
LOGGER = logging.getLogger(__name__)

# Global flag for shutdown
# Use an Event for graceful shutdown so threads can respect it
shutdown_event = threading.Event()


def signal_handler(sig, frame):
    """Handle shutdown signals by setting the shutdown_event.

    Avoid calling sys.exit from a signal handler to allow threads to
    clean up resources. The main thread will notice the event and
    perform an orderly shutdown.
    """
    LOGGER.info("Received signal %s, shutting down gracefully...", sig)
    shutdown_event.set()


def somfy_protect_loop(config, mqtt_client, api, stop_event=None):
    """SomfyProtect 2 MQTT Loop"""
    try:
        somfy_protect_api = SomfyProtect2Mqtt(api=api, mqtt_client=mqtt_client, config=config)
        time.sleep(1)
        # prefer passed event, fall back to global
        somfy_protect_api.loop(stop_event or shutdown_event)
    except SomfyProtectInitError as exc:
        LOGGER.error("Force stopping Api: %s", exc)
        if "somfy_protect_api" in locals() and somfy_protect_api:
            close_and_exit(somfy_protect_api, 0)


def somfy_protect_wss_loop(sso, debug, config, mqtt_client, api, stop_event=None):
    """SomfyProtect WSS Loop"""
    wss = None
    try:
        wss = SomfyProtectWebsocket(sso=sso, debug=debug, config=config, mqtt_client=mqtt_client, api=api)
        # run_forever is blocking; run it in its own thread so we can monitor stop_event
        ws_thread = threading.Thread(target=wss.run_forever, daemon=True)
        ws_thread.start()
        # Wait until stop_event is set
        stop_event = stop_event or shutdown_event
        while not stop_event.is_set():
            stop_event.wait(timeout=1)
        # On shutdown, close websocket and join thread
        wss.close()
        ws_thread.join(timeout=5)
    except Exception as exc:
        LOGGER.error("Force stopping WebSocket: %s", exc)
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
        # start threads as daemons so they don't prevent process exit
        p1 = threading.Thread(target=somfy_protect_loop, args=(CONFIG, MQTT_CLIENT, API, shutdown_event), daemon=True)
        p2 = threading.Thread(target=somfy_protect_wss_loop, args=(SSO, DEBUG, CONFIG, MQTT_CLIENT, API, shutdown_event), daemon=True)
        p1.start()
        p2.start()

        # restart backoff state
        backoffs = {"p1": 1, "p2": 1}
        while not shutdown_event.is_set():
            # restart websocket thread with exponential backoff
            if not p2.is_alive():
                LOGGER.warning("Websocket is DEAD, restarting (backoff %s)s", backoffs["p2"])
                shutdown_event.wait(timeout=backoffs["p2"])  # sleep with awareness of shutdown
                backoffs["p2"] = min(backoffs["p2"] * 2, 60)
                p2 = threading.Thread(target=somfy_protect_wss_loop, args=(SSO, DEBUG, CONFIG, MQTT_CLIENT, API, shutdown_event), daemon=True)
                p2.start()
            else:
                backoffs["p2"] = 1

            # restart api thread with exponential backoff
            if not p1.is_alive():
                LOGGER.warning("API is DEAD, restarting (backoff %s)s", backoffs["p1"])
                shutdown_event.wait(timeout=backoffs["p1"])  # sleep with awareness of shutdown
                backoffs["p1"] = min(backoffs["p1"] * 2, 60)
                p1 = threading.Thread(target=somfy_protect_loop, args=(CONFIG, MQTT_CLIENT, API, shutdown_event), daemon=True)
                p1.start()
            else:
                backoffs["p1"] = 1

            # small wait so the loop is not busy, but responsive to shutdown
            shutdown_event.wait(timeout=1)

    except Exception as exp:
        LOGGER.exception("Force stopping application: %s", exp)
    finally:
        LOGGER.info("Shutdown requested, joining threads...")
        shutdown_event.set()
        try:
            # shutdown background executor tasks (from business.mqtt)
            shutdown_executor()
        except Exception:
            LOGGER.exception("Error while calling shutdown_executor")
        if "p1" in locals() and p1 is not None:
            try:
                p1.join(timeout=5)
            except Exception:
                LOGGER.warning("Failed to join p1 thread")
        if "p2" in locals() and p2 is not None:
            try:
                p2.join(timeout=5)
            except Exception:
                LOGGER.warning("Failed to join p2 thread")
        LOGGER.info("Shutdown complete")
