"""Somfy Protect Websocket"""
import base64
import json
import logging
import os
import ssl
import time

from business.mqtt import mqtt_publish, update_site, update_device
from mqtt import MQTTClient, init_mqtt
from oauthlib.oauth2 import LegacyApplicationClient, TokenExpiredError
from requests_oauthlib import OAuth2Session
from somfy_protect.api import SomfyProtectApi
from somfy_protect.sso import SomfyProtectSso, read_token_from_file

import websocket
from websocket import WebSocketApp

WEBSOCKET = "wss://websocket.myfox.io/events/websocket?token="

LOGGER = logging.getLogger(__name__)


class SomfyProtectWebsocket:
    """Somfy Protect WebSocket Class"""

    def __init__(
        self, sso: SomfyProtectSso, config: dict, mqtt_client: MQTTClient, api: SomfyProtectApi, debug: bool = False,
    ):
        self.mqtt_client = mqtt_client
        self.mqtt_config = config.get("mqtt")
        self.api = api
        self.sso = sso

        if debug:
            websocket.enableTrace(True)
            LOGGER.debug(f"Opening websocket connection to {WEBSOCKET}")
        self.token = self.sso.request_token()
        self._websocket = WebSocketApp(
            f"{WEBSOCKET}{self.token.get('access_token')}",
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
        )

    def run_forever(self):
        """Run Forever Loop"""
        self._websocket.run_forever(
            ping_timeout=10, ping_interval=30, sslopt={"cert_reqs": ssl.CERT_NONE},
        )

    def on_message(self, ws_app, message):
        """Handle New message received on WebSocket"""
        if "websocket.connection.ready" in message:
            LOGGER.info("Websocket Connection is READY")
            return

        if "websocket.error.token" in message:
            LOGGER.warning("Websocket Token Error: requesting a new one")
            self.sso.request_token()

        logging.debug(f"Message: {message}")

        message_json = json.loads(message)
        callbacks = {
            "security.level.change": self.update_alarm_status,
            "alarm.panic": self.start_alarm_panic,
            "alarm.end": self.stop_alarm_siren,
            "presence_out": self.update_keyfob_presence,
            "presence_in": self.update_keyfob_presence,
            "device.status": self.update_device_status,
            "site.device.testing.status": self.site_device_testing_status,
            "device.update.connect": self.default_message,
            "device.update.progress": self.default_message,
        }

        ack = {
            "ack": True,
            "message_id": message_json["message_id"],
            "client": "Android",
        }
        ws_app.send(json.dumps(ack))
        if message_json["key"] in callbacks:
            callbacks[message_json["key"]](message_json)
        else:
            LOGGER.debug(f"Unknown message: {message}")

    def on_error(self, ws_app, message):  # pylint: disable=unused-argument,no-self-use
        """Handle Websocket Errors"""
        LOGGER.error(f"Error in the websocket connection: {message}")

    def on_close(self, ws_app, close_status_code, close_msg):  # pylint: disable=unused-argument,no-self-use
        """Handle Websocket Close Connection"""
        LOGGER.info("Closing websocket connection")
        LOGGER.info("Reconnecting")
        time.sleep(10)
        self.run_forever()

    def update_keyfob_presence(self, message):
        """Update Key Fob Presence"""
        LOGGER.info("Update Key Fob Presence")
        site_id = message.get("site_id")
        device_id = message.get("device_id")
        LOGGER.info(message)
        payload = {"presence": "unknown"}
        if message.get("key") == "presence_out":
            payload = {"presence": "not_home"}
        if message.get("key") == "presence_in":
            payload = {"presence": "home"}
        topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/presence"

        mqtt_publish(mqtt_client=self.mqtt_client, topic=topic, payload=payload)

    def update_alarm_status(self, message):
        """Update Alarm Status"""
        LOGGER.info("Update Alarm Status")
        site_id = message.get("site_id")
        security_level = message.get("security_level")
        payload = {"security_level": security_level}
        topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/state"

        mqtt_publish(mqtt_client=self.mqtt_client, topic=topic, payload=payload)

    def start_alarm_panic(self, message):
        """Report Alarm Panic"""
        LOGGER.info("Report Alarm Panic")
        site_id = message.get("site_id")
        security_level = "triggered"
        payload = {"security_level": security_level}
        topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/state"

        mqtt_publish(mqtt_client=self.mqtt_client, topic=topic, payload=payload, retain=True)

    def stop_alarm_siren(self, message):
        """Report Alarm Stop"""
        LOGGER.info("Report Alarm Stop")
        site_id = message.get("site_id")
        update_site(self.api, self.mqtt_client, self.mqtt_config, site_id)

    def update_device_status(self, message):
        """Update Device Status"""
        LOGGER.info("Read Test message")
        site_id = message.get("site_id")
        device_id = message.get("device_id")
        payload = message
        topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/test"
        mqtt_publish(mqtt_client=self.mqtt_client, topic=topic, payload=payload)

    def site_device_testing_status(self, message):
        """Site Device Testing Status"""
        LOGGER.info("Read Site Device Testing Status")
        items = message.get("items")
        site_id = message.get("site_id")
        # = items.get("device_id")
        device_id = ""
        payload = items
        topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/wss"
        mqtt_publish(mqtt_client=self.mqtt_client, topic=topic, payload=payload)

    def default_message(self, message):
        """Unknown Message"""
        LOGGER.info("#####################################")
        LOGGER.info("Read Unknown Message")
        LOGGER.info(f"Message: {message}")
        # LOGGER.info(f"Site: {message.get('site_id')}")
        # LOGGER.info(f"Device: {message.get('device_id')}")
        # LOGGER.info(f"Key: {message.get('key')}")
        # LOGGER.info(f"Items: {message.get('items')}")
        LOGGER.info("#####################################")
