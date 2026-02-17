"""Somfy Protect Websocket"""

import asyncio
import json
import logging
import os
import queue
import ssl
import threading
import time
import uuid

import websocket
from business import update_visiophone_snapshot, write_to_media_folder
from business.mqtt import mqtt_publish, publish_snapshot_bytes, update_device, update_site
from business.streaming.camera import VideoCamera
from constants import (
    SNAPSHOT_QUEUE_MAXSIZE,
    WEBSOCKET_IDLE_CLOSE_SECONDS,
    WEBSOCKET_PING_INTERVAL,
    WEBSOCKET_PING_TIMEOUT,
    WEBSOCKET_RECONNECT,
    WEBSOCKET_TIMEOUT,
)
from homeassistant.ha_discovery import ALARM_STATUS
from mqtt import MQTTClient
from somfy_protect.api import SomfyProtectApi
from somfy_protect.sso import SomfyProtectSso
from somfy_protect.webrtc_handler import WebRTCHandler
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
        self._last_pong = self.time
        self._keepalive_future = None
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
        self.token = self.sso.request_token()
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

    async def _keepalive_loop(self):
        try:
            while True:
                if self._websocket and self._websocket.sock and self._websocket.sock.connected:
                    try:
                        self._websocket.sock.ping()
                    except (RuntimeError, ValueError) as e:
                        LOGGER.warning("WebSocket ping failed: {}".format(e))
                    if (time.time() - self._last_pong) > WEBSOCKET_PING_TIMEOUT:
                        LOGGER.warning("WebSocket ping timeout, closing connection")
                        self.close()
                        return
                await asyncio.sleep(WEBSOCKET_PING_INTERVAL)
        except asyncio.CancelledError:
            return

    def _start_keepalive(self) -> None:
        if self._keepalive_future is not None:
            return
        self._keepalive_future = asyncio.run_coroutine_threadsafe(self._keepalive_loop(), self.loop)

    def _stop_keepalive(self) -> None:
        if self._keepalive_future is None:
            return
        self._keepalive_future.cancel()
        self._keepalive_future = None

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
            future.result()  # Wait for completion
        except (RuntimeError, ValueError) as e:
            LOGGER.error("Error in message wrapper: {}".format(e))

    def run_forever(self):
        """Run Forever Loop"""
        self._websocket.run_forever(
            # dispatcher=rel,
            ping_timeout=WEBSOCKET_PING_TIMEOUT,
            ping_interval=WEBSOCKET_PING_INTERVAL,
            reconnect=WEBSOCKET_RECONNECT,
            sslopt={"cert_reqs": ssl.CERT_NONE},
        )
        LOGGER.info("Running Forever")

    def close(self):
        """Close Websocket Connection"""
        LOGGER.info("WebSocket Close")

        self._stop_keepalive()
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
                    asyncio.run_coroutine_threadsafe(self.webrtc_handler.cleanup(), self.loop)
                    # Give it a moment to clean up
                    time.sleep(0.5)
            except (RuntimeError, ValueError) as e:
                LOGGER.error("Error cleaning up WebRTC handler: {}".format(e))

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

    def start_webrtc_stream(self, site_id: str, device_id: str, session_id: str = None):
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
        self._last_pong = time.time()
        if (time.time() - self.time) > WEBSOCKET_IDLE_CLOSE_SECONDS:
            self.close()

    async def on_message(self, _ws_app, message):
        """Handle New message received on WebSocket"""
        if "websocket.connection.ready" in message:
            LOGGER.info("Websocket Connection is READY")
            return

        if "websocket.error.token" in message:
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
        self._last_pong = time.time()
        self._start_keepalive()

    def _on_close(self, _ws_app, close_status_code, close_msg):
        """Handle Websocket Close Connection"""
        LOGGER.info("Websocket on_close, status {} => {}".format(close_status_code, close_msg))

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
        site_id = message.get("site_id")
        device_id = message.get("device_id")
        if not site_id or not device_id:
            LOGGER.warning("Missing site_id or device_id for ring event")
            return
        mqtt_config = self.mqtt_config or {}
        LOGGER.info("Someone is ringing on {}".format(device_id))
        topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/ringing"
        payload = {"ringing": "True"}
        mqtt_publish(mqtt_client=self.mqtt_client, topic=topic, payload=payload, retain=True)
        time.sleep(3)
        payload = {"ringing": "False"}
        mqtt_publish(mqtt_client=self.mqtt_client, topic=topic, payload=payload, retain=True)
        snapshot_url = message.get("snapshot_url")
        if snapshot_url:
            LOGGER.info("Found a snapshot !")
            self._run_io_task(
                update_visiophone_snapshot,
                url=snapshot_url,
                site_id=site_id,
                device_id=device_id,
                mqtt_client=self.mqtt_client,
                mqtt_config=mqtt_config,
            )

    def _device_missed_call(self, message):
        """Call missed."""
        site_id = message.get("site_id")
        device_id = message.get("device_id")
        if not site_id or not device_id:
            LOGGER.warning("Missing site_id or device_id for missed call")
            return
        mqtt_config = self.mqtt_config or {}
        LOGGER.info("Someone has rang on {}".format(device_id))
        snapshot_cloudfront_url = message.get("snapshot_cloudfront_url")
        clip_cloudfront_url = message.get("clip_cloudfront_url")
        if snapshot_cloudfront_url:
            LOGGER.info("Found a snapshot !")
            self._run_io_task(
                update_visiophone_snapshot,
                url=snapshot_cloudfront_url,
                site_id=site_id,
                device_id=device_id,
                mqtt_client=self.mqtt_client,
                mqtt_config=mqtt_config,
            )
        if clip_cloudfront_url:
            LOGGER.info("Found Clip !")
            self._run_io_task(
                write_to_media_folder,
                url=clip_cloudfront_url,
                site_id=site_id,
                device_id=device_id,
                label=message.get("label") or device_id,
                event_id=message.get("event_id") or "unknown",
                occurred_at=message.get("occurred_at") or "unknown",
                media_type="video",
                mqtt_client=self.mqtt_client,
                mqtt_config=mqtt_config,
            )

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
                LOGGER.warning("Unable to create directory {}: {}".format(directory, exc))

        if self.streaming_config == "mqtt":
            LOGGER.info("Start MQTT Image")
            camera = VideoCamera(url=stream_url)
            frame = None
            while camera.is_opened():
                frame = camera.get_frame()
                if frame is None:
                    break
                byte_arr = bytearray(frame)
                self._publish_snapshot_bytes(site_id, device_id, byte_arr)
            camera.release()

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
        LOGGER.info("Update Door Lock Triggered")
        site_id = message.get("site_id")
        device_id = message.get("device_id")
        LOGGER.info(message)
        door_lock_status = message.get("door_lock_status", "unknown")
        if door_lock_status and door_lock_status != "unknown":
            payload = {"open_door": door_lock_status}
            topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/state"
            mqtt_publish(
                mqtt_client=self.mqtt_client,
                topic=topic,
                payload=payload,
                retain=True,
            )
        update_device(self.api, self.mqtt_client, self.mqtt_config, site_id, device_id)

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
        LOGGER.info("Update Alarm Status")
        site_id = message.get("site_id")
        security_level = message.get("security_level")
        payload = {"security_level": ALARM_STATUS.get(security_level, "disarmed")}
        topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/state"
        mqtt_publish(mqtt_client=self.mqtt_client, topic=topic, payload=payload, retain=True)

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
        LOGGER.info("Report Alarm Triggered")
        site_id = message.get("site_id")
        device_id = message.get("device_id")
        device_type = message.get("device_type")
        security_level = "triggered"
        if message.get("type") != "alarm":
            LOGGER.info("{} is not 'alarm'".format(message.get("type")))
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

        LOGGER.info("Report Alarm Fire")
        site_id = message.get("site_id")
        payload = {"smoke": "True"}
        for device_id in message.get("devices"):
            topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/fire"

            mqtt_publish(
                mqtt_client=self.mqtt_client,
                topic=topic,
                payload=payload,
                retain=True,
            )

    def _alarm_domestic_fire_end(self, message):
        """Report Alarm Fire End"""
        LOGGER.info("Report Alarm Fire")
        site_id = message.get("site_id")
        payload = {"smoke": "False"}
        for device_id in message.get("devices"):
            topic = f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/fire"

            mqtt_publish(
                mqtt_client=self.mqtt_client,
                topic=topic,
                payload=payload,
                retain=True,
            )

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
        LOGGER.info("Report Alarm Stop")
        site_id = message.get("site_id")
        update_site(self.api, self.mqtt_client, self.mqtt_config, site_id)

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
        site_id = message.get("site_id")
        device_id = message.get("device_id")
        LOGGER.info("It Seems the Door {} is moving".format(device_id))
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

    def _default_message(self, message):
        """Default Message"""
        LOGGER.info("[default] Read Message {}".format(message))
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
