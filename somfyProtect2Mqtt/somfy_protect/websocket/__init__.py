"""Somfy Protect Websocket"""

import base64
import json
import logging
import os
import ssl
import time
from signal import SIGKILL

import websocket
from business import update_visiophone_snapshot, write_to_media_folder
from business.mqtt import mqtt_publish, update_device, update_site
from business.streaming.camera import VideoCamera
from homeassistant.ha_discovery import ALARM_STATUS
from mqtt import MQTTClient, init_mqtt
from oauthlib.oauth2 import LegacyApplicationClient, TokenExpiredError
from requests_oauthlib import OAuth2Session
from somfy_protect.api import SomfyProtectApi
from somfy_protect.sso import SomfyProtectSso, read_token_from_file
from websocket import WebSocketApp
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate

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
        self.streaming_config = config.get("streaming")
        self.api = api
        self.sso = sso
        self.time = time.time()

        if debug:
            websocket.enableTrace(True)
            LOGGER.debug(f"Opening websocket connection to {WEBSOCKET}")
        self.token = self.sso.request_token()
        websocket.setdefaulttimeout(5)
        self._websocket = WebSocketApp(
            f"{WEBSOCKET}{self.token.get('access_token')}",
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_ping=self.on_ping,
            on_pong=self.on_pong,
        )

    def run_forever(self):
        """Run Forever Loop"""
        self._websocket.run_forever(
            # dispatcher=rel,
            ping_timeout=10,
            ping_interval=15,
            reconnect=5,
            sslopt={"cert_reqs": ssl.CERT_NONE},
        )
        LOGGER.info("Running Forever")

    def close(self):
        """Close Websocket Connection"""
        LOGGER.info("WebSocket Close")
        self._websocket.close()

    def on_ping(self, ws_app, message):
        """Handle Ping Message"""
        LOGGER.debug(f"Ping Message: {message}")

    def on_pong(self, ws_app, message):
        """Handle Pong Message"""
        LOGGER.debug(f"Pong Message: {message}")
        if (time.time() - self.time) > 1800:
            self.close()

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
            "video.stream.ready": self.video_stream_ready,
            "device.ring_door_bell": self.device_ring_door_bell,
            "device.missed_call": self.device_missed_call,
            "video.webrtc.offer": self.video_webrtc_offer,
            "video.webrtc.start": self.video_webrtc_start,
            "video.webrtc.session": self.video_webrtc_session,
            "video.webrtc.answer": self.video_webrtc_answer,
            "video.webrtc.candidate": self.video_webrtc_candidate,
            "video.webrtc.turn.config": self.video_webrtc_turn_config,
            "video.webrtc.keep_alive": self.video_webrtc_keep_alive,
            "video.webrtc.hang_up": self.video_webrtc_hang_up,
            "device.gate_triggered_from_mobile": self.device_gate_triggered_from_mobile,
            "device.gate_triggered_from_monitor": self.device_gate_triggered_from_monitor,
            "answered_call_from_monitor": self.device_answered_call_from_monitor,
            "answered_call_from_mobile": self.device_answered_call_from_mobile,
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

    def on_error(self, ws_app, error):  # pylint: disable=unused-argument,no-self-use
        """Handle Websocket Errors"""
        LOGGER.error(f"Error in the websocket connection: {error}")

    def on_open(self, ws_app):
        """Handle Websocket Open Connection"""
        LOGGER.info("Opened connection")

    def on_close(self, ws_app, close_status_code, close_msg):  # pylint: disable=unused-argument,no-self-use
        """Handle Websocket Close Connection"""
        LOGGER.info(f"Websocket on_close, status {close_status_code} => {close_msg}")

    def device_gate_triggered_from_monitor(self, message):
        """Gate Open from Monitor"""
        LOGGER.info(f"Gate Open from Monitor: {message}")

    def device_answered_call_from_mobile(self, message):
        """Answer Call from Mobile"""
        LOGGER.info(f"Answer Call from Mobile: {message}")

    def device_answered_call_from_monitor(self, message):
        """Answer Call from Monitor"""
        LOGGER.info(f"Answer Call from Monitor: {message}")

    def device_gate_triggered_from_mobile(self, message):
        """Gate Open from Mobile"""
        LOGGER.info(f"Gate Open from Mobile: {message}")

    def video_webrtc_hang_up(self, message):
        """WEBRTC HangUP"""
        LOGGER.info(f"WEBRTC HangUp: {message}")

    def video_webrtc_keep_alive(self, message):
        """WEBRTC KeepAlive"""
        LOGGER.info(f"WEBRTC KeepAlive: {message}")

    def video_webrtc_session(self, message):
        """WEBRTC Session"""
        LOGGER.info(f"WEBRTC Session: {message}")

    async def video_webrtc_offer(self, message):
        """WEBRTC Offer"""
        LOGGER.info(f"WEBRTC Offer: {message}")
        device_id = message.get("device_id")
        offer_data = message.get("offer")
        offer_data_clean = str(offer_data).strip("^('").strip("',)$")
        offer_data_json = json.loads(offer_data_clean)
        sdp = offer_data_json.get("sdp")
        LOGGER.info(f"WEBRTC SDP: {sdp}")

        directory = "/config/somfyprotect2mqtt"
        try:
            os.makedirs(directory, exist_ok=True)
            with open(f"{directory}/visiophone_webrtc_sdp_{device_id}", "w", encoding="utf-8") as file:
                file.write(sdp)
        except OSError as exc:
            LOGGER.warning(f"Unable to create directory {directory}: {exc}")

        offer_type = offer_data_json.get("type")
        pc = RTCPeerConnection()
        offer = RTCSessionDescription(sdp=sdp, type=offer_type)
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        response = {
            "type": "video.webrtc.answer",
            "session_id": message.get("session_id"),
            "answer": {"type": pc.localDescription.type, "sdp": pc.localDescription.sdp},
        }
        send = self._websocket.send(json.dumps(response))
        LOGGER.debug(send)

    def video_webrtc_start(self, message):
        """WEBRTC Start"""
        LOGGER.info(f"WEBRTC Start: {message}")

    def video_webrtc_answer(self, message):
        """WEBRTC Answer"""
        LOGGER.info(f"WEBRTC Answer: {message}")

    def video_webrtc_turn_config(self, message):
        """WEBRTC Turn Config"""
        LOGGER.info(f"WEBRTC Turn Config: {message}")

    def video_webrtc_candidate(self, message):
        """WEBRTC Candidate"""
        LOGGER.info(f"WEBRTC Candidate: {message}")

    def device_ring_door_bell(self, message):
        """Someone is ringing at the door."""
        site_id = message.get("site_id")
        device_id = message.get("device_id")
        LOGGER.info(f"Someone is ringing on {device_id}")
        topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/ringing"
        payload = {"ringing": "True"}
        mqtt_publish(mqtt_client=self.mqtt_client, topic=topic, payload=payload, retain=True)
        time.sleep(3)
        payload = {"ringing": "False"}
        mqtt_publish(mqtt_client=self.mqtt_client, topic=topic, payload=payload, retain=True)
        snapshot_url = message.get("snapshot_url")
        if snapshot_url:
            LOGGER.info("Found a snapshot !")
            update_visiophone_snapshot(
                url=snapshot_url,
                site_id=site_id,
                device_id=device_id,
                mqtt_client=self.mqtt_client,
                mqtt_config=self.mqtt_config,
            )

    def device_missed_call(self, message):
        """Call missed."""
        site_id = message.get("site_id")
        device_id = message.get("device_id")
        LOGGER.info(f"Someone has rang on {device_id}")
        snapshot_cloudfront_url = message.get("snapshot_cloudfront_url")
        clip_cloudfront_url = message.get("clip_cloudfront_url")
        if snapshot_cloudfront_url:
            LOGGER.info("Found a snapshot !")
            update_visiophone_snapshot(
                url=snapshot_cloudfront_url,
                site_id=site_id,
                device_id=device_id,
                mqtt_client=self.mqtt_client,
                mqtt_config=self.mqtt_config,
            )
        if clip_cloudfront_url:
            LOGGER.info("Found Clip !")
            write_to_media_folder(url=clip_cloudfront_url)

    def video_stream_ready(self, message):
        # {
        #    "profiles":[
        #       "owner"
        #    ],
        #    "site_id":"XXX",
        #    "key":"video.stream.ready",
        #    "stream_url":"URL",
        #    "device_id":"XXX",
        #    "type":"event",
        #    "message_id":"XXX"
        # }
        LOGGER.info("Stream URL Found")
        LOGGER.info(message)
        site_id = message.get("site_id")
        device_id = message.get("device_id")
        stream_url = message.get("stream_url")
        payload = stream_url
        topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/stream"

        mqtt_publish(
            mqtt_client=self.mqtt_client,
            topic=topic,
            payload=payload,
            retain=False,
        )

        if self.streaming_config == "go2rtc":
            directory = "/config/somfyprotect2mqtt"
            try:
                os.makedirs(directory, exist_ok=True)
                with open(f"{directory}/stream_url_{device_id}", "w", encoding="utf-8") as file:
                    file.write(stream_url)
            except OSError as exc:
                LOGGER.warning(f"Unable to create directory {directory}: {exc}")

        if self.streaming_config == "mqtt":
            LOGGER.info("Start MQTT Image")
            camera = VideoCamera(url=stream_url)
            frame = None
            while camera.is_opened():
                frame = camera.get_frame()
                if frame is None:
                    break
                byte_arr = bytearray(frame)
                topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/snapshot"
                mqtt_publish(
                    mqtt_client=self.mqtt_client,
                    topic=topic,
                    payload=byte_arr,
                    retain=True,
                    is_json=False,
                    qos=2,
                )
            camera.release()

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
        payload = {"security_level": ALARM_STATUS.get(security_level, "disarmed")}
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
