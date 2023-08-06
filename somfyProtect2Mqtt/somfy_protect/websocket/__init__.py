"""Somfy Protect Websocket"""
import base64
import json
import logging
import os
import ssl
import time
from signal import SIGKILL

import websocket
from business.mqtt import mqtt_publish, update_device, update_site
from homeassistant.ha_discovery import ALARM_STATUS
from mqtt import MQTTClient, init_mqtt
from oauthlib.oauth2 import LegacyApplicationClient, TokenExpiredError
from requests_oauthlib import OAuth2Session
from somfy_protect.api import SomfyProtectApi
from somfy_protect.sso import SomfyProtectSso, read_token_from_file
from websocket import WebSocketApp

WEBSOCKET = "wss://websocket.myfox.io/events/websocket?token="

LOGGER = logging.getLogger(__name__)


class SomfyProtectWebsocket:
    """Somfy Protect WebSocket Class"""

    def __init__(
        self,
        sso: SomfyProtectSso,
        config: dict,
        mqtt_client: MQTTClient,
        api: SomfyProtectApi,
        debug: bool = False,
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
            ping_timeout=10,
            ping_interval=20,
            sslopt={"cert_reqs": ssl.CERT_NONE},
        )

    def close(self):
        """Close Websocket Connection"""
        LOGGER.info("WebSocket Close")
        self._websocket.close()

    def on_message(self, ws_app, message):
        """Handle New message received on WebSocket"""
        if "websocket.connection.ready" in message:
            LOGGER.info("Websocket Connection is READY")
            return

        if "websocket.error.token" in message:
            self._websocket.close()
            return

        logging.debug(f"Message: {message}")

        message_json = json.loads(message)
        callbacks = {
            "security.level.change": self.security_level_change,
            "alarm.trespass": self.alarm_trespass,
            "alarm.panic": self.alarm_panic,
            "alarm.end": self.alarm_end,
            "presence_out": self.update_keyfob_presence,
            "presence_in": self.update_keyfob_presence,
            "device.status": self.device_status,
        }

        ack = {
            "ack": True,
            "message_id": message_json["message_id"],
            "client": "Android",
        }
        send = ws_app.send(json.dumps(ack))
        LOGGER.debug(send)
        self.default_message(message_json)
        if message_json["key"] in callbacks:
            callbacks[message_json["key"]](message_json)
        else:
            LOGGER.debug(f"Unknown message: {message}")

    def on_error(self, ws_app, message):  # pylint: disable=unused-argument,no-self-use
        """Handle Websocket Errors"""
        LOGGER.error(f"Error in the websocket connection: {message}")

    def on_close(self, ws_app, close_status_code, close_msg):  # pylint: disable=unused-argument,no-self-use
        """Handle Websocket Close Connection"""
        LOGGER.info("Websocket on_close")

    def update_keyfob_presence(self, message):
        """Update Key Fob Presence"""
        # {
        # "profiles":[
        #     "owner",
        #     "admin"
        # ],
        # "site_id":"XXX",
        # "type":"event",
        # "key":"presence_in",
        # "user_id":"XXX",
        # "device_id":"XXX",
        # "device_type":"fob",
        # "message_id":"XXX"
        # },
        # {
        # "profiles":[
        #     "owner",
        #     "admin"
        # ],
        # "site_id":"XXX",
        # "type":"event",
        # "key":"presence_out",
        # "user_id":"XXX",
        # "device_id":"XXX",
        # "device_type":"fob",
        # "message_id":"XXX"
        # }
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

        mqtt_publish(
            mqtt_client=self.mqtt_client,
            topic=topic,
            payload=payload,
            retain=True,
        )

    def security_level_change(self, message):
        """Update Alarm Status"""
        # {
        # "profiles":[
        #     "owner",
        #     "admin",
        #     "guest",
        #     "kid"
        # ],
        # "site_id":"XXX",
        # "type":"config",
        # "key":"security.level.change",
        # "security_level":"armed",
        # "message_id":"XXX"
        # }
        LOGGER.info("Update Alarm Status")
        site_id = message.get("site_id")
        security_level = message.get("security_level")
        payload = ({"security_level": ALARM_STATUS.get(security_level, "disarmed")},)
        topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/state"

        mqtt_publish(mqtt_client=self.mqtt_client, topic=topic, payload=payload, retain=True)

    def alarm_trespass(self, message):
        """Alarm Triggered !!"""
        # {
        # "profiles":[
        #     "owner",
        #     "admin",
        #     "custom",
        #     "family",
        #     "neighbor"
        # ],
        # "site_id":"XXX",
        # "type":"alarm",
        # "key":"alarm.trespass",
        # "device_id":"XXX",
        # "device_type":"pir",
        # "start_at":"2022-03-14T17:17:12.000000Z",
        # "start_siren_at":"2022-03-14T17:17:42.000000Z",
        # "end_at":"2022-03-14T17:20:42.000000Z",
        # "end_siren_at":"2022-03-14T17:20:42.000000Z",
        # "manual_alarm":false,
        # "message_id":"XXX"
        # }
        LOGGER.info("Report Alarm Triggered")
        site_id = message.get("site_id")
        device_id = message.get("device_id")
        device_type = message.get("device_type")
        security_level = "triggered"
        if message.get("type") != "alarm":
            LOGGER.info(f"{message.get('type')} is not 'alarm'")
        payload = {"security_level": security_level}
        topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/state"

        mqtt_publish(
            mqtt_client=self.mqtt_client,
            topic=topic,
            payload=payload,
            retain=True,
        )

        if device_type == "pir":
            LOGGER.info("Trigger PIR Sensor")
            payload = {"motion_sensor": "True"}
            topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/pir"

            mqtt_publish(mqtt_client=self.mqtt_client, topic=topic, payload=payload, retain=True)
            time.sleep(3)
            payload = {"motion_sensor": "False"}
            mqtt_publish(mqtt_client=self.mqtt_client, topic=topic, payload=payload, retain=True)

    def alarm_panic(self, message):
        """Report Alarm Panic"""
        # {
        # "profiles":[
        #     "owner",
        #     "admin",
        #     "custom",
        #     "family",
        #     "neighbor"
        # ],
        # "site_id":"XXX",
        # "type":"alarm",
        # "key":"alarm.panic",
        # "device_id":null,
        # "device_type":null,
        # "start_at":"2022-03-14T17:21:07.000000Z",
        # "start_siren_at":"2022-03-14T17:21:07.000000Z",
        # "end_at":"2022-03-14T17:24:07.000000Z",
        # "end_siren_at":"2022-03-14T17:24:07.000000Z",
        # "manual_alarm":false,
        # "message_id":"XXX"
        # }
        LOGGER.info("Report Alarm Panic")
        site_id = message.get("site_id")
        security_level = "triggered"
        payload = {"security_level": security_level}
        topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/state"

        mqtt_publish(
            mqtt_client=self.mqtt_client,
            topic=topic,
            payload=payload,
            retain=True,
        )

    def alarm_end(self, message):
        """Report Alarm Stop"""
        # {
        # "profiles":[
        #     "owner",
        #     "admin",
        #     "custom",
        #     "family",
        #     "neighbor"
        # ],
        # "site_id":"XXX",
        # "type":"alarm",
        # "key":"alarm.end",
        # "device_id":null,
        # "device_type":null,
        # "end_at":"2022-03-14T17:19:22.000000Z",
        # "end_siren_at":null,
        # "stopped_by_user_id":"XXX",
        # "message_id":"XXX"
        # }
        LOGGER.info("Report Alarm Stop")
        site_id = message.get("site_id")
        update_site(self.api, self.mqtt_client, self.mqtt_config, site_id)

    def device_status(self, message):
        """Update Device Status"""
        # {
        # "profiles":[
        #     "admin",
        #     "owner",
        #     "installer_write"
        # ],
        # "site_id":"XXX",
        # "type":"testing",
        # "key":"device.status",
        # "device_id":"XXX",
        # "device_lost":false,
        # "rlink_quality":-73,
        # "rlink_quality_percent":75,
        # "battery_level":100,
        # "recalibration_required":false,
        # "cover_present":true,
        # "last_status_at":"2022-03-16T16:06:56.000000Z",
        # "diagnosis":{
        #     "is_everything_ok":true,
        #     "problems":[
        #     ]
        # },
        # "message_id":"XXX"
        # }
        site_id = message.get("site_id")
        device_id = message.get("device_id")
        LOGGER.info(f"It Seems the Door {device_id} is moving")
        topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/pir"
        payload = {"motion_sensor": "True"}
        mqtt_publish(mqtt_client=self.mqtt_client, topic=topic, payload=payload, retain=True)
        time.sleep(3)
        payload = {"motion_sensor": "False"}
        mqtt_publish(mqtt_client=self.mqtt_client, topic=topic, payload=payload, retain=True)

    def site_device_testing_status(self, message):
        """Site Device Testing Status"""
        # {
        # "profiles":[
        #     "owner",
        #     "admin"
        # ],
        # "site_id":"XXX",
        # "type":"testing",
        # "key":"site.device.testing.status",
        # "diagnosis":{
        #     "main_status":"ok",
        #     "main_message":"diagnosis.ok",
        #     "main_message_vars":{

        #     },
        #     "device_diagnosis_available":true,
        #     "device_diagnosis_expired":false,
        #     "items":[

        #     ]
        # },
        # "message_id":"XXX"
        # }

    def default_message(self, message):
        """Default Message"""
        LOGGER.info(f"[default] Read Message {message}")
        topic_suffix = message.get("key")
        site_id = message.get("site_id")
        device_id = message.get("device_id")
        if not site_id:
            topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{topic_suffix}"
        elif not device_id:
            topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{topic_suffix}"
        else:
            topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/{topic_suffix}"
        mqtt_publish(
            mqtt_client=self.mqtt_client,
            topic=topic,
            payload=message,
            retain=True,
        )

    def remote_unassigned(self, message):
        """Remote Unassigned"""
        # {
        # "profiles":[
        #     "owner",
        #     "admin"
        # ],
        # "site_id":"XXX",
        # "type":"config",
        # "key":"remote_unassigned",
        # "user_id":"XXX",
        # "device_id":"XXX",
        # "message_id":"XXX"
        # }

    def device_firmware_update_fail(self, message):
        """Device Firmware Update Fail"""
        # {
        # "profiles":[
        #     "owner",
        #     "admin"
        # ],
        # "site_id":"XXX",
        # "type":"config",
        # "key":"device.firmware.update.fail",
        # "device_id":"XXX",
        # "reason":100,
        # "message_id":"XXX"
        # }

    def site_privacy(self, message):
        """Site Privacy"""
        # {
        # "profiles":[
        #     "admin",
        #     "owner",
        #     "installer_write"
        # ],
        # "site_id":"XXX",
        # "type":"event",
        # "key":"site.privacy",
        # "active":true,
        # "message_id":"XXX"
        # }

    def camerastatus_shutter(self, message):
        """Camera Status Shutter Close"""
        # {
        # "profiles":[
        #     "admin",
        #     "owner",
        #     "installer_write"
        # ],
        # "site_id":"XXX",
        # "type":"config",
        # "key":"camerastatus.shutter.close",
        # "device_id":"XXX",
        # "message_id":"XXX"
        # }
        # {
        # "profiles":[
        #     "admin",
        #     "owner",
        #     "installer_write"
        # ],
        # "site_id":"XXX",
        # "type":"config",
        # "key":"camerastatus.shutter.open",
        # "device_id":"XXX",
        # "message_id":"XXX"
        # }

    def snapshot_ready(self, message):
        """Snapshot Ready"""
        # {
        # "profiles":[
        #     "owner"
        # ],
        # "site_id":"XXX",
        # "key":"snapshotready",
        # "snapshot_id":"XXX",
        # "device_id":"XXX",
        # "snapshot_url":"https:\/\/video-cdn.myfox.io\/camera_snapshot\/XXX\/XXX.XXX-s?Expires=1647629662&Signature=XXX-XXX~XXX~XXX~XXX~XXX-XXX~XXX~XXX&Key-Pair-Id=XXX",
        # "message_id":"XXX",
        # "type":"event"
        # }

    def box_update_progress(self, message):
        """Box Update Progress"""
        # {
        # "profiles":[
        #     "owner",
        #     "admin"
        # ],
        # "site_id":"XXX",
        # "type":"config",
        # "key":"box.update.progress",
        # "box_id":"XXX",
        # "progress":100,
        # "remaining":0,
        # "total":0,
        # "update":"no update",
        # "message_id":"XXX"
        # }

    def device_offline(self, message):
        """Device Offline"""
        # {
        # "profiles":[
        #     "owner",
        #     "admin"
        # ],
        # "site_id":"XXX",
        # "type":"event",
        # "key":"device.offline",
        # "device_id":"XXX",
        # "message_id":"XXX"
        # }

    def device_update_connect(self, message):
        """Device Update Connect"""
        # {
        # "profiles":[
        #     "owner",
        #     "admin"
        # ],
        # "site_id":"XXX",
        # "type":"config",
        # "key":"device.update.connect",
        # "device_type":"mss_plug",
        # "device_mac":"XXX",
        # "message_id":"XXX"
        # }

    def diagnosis_connection_online_camera(self, message):
        """Diagnosis Connection Online Camera"""
        # {
        # "profiles":[
        #     "owner",
        #     "admin"
        # ],
        # "site_id":"XXX",
        # "type":"event",
        # "key":"diagnosis.connection.online.camera",
        # "device_id":"XXX",
        # "message_id":"XXX"
        # }

    def diagnosis_connection_offline_camera(self, message):
        """Diagnosis Connection Offline Camera"""
        # {
        # "profiles":[
        #     "owner",
        #     "admin"
        # ],
        # "site_id":"XXX",
        # "type":"event",
        # "key":"diagnosis.connection.offline.camera",
        # "device_id":"XXX",
        # "message_id":"XX"
        # }
