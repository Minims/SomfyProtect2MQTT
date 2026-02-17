"""WebRTC Handler for Somfy Protect Cameras"""

import asyncio
import importlib
import json
import logging
import math
import os
import re
import tempfile
import threading
import time
from datetime import datetime
from fractions import Fraction
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from typing import Optional

# Suppress ffmpeg/libav warnings at C library level
import av
from aiortc import AudioStreamTrack, RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
from business.mqtt import publish_snapshot_bytes
from PIL import ImageDraw, ImageFont

# Set PyAV logging level to ERROR to suppress FFmpeg warnings
av.logging.set_level(av.logging.ERROR)

# Also suppress Python-level warnings for aiortc
logging.getLogger("libav.h264").setLevel(logging.CRITICAL)
logging.getLogger("libav.swscaler").setLevel(logging.CRITICAL)
logging.getLogger("aiortc.codecs.h264").setLevel(logging.ERROR)


class HLSHandler(BaseHTTPRequestHandler):
    """Serve HLS playlists and segments from memory."""

    handler: Optional["WebRTCHandler"] = None

    def log_message(self, *args, **_kwargs):
        """Suppress default HTTP server logs."""
        return

    def do_GET(self):
        """Handle playlist and segment requests."""
        return self._do_get()

    def _do_get(self):
        """Handle playlist and segment requests."""
        handler = self.__class__.handler
        if handler is None:
            self.send_error(404)
            return
        path_parts = self.path.strip("/").split("/")
        if len(path_parts) < 2:
            self.send_error(404)
            return
        device_id = path_parts[0]
        filename = path_parts[1]
        if device_id not in handler.hls_segments:
            self.send_error(404)
            return
        segments = handler.hls_segments[device_id]
        if filename == "playlist.m3u8":
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            playlist = segments.get("playlist", b"")
            self.wfile.write(playlist)
            return
        if filename.endswith(".ts"):
            if filename in segments:
                self.send_response(200)
                self.send_header("Content-Type", "video/mp2t")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(segments[filename])
            else:
                self.send_error(404)
            return
        self.send_error(404)


def _format_timestamp(timestamp: datetime) -> str:
    return timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _overlay_timestamp(frame: av.VideoFrame, timestamp: datetime) -> av.VideoFrame:
    text = _format_timestamp(timestamp)
    image = frame.to_image()
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    x, y = 8, 8
    shadow_offset = 1
    draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill="black")
    draw.text((x, y), text, font=font, fill="white")
    return av.VideoFrame.from_image(image)


LOGGER = logging.getLogger(__name__)


class SilenceAudioTrack(AudioStreamTrack):
    """Empty audio track that sends silence"""

    def __init__(self):
        super().__init__()
        self.sample_rate = 48000
        self.samples_per_frame = 960
        self._timestamp = 0
        self._start = None

    async def recv(self):
        if self._start is None:
            self._start = time.time()

        # Generate silence frame
        frame = av.AudioFrame(format="s16", layout="stereo", samples=self.samples_per_frame)
        frame.rate = self.sample_rate
        frame.pts = self._timestamp
        # Use Fraction to satisfy aiortc/av expectations for AVRational
        frame.time_base = Fraction(1, self.sample_rate)

        for plane in list(getattr(frame, "planes", [])):
            plane.update(bytes(plane.buffer_size))

        self._timestamp += self.samples_per_frame

        # Wait to maintain proper timing (20ms per frame at 48kHz/960 samples)
        await asyncio.sleep(0.02)

        return frame


class WebRTCHandler:
    """Handles WebRTC connections for Somfy Protect cameras"""

    def __init__(self, mqtt_client, mqtt_config, send_websocket_callback, streaming_config=None):
        """
        Initialize WebRTC handler

        Args:
            mqtt_client: MQTT client for publishing snapshots
            mqtt_config: MQTT configuration dict
            send_websocket_callback: Callback function to send WebSocket messages
            streaming_config: Streaming configuration ("mqtt", "go2rtc", etc.)
        """
        self.mqtt_client = mqtt_client
        self.mqtt_config = mqtt_config
        self.send_websocket = send_websocket_callback
        self.streaming_config = streaming_config
        self.peer_connections = {}
        self.turn_configs = {}
        self.active_tasks = set()  # Track all active asyncio tasks

        # HLS HTTP server for go2rtc
        self.hls_muxers = {}  # Store HLS muxers per device_id
        self.hls_segments = {}  # Store HLS segments and playlists per device_id
        self.hls_server = None
        self.hls_port = 8090
        self.hls_segment_duration = 3  # seconds per segment (longer reduces churn)

    def store_turn_config(self, session_id, turn_data):
        """Store TURN server configuration for a session"""
        if session_id and turn_data:
            self.turn_configs[session_id] = turn_data
            LOGGER.info(
                "Stored TURN config for session {}: {}".format(
                    session_id,
                    turn_data.get("url"),
                )
            )

    async def handle_offer(self, message):
        """
        Handle incoming WebRTC offer from camera

        Args:
            message: WebSocket message containing the offer
        """
        LOGGER.info("WEBRTC Offer: {}".format(message))

        device_id = message.get("device_id")
        site_id = message.get("site_id")
        session_id = message.get("session_id")
        offer_data = message.get("offer")
        offer_data_clean = str(offer_data).strip("^('").strip("',)$")
        offer_data_json = json.loads(offer_data_clean)
        sdp = offer_data_json.get("sdp")
        offer_type = offer_data_json.get("type")

        # Try to fix H264 decoding issues by forcing a common profile-level-id
        new_sdp_lines = []
        for line in sdp.splitlines():
            if line.startswith("a=fmtp:") and "H264" in line:
                LOGGER.info("Original H264 fmtp line: {}".format(line))
                # Force a common profile-level-id
                line = re.sub(r"profile-level-id=[^;]+", "profile-level-id=42e01f", line)
                LOGGER.info("Modified H264 fmtp line: {}".format(line))
            new_sdp_lines.append(line)
        sdp = "\r\n".join(new_sdp_lines)

        # Check if audio is present in the offer
        has_audio = any(line.startswith("m=audio") for line in sdp.splitlines())
        LOGGER.info("[SDP] Offer contains audio track: {}".format(has_audio))

        # Build ICE servers configuration
        ice_servers = [RTCIceServer(urls=["stun:stun.l.google.com:19302"])]

        # Add TURN server if available
        turn_config = self.turn_configs.get(session_id)
        if turn_config:
            turn_url = turn_config.get("url")
            turn_username = turn_config.get("username")
            turn_password = turn_config.get("password")
            if turn_url and turn_username and turn_password:
                ice_servers.append(RTCIceServer(urls=[turn_url], username=turn_username, credential=turn_password))
                LOGGER.info("Added TURN server: {}".format(turn_url))
        else:
            LOGGER.warning("No TURN config available for session {}".format(session_id))

        # Create peer connection
        pc = RTCPeerConnection(configuration=RTCConfiguration(iceServers=ice_servers))
        self.peer_connections[session_id] = pc

        # Setup event handlers
        self._setup_event_handlers(pc, session_id, site_id, device_id)

        # Set remote description
        offer = RTCSessionDescription(sdp=sdp, type=offer_type)
        await pc.setRemoteDescription(offer)

        # Add audio track - silence for MQTT, nothing for go2rtc (let it auto-negotiate)
        if self.streaming_config != "go2rtc":
            pc.addTrack(SilenceAudioTrack())
            LOGGER.info("[SDP] Added silence audio track (streaming_config={})".format(self.streaming_config))
        else:
            LOGGER.info("[SDP] No audio track added - go2rtc will receive only")

        # Create answer
        answer = await pc.createAnswer()

        # Modify SDP to use passive DTLS setup
        modified_sdp = answer.sdp.replace("a=setup:active", "a=setup:passive")
        answer = RTCSessionDescription(sdp=modified_sdp, type=answer.type)

        await pc.setLocalDescription(answer)

        # Wait for ICE gathering
        await self._wait_for_ice_gathering(pc)

        # Send answer and candidates
        await self._send_answer_and_candidates(pc, session_id)

    def _setup_event_handlers(self, pc, session_id, site_id, device_id):
        """Setup event handlers for peer connection"""

        @pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            LOGGER.info("ICE connection state is {}".format(pc.iceConnectionState))
            if pc.iceConnectionState == "failed":
                LOGGER.error("ICE connection failed")
                if session_id in self.peer_connections:
                    del self.peer_connections[session_id]
                await pc.close()
            elif pc.iceConnectionState == "connected":
                LOGGER.info("ICE connection established successfully!")

        @pc.on("icegatheringstatechange")
        async def on_icegatheringstatechange():
            LOGGER.info("ICE gathering state is {}".format(pc.iceGatheringState))

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            LOGGER.info("Connection state is {}".format(pc.connectionState))
            if pc.connectionState == "connected":
                LOGGER.info("WebRTC connection established")
            elif pc.connectionState == "failed":
                LOGGER.error("WebRTC connection failed")
                await pc.close()

        @pc.on("icecandidate")
        async def on_icecandidate(candidate):
            if candidate:
                LOGGER.info("New local ICE candidate generated: {}".format(candidate.candidate))
                self._send_ice_candidate(candidate, session_id)
            else:
                LOGGER.info("All local ICE candidates have been generated (end-of-candidates)")

        @pc.on("track")
        async def on_track(track):
            LOGGER.info("[TRACK] Received {} track (id={})".format(track.kind, track.id))
            if track.kind == "video":
                if self.streaming_config == "mqtt":
                    LOGGER.info("Video track started, processing frames and publishing to MQTT")
                    topic = (
                        f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/snapshot"
                    )
                    frame_skip_counter = 0
                    try:
                        while True:
                            try:
                                frame = await track.recv()
                                LOGGER.debug(
                                    "Video frame received: {}, size={}x{}".format(
                                        frame,
                                        frame.width,
                                        frame.height,
                                    )
                                )

                                # Convert frame to JPEG and publish to MQTT.
                                try:
                                    # Convert directly to PIL Image from native YUV format (more efficient)
                                    pil_img = frame.to_image()

                                    # Encode as JPEG
                                    buffer = BytesIO()
                                    pil_img.save(buffer, format="JPEG", quality=85)
                                    byte_arr = bytearray(buffer.getvalue())

                                    # Publish to MQTT
                                    snapshot_args = (
                                        self.mqtt_client,
                                        self.mqtt_config,
                                        site_id,
                                        device_id,
                                        byte_arr,
                                    )
                                    publish_snapshot_bytes(*snapshot_args)
                                    LOGGER.debug("Published frame to MQTT topic: {}".format(topic))
                                    frame_skip_counter = 0
                                except (OSError, ValueError, RuntimeError) as e:
                                    frame_skip_counter += 1
                                    # Skip frames with decoding errors (especially at start due to missing SPS/PPS)
                                    if frame_skip_counter <= 10:
                                        LOGGER.debug(
                                            "Skipping frame due to decoding error (attempt {}): {}".format(
                                                frame_skip_counter,
                                                e,
                                            )
                                        )
                                    else:
                                        LOGGER.error("Multiple frame decoding failures: {}".format(e))

                            except (OSError, ValueError, RuntimeError) as e:
                                LOGGER.error("Error receiving video frame: {}".format(e))
                                await asyncio.sleep(0.1)

                    except (OSError, ValueError, RuntimeError) as e:
                        LOGGER.error("Error receiving video frames: {}".format(e))

                elif self.streaming_config == "go2rtc":
                    LOGGER.info("Video track started, streaming HLS for go2rtc")

                    # Start HLS HTTP server if not already running
                    if self.hls_server is None:
                        self._start_hls_server(device_id)

                    # Initialize HLS muxer for this device
                    if device_id not in self.hls_muxers:
                        self._init_hls_muxer(device_id)

                    # Store video track and start reading
                    self.hls_muxers[device_id]["video_track"] = track
                    task = asyncio.create_task(self._read_video_frames(device_id, track))
                    self.active_tasks.add(task)
                    task.add_done_callback(self.active_tasks.discard)

                else:
                    LOGGER.info(
                        "Video track received but streaming_config is not 'mqtt' or 'go2rtc' (current: {})".format(
                            self.streaming_config
                        )
                    )
            elif track.kind == "audio":
                if self.streaming_config == "go2rtc":
                    LOGGER.info("[TRACK] Audio track received! Starting audio reader task")
                    # Initialize HLS muxer if not exists
                    if device_id not in self.hls_muxers:
                        LOGGER.info("[AUDIO] Creating new muxer for device {}".format(device_id))
                        self._init_hls_muxer(device_id)
                    else:
                        LOGGER.info("[AUDIO] Using existing muxer for device {}".format(device_id))

                    # Store audio track and start reading
                    self.hls_muxers[device_id]["audio_track"] = track
                    task = asyncio.create_task(self._read_audio_frames(device_id, track))
                    self.active_tasks.add(task)
                    task.add_done_callback(self.active_tasks.discard)
                else:
                    LOGGER.warning(
                        "[TRACK] Audio track received but streaming_config is '{}' (not 'go2rtc')".format(
                            self.streaming_config
                        )
                    )

        # ICE connection timeout checker
        async def check_ice_connection_state():
            for i in range(20):
                await asyncio.sleep(1)
                LOGGER.debug(
                    "ICE check ({}/20): iceConnectionState={}, connectionState={}".format(
                        i + 1,
                        pc.iceConnectionState,
                        pc.connectionState,
                    )
                )
                if pc.iceConnectionState in ["connected", "completed"]:
                    LOGGER.info("ICE connection successful!")
                    return
            if pc.iceConnectionState in ["new", "checking"]:
                LOGGER.warning(
                    "ICE connection timeout - state stuck at {}, closing connection".format(pc.iceConnectionState)
                )
                await pc.close()

        task = asyncio.create_task(check_ice_connection_state())
        self.active_tasks.add(task)
        task.add_done_callback(self.active_tasks.discard)

    async def _wait_for_ice_gathering(self, pc, max_wait=2):
        """Wait for ICE gathering to complete"""
        for _ in range(max_wait * 10):
            if pc.iceGatheringState == "complete":
                break
            await asyncio.sleep(0.1)
        LOGGER.info("ICE gathering state: {}".format(pc.iceGatheringState))

    async def _send_answer_and_candidates(self, pc, session_id):
        """Send SDP answer and ICE candidates separately (trickle ICE)"""
        answer_sdp = pc.localDescription.sdp
        answer_sdp_lines = answer_sdp.split("\r\n")
        answer_sdp_no_candidates = []

        # Strip candidates from SDP
        for line in answer_sdp_lines:
            if not line.startswith("a=candidate:") and line != "a=end-of-candidates":
                answer_sdp_no_candidates.append(line)

        clean_answer_sdp = "\r\n".join(answer_sdp_no_candidates)
        candidates_stripped = answer_sdp.count("a=candidate:")
        LOGGER.info("Stripped {} candidates from answer SDP".format(candidates_stripped))

        # Log SDP for debugging
        LOGGER.info("Full clean answer SDP:\n{}".format(clean_answer_sdp))

        if "a=setup:" in clean_answer_sdp:
            setup_line = [line for line in answer_sdp_no_candidates if "a=setup:" in line]
            LOGGER.info("DTLS setup in answer: {}".format(setup_line))

        # Send answer
        response = {
            "key": "video.webrtc.answer",
            "session_id": session_id,
            "answer": {"type": pc.localDescription.type, "sdp": clean_answer_sdp},
            "forward": True,
        }
        self.send_websocket(response)
        LOGGER.info("Answer sent")

        # Send ICE candidates separately
        sdp_lines = pc.localDescription.sdp.split("\r\n")
        current_mid = None
        mid_index = {}
        m_line_count = -1

        for line in sdp_lines:
            if line.startswith("m="):
                m_line_count += 1
            elif line.startswith("a=mid:"):
                current_mid = line.split("a=mid:")[1]
                mid_index[current_mid] = m_line_count
            elif line.startswith("a=candidate:"):
                candidate_str = line.split("a=")[1]
                if current_mid is not None:
                    candidate_msg = {
                        "key": "video.webrtc.candidate",
                        "session_id": session_id,
                        "candidate": {
                            "sdp": candidate_str,
                            "sdpMid": current_mid,
                            "sdpMLineIndex": mid_index.get(current_mid, 0),
                        },
                        "forward": True,
                    }
                    self.send_websocket(candidate_msg)
                    LOGGER.info(
                        "Sent ICE candidate for mid={}: {}...".format(
                            current_mid,
                            candidate_str[:50],
                        )
                    )

        LOGGER.info("All ICE candidates sent via trickle ICE")

    def _send_ice_candidate(self, candidate, session_id):
        """Send ICE candidate via WebSocket"""
        message = {
            "key": "video.webrtc.candidate",
            "session_id": session_id,
            "candidate": {
                "sdpMid": candidate.sdpMid,
                "sdpMLineIndex": candidate.sdpMLineIndex,
                "sdp": candidate.candidate,
            },
            "forward": True,
        }
        self.send_websocket(message)

    async def add_remote_candidate(self, session_id, candidate_data):
        """
        Add remote ICE candidate from camera

        Args:
            session_id: WebRTC session ID
            candidate_data: Candidate data from WebSocket message
        """
        if not session_id or not candidate_data:
            LOGGER.warning("Missing session_id or candidate data")
            return

        pc = self.peer_connections.get(session_id)
        if not pc:
            LOGGER.warning("No peer connection found for session {}".format(session_id))
            return

        try:
            candidate_sdp = candidate_data.get("sdp")
            if not candidate_sdp:
                LOGGER.warning("Missing candidate sdp for session {}".format(session_id))
                return
            rtc_transport = importlib.import_module("aiortc.rtcicetransport")
            candidate_factory = getattr(rtc_transport, "candidate_from_sdp")
            candidate = candidate_factory(candidate_sdp)
            candidate.sdpMid = candidate_data.get("sdpMid")
            candidate.sdpMLineIndex = candidate_data.get("sdpMLineIndex")
            await pc.addIceCandidate(candidate)
            LOGGER.info("Added remote ICE candidate: {}...".format(candidate_data.get("sdp", "")[:60]))
        except (ValueError, RuntimeError) as e:
            LOGGER.error("Failed to add remote ICE candidate: {}".format(e))

    async def close_session(self, session_id):
        """
        Close WebRTC session and cleanup

        Args:
            session_id: WebRTC session ID
        """
        if session_id and session_id in self.peer_connections:
            try:
                pc = self.peer_connections[session_id]
                await pc.close()
                del self.peer_connections[session_id]
                if session_id in self.turn_configs:
                    del self.turn_configs[session_id]
                LOGGER.info("Closed and removed peer connection for session {}".format(session_id))
            except (ValueError, RuntimeError) as e:
                LOGGER.error("Error closing peer connection: {}".format(e))

    async def cleanup(self):
        """
        Cleanup all WebRTC resources - peer connections, tasks, HLS server, etc.
        Should be called when shutting down the handler.
        """
        LOGGER.info("Starting WebRTC handler cleanup...")

        # Cancel all active tasks
        if hasattr(self, "active_tasks") and self.active_tasks:
            LOGGER.info("Cancelling {} active tasks".format(len(self.active_tasks)))
            for task in list(self.active_tasks):
                if not task.done():
                    task.cancel()
            # Wait for tasks to finish cancellation
            if self.active_tasks:
                await asyncio.gather(*self.active_tasks, return_exceptions=True)
            self.active_tasks.clear()

        # Close all peer connections
        if hasattr(self, "peer_connections") and self.peer_connections:
            LOGGER.info("Closing {} peer connections".format(len(self.peer_connections)))
            for session_id in list(self.peer_connections.keys()):
                try:
                    await self.close_session(session_id)
                except (ValueError, RuntimeError) as e:
                    LOGGER.error("Error closing session {}: {}".format(session_id, e))
            self.peer_connections.clear()

        # Clear TURN configs
        if hasattr(self, "turn_configs"):
            self.turn_configs.clear()

        # Clear HLS resources
        if hasattr(self, "hls_muxers"):
            self.hls_muxers.clear()
        if hasattr(self, "hls_segments"):
            self.hls_segments.clear()

        # Stop HLS server if running
        if hasattr(self, "hls_server") and self.hls_server:
            try:
                self.hls_server.shutdown()
                LOGGER.info("HLS server stopped")
            except (OSError, RuntimeError) as e:
                LOGGER.error("Error stopping HLS server: {}".format(e))

        LOGGER.info("WebRTC handler cleanup completed")

    def _start_hls_server(self, device_id=None):
        """Start HTTP server for HLS streaming"""
        HLSHandler.handler = self
        server = HTTPServer(("0.0.0.0", self.hls_port), HLSHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.hls_server = server
        if device_id:
            LOGGER.info(
                "HLS HTTP server started on http://0.0.0.0:{}/{}/playlist.m3u8".format(
                    self.hls_port,
                    device_id,
                )
            )
        else:
            LOGGER.info("HLS HTTP server started on http://0.0.0.0:{}/<device_id>/playlist.m3u8".format(self.hls_port))

    def _init_hls_muxer(self, device_id):
        """Initialize HLS muxer for a device"""
        # Create temporary directory for HLS segments
        temp_dir = tempfile.mkdtemp(prefix=f"hls_{device_id}_")

        self.hls_muxers[device_id] = {
            "temp_dir": temp_dir,
            "video_track": None,
            "audio_track": None,
            "video_queue": asyncio.Queue(maxsize=90),
            "audio_queue": asyncio.Queue(maxsize=90),
            "container": None,
            "video_stream": None,
            "audio_stream": None,
            "pending_video": None,
            "segment_index": 0,
            "segment_start_time": None,
            "current_segment_path": None,
            "frame_count": 0,
            "audio_pts": 0,
            "video_pts": 0,
            "video_ready": False,
            "audio_ready": False,
            "audio_failed": False,
            "stopped": False,
            "no_frame_retries": 0,
        }

        self.hls_segments[device_id] = {
            "playlist": b"",
        }

        # Start the muxer task
        task = asyncio.create_task(self._hls_muxer_task(device_id))
        self.active_tasks.add(task)
        task.add_done_callback(self.active_tasks.discard)

        LOGGER.info(
            "Initialized HLS muxer for device {device_id} in {temp_dir}. "
            "Playlist: http://0.0.0.0:{port}/{device_id}/playlist.m3u8".format(
                device_id=device_id,
                temp_dir=temp_dir,
                port=self.hls_port,
            )
        )

    async def _read_video_frames(self, device_id, track):
        """Read video frames and put them in the queue"""
        try:
            while True:
                frame = await track.recv()
                received_at = datetime.now()
                try:
                    muxer = self.hls_muxers.get(device_id)
                    if muxer:
                        muxer["video_queue"].put_nowait((frame, received_at))
                        muxer["video_ready"] = True
                except asyncio.QueueFull:
                    LOGGER.debug("Video queue full for {}, dropping frame".format(device_id))
        except MediaStreamError:
            muxer = self.hls_muxers.get(device_id)
            if muxer:
                muxer["stopped"] = True
            LOGGER.info("Video stream ended for device {}".format(device_id))
        except (OSError, RuntimeError, ValueError) as e:
            LOGGER.error("Error reading video frames: {}".format(e))

    async def _read_audio_frames(self, device_id, track):
        """Read audio frames and put them in the queue"""
        LOGGER.info("[AUDIO] Audio track started for device {}".format(device_id))
        try:
            first_frame = True
            audio_frame_count = 0
            error_count = 0

            while True:
                try:
                    frame = await asyncio.wait_for(track.recv(), timeout=2.0)
                    audio_frame_count += 1
                    error_count = 0  # Reset error counter on success

                    if first_frame:
                        LOGGER.info(
                            "[AUDIO] Receiving audio: {}, {}ch @ {}Hz".format(
                                frame.format.name,
                                frame.layout.channels,
                                frame.sample_rate,
                            )
                        )
                        first_frame = False

                    muxer = self.hls_muxers.get(device_id)
                    if muxer:
                        try:
                            muxer["audio_queue"].put_nowait(frame)
                            muxer["audio_ready"] = True
                        except asyncio.QueueFull:
                            pass  # Drop frame silently if queue is full

                except asyncio.TimeoutError:
                    error_count += 1
                    if error_count == 1:
                        LOGGER.warning("[AUDIO] No audio frames from camera for device {}".format(device_id))
                    await asyncio.sleep(0.5)

                except (MediaStreamError, OSError, RuntimeError, ValueError) as frame_error:
                    if isinstance(frame_error, MediaStreamError):
                        muxer = self.hls_muxers.get(device_id)
                        if muxer:
                            muxer["audio_failed"] = True
                        LOGGER.info("[AUDIO] Stream ended for device {}".format(device_id))
                        return
                    error_count += 1
                    # Log only every 100 errors to avoid spam
                    if error_count % 100 == 1:
                        LOGGER.warning(
                            "[AUDIO] Audio receive errors ({}x): {}".format(
                                error_count,
                                type(frame_error).__name__,
                            )
                        )
                    await asyncio.sleep(0.1)

                # If we hit many consecutive failures, mark audio_failed to avoid blocking video
                if error_count >= 200:
                    muxer = self.hls_muxers.get(device_id)
                    if muxer:
                        muxer["audio_failed"] = True
                    LOGGER.error(
                        "[AUDIO] Too many errors ({}), disabling audio for device {}".format(
                            error_count,
                            device_id,
                        )
                    )
                    return

        except (MediaStreamError, OSError, RuntimeError, ValueError) as e:
            if isinstance(e, MediaStreamError):
                muxer = self.hls_muxers.get(device_id)
                if muxer:
                    muxer["audio_failed"] = True
                LOGGER.info("[AUDIO] Stream ended for device {}".format(device_id))
                return
            LOGGER.error("[AUDIO] Fatal error in audio reader: {}".format(e))

    async def _hls_muxer_task(self, device_id):
        """Single task that muxes audio+video frames into HLS segments"""
        muxer = self.hls_muxers.get(device_id)
        if not muxer:
            return

        LOGGER.info("HLS muxer task started for device {}".format(device_id))

        try:
            # Wait for video track to arrive (mandatory) and audio (best effort)
            wait_start = time.time()
            while not muxer["video_ready"]:
                elapsed = time.time() - wait_start
                if elapsed > 5:
                    LOGGER.error("[TRACKS] Timeout waiting for video track (>{:.1f}s), aborting muxer".format(elapsed))
                    return
                await asyncio.sleep(0.1)

            # Give audio up to 5s but continue without it if absent
            wait_start = time.time()
            while not muxer["audio_ready"] and (time.time() - wait_start) < 5:
                await asyncio.sleep(0.1)

            LOGGER.info(
                "[TRACKS] Starting muxer - Video: {}, Audio: {}".format(
                    muxer["video_ready"],
                    muxer["audio_ready"],
                )
            )

            audio_no_stream_warns = 0

            while True:
                if muxer.get("stopped"):
                    return
                current_time = time.time()

                # Initialize segment if needed
                if muxer["container"] is None:
                    await self._create_hls_segment(device_id)
                    if muxer["container"] is None:
                        await asyncio.sleep(0.05)
                        continue

                # Check if we need to close current segment
                if (
                    muxer["segment_start_time"]
                    and (current_time - muxer["segment_start_time"]) >= self.hls_segment_duration
                ):
                    await self._close_hls_segment(device_id)
                    continue

                # Try to get frames from queues
                video_frame = None
                video_received_at = None
                audio_frame = None

                if muxer.get("pending_video"):
                    video_frame, video_received_at = muxer.pop("pending_video")

                try:
                    if video_frame is None:
                        video_item = muxer["video_queue"].get_nowait()
                        if isinstance(video_item, tuple):
                            video_frame, video_received_at = video_item
                        else:
                            video_frame = video_item
                            video_received_at = datetime.now()
                except asyncio.QueueEmpty:
                    pass

                try:
                    audio_frame = muxer["audio_queue"].get_nowait()
                except asyncio.QueueEmpty:
                    pass

                # Process frames
                if video_frame and muxer["video_stream"]:
                    try:
                        if video_received_at:
                            video_frame = _overlay_timestamp(video_frame, video_received_at)
                        # Monotonic PTS based on 30fps -> 90000/30 = 3000 ticks per frame
                        video_frame.pts = muxer.get("video_pts", 0)
                        muxer["video_pts"] = video_frame.pts + 3000
                        for packet in muxer["video_stream"].encode(video_frame):
                            muxer["container"].mux(packet)
                        muxer["frame_count"] += 1
                    except (OSError, RuntimeError, ValueError) as e:
                        LOGGER.warning("Error encoding video: {}".format(e))

                if audio_frame and muxer.get("audio_failed"):
                    # Drop audio frames silently if audio setup failed
                    continue

                if audio_frame and muxer["audio_stream"]:
                    try:
                        # Reformat audio if needed
                        if audio_frame.format.name != "s16":
                            LOGGER.debug("[AUDIO] Reformatting from {} to s16".format(audio_frame.format.name))
                            audio_frame = audio_frame.reformat(format="s16")

                        audio_frame.pts = muxer.get("audio_pts", 0)
                        muxer["audio_pts"] = audio_frame.pts + (audio_frame.samples or 0)

                        packets = list(muxer["audio_stream"].encode(audio_frame))
                        if packets:
                            for packet in packets:
                                muxer["container"].mux(packet)
                            LOGGER.debug("[AUDIO] Encoded frame into {} packets".format(len(packets)))
                        else:
                            LOGGER.debug("[AUDIO] No packets produced")
                    except (OSError, RuntimeError, ValueError) as e:
                        LOGGER.error("[AUDIO] Encoding error: {}".format(e), exc_info=True)
                elif audio_frame and not muxer["audio_stream"]:
                    audio_no_stream_warns += 1
                    if audio_no_stream_warns == 1 or audio_no_stream_warns % 200 == 0:
                        LOGGER.warning("[AUDIO] Frame available but no audio stream created yet")

                # Small sleep to prevent CPU spinning
                if not video_frame and not audio_frame:
                    await asyncio.sleep(0.001)

        except (OSError, RuntimeError, ValueError) as e:
            LOGGER.error("Error in HLS muxer task: {}".format(e))
            LOGGER.exception("Details:")

    async def _create_hls_segment(self, device_id):
        """Create a new HLS segment"""
        muxer = self.hls_muxers.get(device_id)
        if not muxer:
            return

        segment_index = muxer["segment_index"]
        segment_filename = f"segment{segment_index}.ts"
        segment_path = f"{muxer['temp_dir']}/{segment_filename}"

        # Create container
        container = av.open(segment_path, "w", format="mpegts")

        # Add video stream if ready
        if muxer["video_ready"]:
            try:
                # Wait up to 1 second for a video frame to get correct dimensions
                video_frame = None
                video_received_at = None
                wait_count = 0
                while wait_count < 100 and not video_frame:
                    try:
                        video_item = muxer["video_queue"].get_nowait()
                        if isinstance(video_item, tuple):
                            video_frame, video_received_at = video_item
                        else:
                            video_frame = video_item
                            video_received_at = datetime.now()
                    except asyncio.QueueEmpty:
                        await asyncio.sleep(0.01)
                        wait_count += 1

                if not video_frame:
                    LOGGER.warning("Video ready but no frame available to start segment; retrying later")
                    muxer["no_frame_retries"] += 1
                    muxer["container"] = None
                    await asyncio.sleep(min(0.5, 0.05 * muxer["no_frame_retries"]))
                    return
                muxer["no_frame_retries"] = 0

                width = video_frame.width
                height = video_frame.height

                # Force a stable framerate to avoid mis-detected 120fps and segment glitches
                fps = 30.0
                gop = int(self.hls_segment_duration * fps)
                LOGGER.debug(
                    "[VIDEO] Creating video stream {}x{} @ {:.2f}fps (gop={})".format(
                        width,
                        height,
                        fps,
                        gop,
                    )
                )

                video_stream = container.add_stream("libx264", rate=fps)
                video_stream.width = width
                video_stream.height = height
                video_stream.pix_fmt = "yuv420p"
                video_stream.time_base = Fraction(1, 90000)
                video_stream.options = {
                    "preset": "ultrafast",
                    "tune": "zerolatency",
                    "g": str(gop),
                    "keyint": str(gop),
                    "min-keyint": str(gop),
                    "scenecut": "0",
                    "bf": "0",
                    "bframes": "0",
                    "x264-params": (
                        f"keyint={gop}:min-keyint={gop}:scenecut=0:open-gop=0:force-idr=1:aud=1:force-cfr=1"
                    ),
                }
                muxer["video_stream"] = video_stream

                # Hold the first frame so it can be encoded after stream setup
                if video_frame is not None:
                    muxer["pending_video"] = (video_frame, video_received_at)
            except (OSError, RuntimeError, ValueError) as e:
                LOGGER.warning("Error adding video stream: {}".format(e))
                muxer["container"] = None
                return

        # Add audio stream if ready and not previously failed
        if muxer["audio_ready"] and not muxer.get("audio_failed"):
            try:
                # Wait up to 1 second for an audio frame to get correct parameters
                audio_frame = None
                wait_count = 0
                while wait_count < 100 and not audio_frame:
                    try:
                        audio_frame = muxer["audio_queue"].get_nowait()
                    except asyncio.QueueEmpty:
                        await asyncio.sleep(0.01)
                        wait_count += 1

                if audio_frame:
                    num_channels = len(audio_frame.layout.channels)
                    sample_rate = audio_frame.sample_rate
                    LOGGER.debug(
                        "[AUDIO] Creating audio stream: {}ch @ {}Hz".format(
                            num_channels,
                            sample_rate,
                        )
                    )

                    try:
                        audio_stream = container.add_stream("aac", rate=sample_rate)
                        audio_stream.channels = num_channels
                        audio_stream.time_base = Fraction(1, sample_rate)
                        muxer["audio_stream"] = audio_stream
                    except (OSError, RuntimeError, ValueError):
                        # Fallback to MP3 if AAC fails
                        try:
                            audio_stream = container.add_stream("libmp3lame", rate=sample_rate)
                            audio_stream.channels = num_channels
                            audio_stream.time_base = Fraction(1, sample_rate)
                            muxer["audio_stream"] = audio_stream
                            LOGGER.info("[AUDIO] Using MP3 codec (AAC unavailable)")
                        except (OSError, RuntimeError, ValueError) as e:
                            LOGGER.error("[AUDIO] Failed to create audio stream: {}".format(e))
                            muxer["audio_stream"] = None
                            muxer["audio_failed"] = True

                    # Put the frame back in the queue
                    if muxer["audio_stream"]:
                        muxer["audio_queue"].put_nowait(audio_frame)
            except (OSError, RuntimeError, ValueError) as e:
                LOGGER.error("[AUDIO] Error adding audio stream: {}".format(e))
                muxer["audio_failed"] = True

        muxer["container"] = container
        muxer["current_segment_path"] = segment_path
        muxer["segment_start_time"] = time.time()
        muxer["segment_index"] += 1
        muxer["frame_count"] = 0

    async def _close_hls_segment(self, device_id):
        """Close current HLS segment and update playlist"""
        muxer = self.hls_muxers.get(device_id)
        if not muxer or not muxer["container"]:
            return

        try:
            # Flush encoders
            if muxer["video_stream"]:
                video_packets = list(muxer["video_stream"].encode(None))
                for packet in video_packets:
                    muxer["container"].mux(packet)
                LOGGER.debug("[VIDEO] Flushed {} packets".format(len(video_packets)))

            if muxer["audio_stream"]:
                audio_packets = list(muxer["audio_stream"].encode(None))
                for packet in audio_packets:
                    muxer["container"].mux(packet)

            # Close container
            muxer["container"].close()

            # Debug segment stats to trace freezes
            LOGGER.debug(
                "[HLS] Closed segment {} with {} video frames".format(
                    muxer["segment_index"] - 1,
                    muxer["frame_count"],
                )
            )

            # Update playlist (offload disk IO)
            await asyncio.to_thread(self._update_hls_playlist, device_id)

            # Reset for next segment
            muxer["container"] = None
            muxer["video_stream"] = None
            muxer["audio_stream"] = None
            muxer["segment_start_time"] = None

        except (OSError, RuntimeError, ValueError) as e:
            LOGGER.error("Error closing HLS segment: {}".format(e))

    def _update_hls_playlist(self, device_id):
        """Update HLS playlist for a device"""
        muxer = self.hls_muxers.get(device_id)
        if not muxer:
            return

        # Keep only last 8 segments in memory (short window to reduce latency)
        max_segments = 8
        segment_index = muxer["segment_index"]
        start_index = max(0, segment_index - max_segments)

        # Build playlist for live streaming
        target_duration = max(1, int(math.ceil(self.hls_segment_duration)))
        playlist = "#EXTM3U\n"
        playlist += "#EXT-X-VERSION:3\n"
        playlist += "#EXT-X-INDEPENDENT-SEGMENTS\n"
        playlist += "#EXT-X-PLAYLIST-TYPE:EVENT\n"
        playlist += f"#EXT-X-TARGETDURATION:{target_duration}\n"
        playlist += f"#EXT-X-MEDIA-SEQUENCE:{start_index}\n"

        # Load segments into memory
        segment_count = 0
        for i in range(start_index, segment_index):
            segment_filename = f"segment{i}.ts"
            segment_path = f"{muxer['temp_dir']}/{segment_filename}"

            if os.path.exists(segment_path):
                # Load segment into memory
                with open(segment_path, "rb") as f:
                    segment_data = f.read()
                    if len(segment_data) > 0:  # Only add non-empty segments
                        self.hls_segments[device_id][segment_filename] = segment_data
                        playlist += f"#EXTINF:{self.hls_segment_duration:.1f},\n"
                        playlist += f"{segment_filename}\n"
                        segment_count += 1

        self.hls_segments[device_id]["playlist"] = playlist.encode("utf-8")
        LOGGER.debug("Updated playlist for {} with {} segments".format(device_id, segment_count))

        # Clean up old segments from disk and memory
        for i in range(max(0, start_index - 10), start_index):
            old_segment_filename = f"segment{i}.ts"
            old_segment_path = f"{muxer['temp_dir']}/{old_segment_filename}"

            # Remove from disk
            if os.path.exists(old_segment_path):
                try:
                    os.remove(old_segment_path)
                except OSError as e:
                    LOGGER.debug("Unable to remove old segment {}: {}".format(old_segment_path, e))

            # Remove from memory
            if old_segment_filename in self.hls_segments[device_id]:
                del self.hls_segments[device_id][old_segment_filename]
