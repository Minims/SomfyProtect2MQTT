"""Somfy Protect Websocket"""

import asyncio
import json
import logging
import queue
import ssl
import threading
import time
import uuid

import websocket
from business.mqtt import mqtt_publish, publish_snapshot_bytes
from constants import (
    SNAPSHOT_QUEUE_MAXSIZE,
    WEBSOCKET_IDLE_CLOSE_SECONDS,
    WEBSOCKET_PING_INTERVAL,
    WEBSOCKET_PING_TIMEOUT,
    WEBSOCKET_RECONNECT,
    WEBSOCKET_TIMEOUT,
)
from mqtt import MQTTClient
from oauthlib.oauth2 import MissingTokenError
from somfy_protect.api import SomfyProtectApi
from somfy_protect.sso import SomfyProtectSso, read_token_from_file
from somfy_protect.webrtc_handler import WebRTCHandler
from somfy_protect.websocket.handlers import alarm as alarm_handlers
from somfy_protect.websocket.handlers import device as device_handlers
from somfy_protect.websocket.handlers import video as video_handlers
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
        self.streaming_config = config.get("streaming")
        self.api = api
        self.sso = sso
        self.time = time.time()
        self._io_queue = queue.Queue(maxsize=SNAPSHOT_QUEUE_MAXSIZE)
        self._io_worker_stop = threading.Event()
        self._io_worker = threading.Thread(target=self._io_worker_loop, daemon=True)
        self._io_worker.start()

        # Initialize WebRTC handler
        self.webrtc_handler = WebRTCHandler(
            mqtt_client=mqtt_client,
            mqtt_config=self.mqtt_config,
            send_websocket_callback=self.send_websocket_message,
            streaming_config=self.streaming_config,
        )

        # Create a dedicated event loop for async operations in a separate thread
        self.loop = asyncio.new_event_loop()

        self.loop_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.loop_thread.start()

        if debug:
            websocket.enableTrace(True)
            LOGGER.debug("Opening websocket connection to {}".format(WEBSOCKET))
        self.token = self._load_token()
        websocket.setdefaulttimeout(WEBSOCKET_TIMEOUT)
        self._websocket = WebSocketApp(
            f"{WEBSOCKET}{self.token.get('access_token')}",
            on_open=self._on_open,
            on_message=self._on_message_wrapper,
            on_error=self._on_error,
            on_close=self._on_close,
            on_ping=self._on_ping,
            on_pong=self._on_pong,
        )

    def _run_event_loop(self):
        """Run the event loop in a dedicated thread"""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _load_token(self) -> dict:
        token = self.sso.oauth.token or read_token_from_file(self.sso.token_cache_path)
        if token and token.get("access_token"):
            if self._is_token_expired(token):
                LOGGER.info("Websocket token expired, refreshing")
                token = self.sso.refresh_tokens()
                self.sso.oauth.token = token
            return token
        try:
            token = self.sso.request_token()
        except MissingTokenError as e:
            LOGGER.error("Unable to request access token: {}".format(e))
            raise
        if self.sso.token_updater is not None:
            self.sso.token_updater(token)
        self.sso.oauth.token = token
        return token

    @staticmethod
    def _is_token_expired(token: dict, leeway_seconds: int = 60) -> bool:
        expires_at = token.get("expires_at")
        if not expires_at:
            return False
        try:
            expires_at = float(expires_at)
        except (TypeError, ValueError):
            return False
        return expires_at <= (time.time() + leeway_seconds)

    def _io_worker_loop(self) -> None:
        while not self._io_worker_stop.is_set():
            try:
                job = self._io_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if job is None:
                self._io_queue.task_done()
                break
            func, args, kwargs = job
            try:
                func(*args, **kwargs)
            except (OSError, RuntimeError, ValueError) as e:
                LOGGER.warning("IO task failed: {}".format(e))
            finally:
                self._io_queue.task_done()

    def _run_io_task(self, func, *args, **kwargs) -> None:
        try:
            self._io_queue.put_nowait((func, args, kwargs))
        except queue.Full:
            LOGGER.warning("IO task dropped: queue full")

    def _on_message_wrapper(self, _ws_app, message):
        """Wrapper to handle async on_message in sync context"""
        try:
            # Schedule coroutine on the persistent event loop
            future = asyncio.run_coroutine_threadsafe(self.on_message(_ws_app, message), self.loop)
            future.add_done_callback(self._log_message_processing_error)
        except (RuntimeError, ValueError) as e:
            LOGGER.error("Error in message wrapper: {}".format(e))

    @staticmethod
    def _log_message_processing_error(future):
        try:
            future.result()
        except (RuntimeError, ValueError) as e:
            LOGGER.error("Error while processing websocket message: {}".format(e))

    def run_forever(self):
        """Run Forever Loop"""
        LOGGER.info("Running Forever")
        self._websocket.run_forever(
            # dispatcher=rel,
            ping_timeout=WEBSOCKET_PING_TIMEOUT,
            ping_interval=WEBSOCKET_PING_INTERVAL,
            reconnect=WEBSOCKET_RECONNECT,
            sslopt={"cert_reqs": ssl.CERT_NONE},
        )

    def close(self):
        """Close Websocket Connection"""
        LOGGER.info("WebSocket Close")

        self._io_worker_stop.set()
        try:
            self._io_queue.put_nowait(None)
        except queue.Full:
            pass

        # Close websocket connection
        if self._websocket:
            self._websocket.close()

        # Cleanup WebRTC resources
        if hasattr(self, "webrtc_handler") and self.webrtc_handler:
            try:
                # Schedule cleanup on the event loop
                if hasattr(self, "loop") and self.loop and self.loop.is_running():
                    cleanup_future = asyncio.run_coroutine_threadsafe(self.webrtc_handler.cleanup(), self.loop)
                    cleanup_future.result(timeout=2)
            except (RuntimeError, ValueError) as e:
                LOGGER.error("Error cleaning up WebRTC handler: {}".format(e))
            except TimeoutError:
                LOGGER.warning("WebRTC cleanup timed out")

        # Stop the event loop
        if hasattr(self, "loop") and self.loop:
            try:
                if self.loop.is_running():
                    self.loop.call_soon_threadsafe(self.loop.stop)
                    # Wait for loop thread to finish
                    if hasattr(self, "loop_thread") and self.loop_thread:
                        self.loop_thread.join(timeout=2.0)
                # Close the loop
                if not self.loop.is_closed():
                    self.loop.close()
                LOGGER.info("Event loop closed successfully")
            except (RuntimeError, ValueError) as e:
                LOGGER.error("Error closing event loop: {}".format(e))

    def start_webrtc_stream(self, site_id: str, device_id: str, session_id: str | None = None):
        """Start a WebRTC video stream session"""
        if not session_id:
            session_id = str(uuid.uuid4()).replace("-", "").upper()

        message = {
            "site_id": site_id,
            "forward": True,
            "device_id": device_id,
            "key": "video.webrtc.start",
            "session_id": session_id,
        }
        self.send_websocket_message(message)
        LOGGER.info("Sent video.webrtc.start for device {}, session {}".format(device_id, session_id))
        return session_id

    def _on_ping(self, _ws_app, message):
        """Handle Ping Message"""
        LOGGER.debug("Ping Message: {}".format(message))

    def _on_pong(self, _ws_app, message):
        """Handle Pong Message"""
        LOGGER.debug("Pong Message: {}".format(message))
        self.time = time.time()
        if (time.time() - self.time) > WEBSOCKET_IDLE_CLOSE_SECONDS:
            self.close()

    async def on_message(self, _ws_app, message):
        """Handle New message received on WebSocket"""
        self.time = time.time()
        if "websocket.connection.ready" in message:
            LOGGER.info("Websocket Connection is READY")
            return

        if "websocket.error.token" in message:
            LOGGER.warning("Websocket token error, refreshing and reconnecting")
            try:
                self.token = self.sso.refresh_tokens()
                self.sso.oauth.token = self.token
            except (MissingTokenError, OSError, RuntimeError, ValueError) as e:
                LOGGER.error("Unable to refresh websocket token: {}".format(e))
            self._websocket.close()
            return

        logging.debug("Message: {}".format(message))

        try:
            message_json = json.loads(message)
        except json.JSONDecodeError:
            LOGGER.warning("Received non-JSON websocket message")
            return
        if not isinstance(message_json, dict):
            LOGGER.warning("Unexpected websocket payload type")
            return
        message_id = message_json.get("message_id")
        if not message_id:
            LOGGER.warning("Websocket message missing message_id")
            return
        callbacks = {
            "security.level.change": self._security_level_change,
            "alarm.trespass": self._alarm_trespass,
            "alarm.panic": self._alarm_panic,
            "alarm.domestic.fire": self._alarm_domestic_fire,
            "alarm.domestic.fire.end": self._alarm_domestic_fire_end,
            "alarm.end": self._alarm_end,
            "presence_out": self._update_keyfob_presence,
            "presence_in": self._update_keyfob_presence,
            "device.status": self._device_status,
            "video.stream.ready": self._video_stream_ready,
            "device.ring_door_bell": self._device_ring_door_bell,
            "device.missed_call": self._device_missed_call,
            "video.webrtc.offer": self._video_webrtc_offer,
            "video.webrtc.start": self._video_webrtc_start,
            "video.webrtc.session": self._video_webrtc_session,
            "video.webrtc.answer": self._video_webrtc_answer,
            "video.webrtc.candidate": self._video_webrtc_candidate,
            "video.webrtc.turn.config": self._video_webrtc_turn_config,
            "video.webrtc.keep_alive": self._video_webrtc_keep_alive,
            "video.webrtc.hang_up": self._video_webrtc_hang_up,
            "device.gate_triggered_from_mobile": self._device_gate_triggered_from_mobile,
            "device.gate_triggered_from_monitor": self._device_gate_triggered_from_monitor,
            "answered_call_from_monitor": self._device_answered_call_from_monitor,
            "answered_call_from_mobile": self._device_answered_call_from_mobile,
            "device.doorlock_triggered": self._device_doorlock_triggered,
        }

        ack = {
            "ack": True,
            "message_id": message_id,
            "client": "Android",
        }
        self.send_websocket_message(ack)
        self._default_message(message_json)
        message_key = message_json.get("key")
        if not message_key:
            LOGGER.debug("Websocket message missing key")
            return
        if message_key in callbacks:
            callback = callbacks[message_key]
            if asyncio.iscoroutinefunction(callback):
                await callback(message_json)
            else:
                callback(message_json)
        else:
            LOGGER.debug("Unknown message: {}".format(message))

    def _on_error(self, _ws_app, error):
        """Handle Websocket Errors"""
        LOGGER.error("Error in the websocket connection: {}".format(error))

    def _on_open(self, _ws_app):
        """Handle Websocket Open Connection"""
        LOGGER.info("Opened connection")

    def _on_close(self, _ws_app, close_status_code, close_msg):
        """Handle Websocket Close Connection"""
        LOGGER.info("Websocket on_close, status {} => {}".format(close_status_code, close_msg))
        if close_status_code is None and close_msg is None:
            expires_at = None
            if hasattr(self, "token") and isinstance(self.token, dict):
                expires_at = self.token.get("expires_at")
            LOGGER.info("Websocket closed without status, token expires_at: {}".format(expires_at))

    def _device_gate_triggered_from_monitor(self, message):
        """Gate Open from Monitor"""
        LOGGER.info("Gate Open from Monitor: {}".format(message))

    def _device_answered_call_from_mobile(self, message):
        """Answer Call from Mobile"""
        LOGGER.info("Answer Call from Mobile: {}".format(message))

    def _device_answered_call_from_monitor(self, message):
        """Answer Call from Monitor"""
        LOGGER.info("Answer Call from Monitor: {}".format(message))

    def _device_gate_triggered_from_mobile(self, message):
        """Gate Open from Mobile"""
        LOGGER.info("Gate Open from Mobile: {}".format(message))

    async def _video_webrtc_hang_up(self, message):
        """WEBRTC HangUP"""
        LOGGER.info("WEBRTC HangUp: {}".format(message))
        session_id = message.get("session_id")
        await self.webrtc_handler.close_session(session_id)

    def _video_webrtc_keep_alive(self, message):
        """WEBRTC KeepAlive"""
        LOGGER.info("WEBRTC KeepAlive: {}".format(message))
        site_id = message.get("site_id")
        device_id = message.get("device_id")
        session_id = message.get("session_id")
        if not site_id or not device_id or not session_id:
            LOGGER.warning("Missing keepalive identifiers")
            return
        keepalive = {
            "site_id": site_id,
            "device_id": device_id,
            "session_id": session_id,
            "forward": True,
            "key": "video.webrtc.keep_alive",
        }
        self.send_websocket_message(keepalive)

    def _video_webrtc_session(self, message):
        """WEBRTC Session"""
        LOGGER.info("WEBRTC Session: {}".format(message))

    async def _video_webrtc_offer(self, message):
        """WEBRTC Offer"""
        await self.webrtc_handler.handle_offer(message)

    def _video_webrtc_start(self, message):
        """WEBRTC Start - Initiates WebRTC session"""
        LOGGER.info("WEBRTC Start: {}".format(message))
        # When we receive this from server, it means session is starting
        # We should have already sent our start request

    def _video_webrtc_answer(self, message):
        """WEBRTC Answer"""
        LOGGER.info("WEBRTC Answer: {}".format(message))

    def _video_webrtc_turn_config(self, message):
        """WEBRTC Turn Config - Store TURN server configuration"""
        LOGGER.info("WEBRTC Turn Config: {}".format(message))
        session_id = message.get("session_id")
        turn_data = message.get("turn")
        self.webrtc_handler.store_turn_config(session_id, turn_data)

    async def _video_webrtc_candidate(self, message):
        """WEBRTC Candidate - Add remote ICE candidate from camera"""
        session_id = message.get("session_id")
        candidate_data = message.get("candidate")
        await self.webrtc_handler.add_remote_candidate(session_id, candidate_data)

    def _device_ring_door_bell(self, message):
        """Someone is ringing at the door."""
        device_handlers.device_ring_door_bell(self, message)

    def _publish_false_after_delay(self, topic: str, key: str, delay_seconds: int = 3) -> None:
        """Publish a false payload after a delay without blocking websocket handling."""
        time.sleep(delay_seconds)
        mqtt_publish(
            mqtt_client=self.mqtt_client,
            topic=topic,
            payload={key: "False"},
            retain=True,
        )

    def _device_missed_call(self, message):
        """Call missed."""
        device_handlers.device_missed_call(self, message)

    def _publish_snapshot_bytes(self, site_id: str, device_id: str, byte_arr: bytearray) -> None:
        payload = {
            "mqtt_client": self.mqtt_client,
            "mqtt_config": self.mqtt_config,
            "site_id": site_id,
            "device_id": device_id,
            "byte_arr": byte_arr,
        }
        publish_snapshot_bytes(**payload)

    def _video_stream_ready(self, message):
        """Handle video stream ready events.

        Args:
            message (dict): Websocket event payload.
        """
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
        video_handlers.video_stream_ready(self, message)

    def _stream_video_to_mqtt(self, site_id: str, device_id: str, stream_url: str) -> None:
        """Stream camera frames and publish snapshots to MQTT."""
        video_handlers.stream_video_to_mqtt(self, site_id, device_id, stream_url)

    def _device_doorlock_triggered(self, message):
        """Update Door Lock Triggered"""
        # {
        # "profiles":[
        #     "owner",
        #     "admin"
        # ],
        # "site_id":"XXX",
        # "type":"event",
        # "key":"device.doorlock_triggered",
        # "device_id":"XXX",
        # "door_lock_gateway_id":"XXX",
        # "door_lock_status":"unknown",
        # "message_id":"XXX"
        # }
        device_handlers.device_doorlock_triggered(self, message)

    def _update_keyfob_presence(self, message):
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
        device_handlers.update_keyfob_presence(self, message)

    def _security_level_change(self, message):
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
        alarm_handlers.security_level_change(self, message)

    def _alarm_trespass(self, message):
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
        alarm_handlers.alarm_trespass(self, message)

    def _alarm_panic(self, message):
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
        alarm_handlers.alarm_panic(self, message)

    def _alarm_domestic_fire(self, message):
        """Report Alarm Fire"""
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
        # "key":"alarm.domestic.fire",
        # "alarm_id":"XXX",
        # "alarm_type":"fire",
        # "devices":[
        #     "XXX"
        # ],
        # "start_at":"2025-01-31T13:19:33.000000Z",
        # "end_at":"None",
        # "message_id":"XXX"
        # }

        alarm_handlers.alarm_domestic_fire(self, message)

    def _alarm_domestic_fire_end(self, message):
        """Report Alarm Fire End"""
        alarm_handlers.alarm_domestic_fire_end(self, message)

    def _alarm_end(self, message):
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
        alarm_handlers.alarm_end(self, message)

    def _device_status(self, message):
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
        device_handlers.device_status(self, message)

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

    def _default_message(self, message):
        """Default Message"""
        LOGGER.info("[default] Read Message {}".format(message))
        mqtt_config = self.mqtt_config or {}
        topic_suffix = message.get("key")
        if not topic_suffix:
            LOGGER.debug("Skipping default publish: message has no key")
            return
        site_id = message.get("site_id")
        device_id = message.get("device_id")
        if not site_id:
            topic = f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{topic_suffix}"
        elif not device_id:
            topic = f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{topic_suffix}"
        else:
            topic = f"{mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/{topic_suffix}"
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

    def _device_firmware_update_fail(self, message):
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
        # "snapshot_url":"https:\/\/video-cdn.myfox.io\/camera_snapshot\/XXX\/XXX.XXX-s"
        #                 "?Expires=1647629662&Signature=XXX-XXX~XXX~XXX~XXX~XXX-XXX~XXX~XXX"
        #                 "&Key-Pair-Id=XXX",
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

    def _device_offline(self, message):
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

    def _device_update_connect(self, message):
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

    def send_websocket_message(self, message: dict):
        """Send a message via the WebSocket connection"""
        if self._websocket and self._websocket.sock and self._websocket.sock.connected:
            self._websocket.send(json.dumps(message))
            LOGGER.debug("Sent on Websocket: {}".format(message))
        else:
            LOGGER.warning("WebSocket is not connected. Unable to send message: {}".format(message))
