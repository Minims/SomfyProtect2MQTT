"""WebRTC Handler for Somfy Protect Cameras"""

import asyncio
import json
import logging
import re
from fractions import Fraction
from io import BytesIO

from aiortc import (
    AudioStreamTrack,
    RTCConfiguration,
    RTCIceCandidate,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)
from business.mqtt import mqtt_publish

# Suppress ffmpeg/libav warnings at C library level
import av

# Set PyAV logging level to ERROR to suppress FFmpeg warnings
av.logging.set_level(av.logging.ERROR)

# Also suppress Python-level warnings for aiortc
logging.getLogger("libav.h264").setLevel(logging.CRITICAL)
logging.getLogger("libav.swscaler").setLevel(logging.CRITICAL)
logging.getLogger("aiortc.codecs.h264").setLevel(logging.ERROR)

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
        import av
        import time

        if self._start is None:
            self._start = time.time()

        # Generate silence frame
        frame = av.AudioFrame(format="s16", layout="stereo", samples=self.samples_per_frame)
        frame.rate = self.sample_rate
        frame.pts = self._timestamp
        # Use Fraction to satisfy aiortc/av expectations for AVRational
        frame.time_base = Fraction(1, self.sample_rate)

        for p in frame.planes:
            p.update(bytes(p.buffer_size))

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
        self.hls_segment_duration = 1  # seconds per segment (shorter to reduce boundary stalls)

    def store_turn_config(self, session_id, turn_data):
        """Store TURN server configuration for a session"""
        if session_id and turn_data:
            self.turn_configs[session_id] = turn_data
            LOGGER.info(f"Stored TURN config for session {session_id}: {turn_data.get('url')}")

    async def handle_offer(self, message):
        """
        Handle incoming WebRTC offer from camera

        Args:
            message: WebSocket message containing the offer
        """
        LOGGER.info(f"WEBRTC Offer: {message}")

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
                LOGGER.info("Original H264 fmtp line: %s", line)
                # Force a common profile-level-id
                line = re.sub(r"profile-level-id=[^;]+", "profile-level-id=42e01f", line)
                LOGGER.info("Modified H264 fmtp line: %s", line)
            new_sdp_lines.append(line)
        sdp = "\r\n".join(new_sdp_lines)

        # Check if audio is present in the offer
        has_audio = any(line.startswith("m=audio") for line in sdp.splitlines())
        LOGGER.info(f"[SDP] Offer contains audio track: {has_audio}")

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
                LOGGER.info(f"Added TURN server: {turn_url}")
        else:
            LOGGER.warning(f"No TURN config available for session {session_id}")

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
            LOGGER.info(f"[SDP] Added silence audio track (streaming_config={self.streaming_config})")
        else:
            LOGGER.info(f"[SDP] No audio track added - go2rtc will receive only")

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
            LOGGER.info(f"ICE connection state is {pc.iceConnectionState}")
            if pc.iceConnectionState == "failed":
                LOGGER.error("ICE connection failed")
                if session_id in self.peer_connections:
                    del self.peer_connections[session_id]
                await pc.close()
            elif pc.iceConnectionState == "connected":
                LOGGER.info("ICE connection established successfully!")

        @pc.on("icegatheringstatechange")
        async def on_icegatheringstatechange():
            LOGGER.info(f"ICE gathering state is {pc.iceGatheringState}")

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            LOGGER.info(f"Connection state is {pc.connectionState}")
            if pc.connectionState == "connected":
                LOGGER.info("WebRTC connection established")
            elif pc.connectionState == "failed":
                LOGGER.error("WebRTC connection failed")
                await pc.close()

        @pc.on("icecandidate")
        async def on_icecandidate(candidate):
            if candidate:
                LOGGER.info(f"New local ICE candidate generated: {candidate.candidate}")
                self._send_ice_candidate(candidate, session_id)
            else:
                LOGGER.info("All local ICE candidates have been generated (end-of-candidates)")

        @pc.on("track")
        async def on_track(track):
            LOGGER.info(f"[TRACK] Received {track.kind} track (id={track.id})")
            if track.kind == "video":
                if self.streaming_config == "mqtt":
                    LOGGER.info(f"Video track started, processing frames and publishing to MQTT")
                    topic = (
                        f"{self.mqtt_config.get('topic_prefix', 'somfyProtect2mqtt')}/{site_id}/{device_id}/snapshot"
                    )
                    frame_skip_counter = 0
                    try:
                        while True:
                            try:
                                frame = await track.recv()
                                LOGGER.debug(f"Video frame received: {frame}, size={frame.width}x{frame.height}")

                                # Convert frame to JPEG and publish to MQTT.
                                try:
                                    from PIL import Image

                                    # Convert directly to PIL Image from native YUV format (more efficient)
                                    pil_img = frame.to_image()

                                    # Encode as JPEG
                                    buffer = BytesIO()
                                    pil_img.save(buffer, format="JPEG", quality=85)
                                    byte_arr = bytearray(buffer.getvalue())

                                    # Publish to MQTT
                                    mqtt_publish(
                                        mqtt_client=self.mqtt_client,
                                        topic=topic,
                                        payload=byte_arr,
                                        retain=True,
                                        is_json=False,
                                        qos=2,
                                    )
                                    LOGGER.debug(f"Published frame to MQTT topic: {topic}")
                                    frame_skip_counter = 0
                                except Exception as e:
                                    frame_skip_counter += 1
                                    # Skip frames with decoding errors (especially at start due to missing SPS/PPS)
                                    if frame_skip_counter <= 10:
                                        LOGGER.debug(
                                            f"Skipping frame due to decoding error (attempt {frame_skip_counter}): {e}"
                                        )
                                    else:
                                        LOGGER.error(f"Multiple frame decoding failures: {e}")

                            except Exception as e:
                                LOGGER.error(f"Error receiving video frame: {e}")
                                await asyncio.sleep(0.1)

                    except Exception as e:
                        LOGGER.error(f"Error receiving video frames: {e}")

                elif self.streaming_config == "go2rtc":
                    LOGGER.info(f"Video track started, streaming HLS for go2rtc")

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
                        f"Video track received but streaming_config is not 'mqtt' or 'go2rtc' (current: {self.streaming_config})"
                    )
            elif track.kind == "audio":
                if self.streaming_config == "go2rtc":
                    LOGGER.info(f"[TRACK] Audio track received! Starting audio reader task")
                    # Initialize HLS muxer if not exists
                    if device_id not in self.hls_muxers:
                        LOGGER.info(f"[AUDIO] Creating new muxer for device {device_id}")
                        self._init_hls_muxer(device_id)
                    else:
                        LOGGER.info(f"[AUDIO] Using existing muxer for device {device_id}")

                    # Store audio track and start reading
                    self.hls_muxers[device_id]["audio_track"] = track
                    task = asyncio.create_task(self._read_audio_frames(device_id, track))
                    self.active_tasks.add(task)
                    task.add_done_callback(self.active_tasks.discard)
                else:
                    LOGGER.warning(
                        f"[TRACK] Audio track received but streaming_config is '{self.streaming_config}' (not 'go2rtc')"
                    )

        # ICE connection timeout checker
        async def check_ice_connection_state():
            for i in range(20):
                await asyncio.sleep(1)
                LOGGER.debug(
                    f"ICE check ({i+1}/20): iceConnectionState={pc.iceConnectionState}, "
                    f"connectionState={pc.connectionState}"
                )
                if pc.iceConnectionState in ["connected", "completed"]:
                    LOGGER.info("ICE connection successful!")
                    return
            if pc.iceConnectionState in ["new", "checking"]:
                LOGGER.warning(f"ICE connection timeout - state stuck at {pc.iceConnectionState}, closing connection")
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
        LOGGER.info(f"ICE gathering state: {pc.iceGatheringState}")

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
        LOGGER.info(f"Stripped {candidates_stripped} candidates from answer SDP")

        # Log SDP for debugging
        LOGGER.info(f"Full clean answer SDP:\n{clean_answer_sdp}")

        if "a=setup:" in clean_answer_sdp:
            setup_line = [line for line in answer_sdp_no_candidates if "a=setup:" in line]
            LOGGER.info(f"DTLS setup in answer: {setup_line}")

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
                    LOGGER.info(f"Sent ICE candidate for mid={current_mid}: {candidate_str[:50]}...")

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
            LOGGER.warning(f"Missing session_id or candidate data")
            return

        pc = self.peer_connections.get(session_id)
        if not pc:
            LOGGER.warning(f"No peer connection found for session {session_id}")
            return

        try:
            candidate = RTCIceCandidate(
                sdpMid=candidate_data.get("sdpMid"),
                sdpMLineIndex=candidate_data.get("sdpMLineIndex"),
                candidate=candidate_data.get("sdp"),
            )
            await pc.addIceCandidate(candidate)
            LOGGER.info(f"Added remote ICE candidate: {candidate_data.get('sdp', '')[:60]}...")
        except Exception as e:
            LOGGER.error(f"Failed to add remote ICE candidate: {e}")

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
                LOGGER.info(f"Closed and removed peer connection for session {session_id}")
            except Exception as e:
                LOGGER.error(f"Error closing peer connection: {e}")

    async def cleanup(self):
        """
        Cleanup all WebRTC resources - peer connections, tasks, HLS server, etc.
        Should be called when shutting down the handler.
        """
        LOGGER.info("Starting WebRTC handler cleanup...")

        # Cancel all active tasks
        if hasattr(self, "active_tasks") and self.active_tasks:
            LOGGER.info(f"Cancelling {len(self.active_tasks)} active tasks")
            for task in list(self.active_tasks):
                if not task.done():
                    task.cancel()
            # Wait for tasks to finish cancellation
            if self.active_tasks:
                await asyncio.gather(*self.active_tasks, return_exceptions=True)
            self.active_tasks.clear()

        # Close all peer connections
        if hasattr(self, "peer_connections") and self.peer_connections:
            LOGGER.info(f"Closing {len(self.peer_connections)} peer connections")
            for session_id in list(self.peer_connections.keys()):
                try:
                    await self.close_session(session_id)
                except Exception as e:
                    LOGGER.error(f"Error closing session {session_id}: {e}")
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
            except Exception as e:
                LOGGER.error(f"Error stopping HLS server: {e}")

        LOGGER.info("WebRTC handler cleanup completed")

    async def close_all_sessions(self):
        """Alias for cleanup() for backward compatibility.
        
        This method is called from websocket/__init__.py during shutdown.
        """
        await self.cleanup()

    def _start_hls_server(self, device_id=None):
        """Start HTTP server for HLS streaming"""
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import threading
        import os

        handler = self

        class HLSHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Suppress HTTP logs

            def do_GET(self):
                # Parse path: /{device_id}/playlist.m3u8 or /{device_id}/segment{N}.ts
                path_parts = self.path.strip("/").split("/")
                if len(path_parts) >= 2:
                    device_id = path_parts[0]
                    filename = path_parts[1]

                    if device_id in handler.hls_segments:
                        segments = handler.hls_segments[device_id]

                        if filename == "playlist.m3u8":
                            # Serve playlist
                            self.send_response(200)
                            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
                            self.send_header("Access-Control-Allow-Origin", "*")
                            self.end_headers()

                            playlist = segments.get("playlist", b"")
                            self.wfile.write(playlist)

                        elif filename.endswith(".ts"):
                            # Serve segment
                            if filename in segments:
                                self.send_response(200)
                                self.send_header("Content-Type", "video/mp2t")
                                self.send_header("Access-Control-Allow-Origin", "*")
                                self.end_headers()
                                self.wfile.write(segments[filename])
                            else:
                                self.send_error(404)
                        else:
                            self.send_error(404)
                    else:
                        self.send_error(404)
                else:
                    self.send_error(404)

        server = HTTPServer(("0.0.0.0", self.hls_port), HLSHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.hls_server = server
        if device_id:
            LOGGER.info(f"HLS HTTP server started on http://0.0.0.0:{self.hls_port}/{device_id}/playlist.m3u8")
        else:
            LOGGER.info(f"HLS HTTP server started on http://0.0.0.0:{self.hls_port}/<device_id>/playlist.m3u8")

    def _init_hls_muxer(self, device_id):
        """Initialize HLS muxer for a device"""
        import tempfile
        import os

        # Create temporary directory for HLS segments
        temp_dir = tempfile.mkdtemp(prefix=f"hls_{device_id}_")

        self.hls_muxers[device_id] = {
            "temp_dir": temp_dir,
            "video_track": None,
            "audio_track": None,
            "video_queue": asyncio.Queue(maxsize=30),
            "audio_queue": asyncio.Queue(maxsize=30),
            "container": None,
            "video_stream": None,
            "audio_stream": None,
            "segment_index": 0,
            "segment_start_time": None,
            "current_segment_path": None,
            "frame_count": 0,
            "audio_pts": 0,
            "video_pts": 0,
            "video_ready": False,
            "audio_ready": False,
            "audio_failed": False,
        }

        self.hls_segments[device_id] = {
            "playlist": b"",
        }

        # Start the muxer task
        task = asyncio.create_task(self._hls_muxer_task(device_id))
        self.active_tasks.add(task)
        task.add_done_callback(self.active_tasks.discard)

        LOGGER.info(
            f"Initialized HLS muxer for device {device_id} in {temp_dir}. "
            f"Playlist: http://0.0.0.0:{self.hls_port}/{device_id}/playlist.m3u8"
        )

    async def _read_video_frames(self, device_id, track):
        """Read video frames and put them in the queue"""
        try:
            while True:
                frame = await track.recv()
                try:
                    muxer = self.hls_muxers.get(device_id)
                    if muxer:
                        muxer["video_queue"].put_nowait(frame)
                        muxer["video_ready"] = True
                except asyncio.QueueFull:
                    LOGGER.debug(f"Video queue full for {device_id}, dropping frame")
        except Exception as e:
            LOGGER.error(f"Error reading video frames: {e}")

    async def _read_audio_frames(self, device_id, track):
        """Read audio frames and put them in the queue"""
        LOGGER.info(f"[AUDIO] Audio track started for device {device_id}")
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
                            f"[AUDIO] Receiving audio: {frame.format.name}, {frame.layout.channels}ch @ {frame.sample_rate}Hz"
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
                        LOGGER.warning(f"[AUDIO] No audio frames from camera for device {device_id}")
                    await asyncio.sleep(0.5)

                except Exception as frame_error:
                    error_count += 1
                    # Log only every 100 errors to avoid spam
                    if error_count % 100 == 1:
                        LOGGER.warning(f"[AUDIO] Audio receive errors ({error_count}x): {type(frame_error).__name__}")
                    await asyncio.sleep(0.1)

                # If we hit many consecutive failures, mark audio_failed to avoid blocking video
                if error_count >= 200:
                    muxer = self.hls_muxers.get(device_id)
                    if muxer:
                        muxer["audio_failed"] = True
                    LOGGER.error(f"[AUDIO] Too many errors ({error_count}), disabling audio for device {device_id}")
                    return

        except Exception as e:
            LOGGER.error(f"[AUDIO] Fatal error in audio reader: {e}")

    async def _hls_muxer_task(self, device_id):
        """Single task that muxes audio+video frames into HLS segments"""
        import time

        muxer = self.hls_muxers.get(device_id)
        if not muxer:
            return

        LOGGER.info(f"HLS muxer task started for device {device_id}")

        try:
            # Wait for video track to arrive (mandatory) and audio (best effort)
            wait_start = time.time()
            while not muxer["video_ready"]:
                elapsed = time.time() - wait_start
                if elapsed > 5:
                    LOGGER.error(f"[TRACKS] Timeout waiting for video track (>{elapsed:.1f}s), aborting muxer")
                    return
                await asyncio.sleep(0.1)

            # Give audio up to 5s but continue without it if absent
            wait_start = time.time()
            while not muxer["audio_ready"] and (time.time() - wait_start) < 5:
                await asyncio.sleep(0.1)

            LOGGER.info(f"[TRACKS] Starting muxer - Video: {muxer['video_ready']}, Audio: {muxer['audio_ready']}")

            audio_no_stream_warns = 0

            while True:
                current_time = time.time()

                # Initialize segment if needed
                if muxer["container"] is None:
                    await self._create_hls_segment(device_id)

                # Check if we need to close current segment
                if (
                    muxer["segment_start_time"]
                    and (current_time - muxer["segment_start_time"]) >= self.hls_segment_duration
                ):
                    await self._close_hls_segment(device_id)
                    continue

                # Try to get frames from queues
                video_frame = None
                audio_frame = None

                try:
                    video_frame = muxer["video_queue"].get_nowait()
                except asyncio.QueueEmpty:
                    pass

                try:
                    audio_frame = muxer["audio_queue"].get_nowait()
                except asyncio.QueueEmpty:
                    pass

                # Process frames
                if video_frame and muxer["video_stream"]:
                    try:
                        # Monotonic PTS based on 30fps -> 90000/30 = 3000 ticks per frame
                        video_frame.pts = muxer.get("video_pts", 0)
                        muxer["video_pts"] = video_frame.pts + 3000
                        for packet in muxer["video_stream"].encode(video_frame):
                            muxer["container"].mux(packet)
                        muxer["frame_count"] += 1
                    except Exception as e:
                        LOGGER.warning(f"Error encoding video: {e}")

                if audio_frame and muxer.get("audio_failed"):
                    # Drop audio frames silently if audio setup failed
                    continue

                if audio_frame and muxer["audio_stream"]:
                    try:
                        # Reformat audio if needed
                        if audio_frame.format.name != "s16":
                            LOGGER.debug(f"[AUDIO] Reformatting from {audio_frame.format.name} to s16")
                            audio_frame = audio_frame.reformat(format="s16")

                        tb = muxer["audio_stream"].time_base
                        audio_frame.pts = muxer.get("audio_pts", 0)
                        muxer["audio_pts"] = audio_frame.pts + (audio_frame.samples or 0)

                        packets = list(muxer["audio_stream"].encode(audio_frame))
                        if packets:
                            for packet in packets:
                                muxer["container"].mux(packet)
                            LOGGER.debug(f"[AUDIO] Encoded frame into {len(packets)} packets")
                        else:
                            LOGGER.debug("[AUDIO] No packets produced")
                    except Exception as e:
                        LOGGER.error(f"[AUDIO] Encoding error: {e}", exc_info=True)
                elif audio_frame and not muxer["audio_stream"]:
                    audio_no_stream_warns += 1
                    if audio_no_stream_warns == 1 or audio_no_stream_warns % 200 == 0:
                        LOGGER.warning("[AUDIO] Frame available but no audio stream created yet")

                # Small sleep to prevent CPU spinning
                if not video_frame and not audio_frame:
                    await asyncio.sleep(0.001)

        except Exception as e:
            LOGGER.error(f"Error in HLS muxer task: {e}")
            LOGGER.exception("Details:")

    async def _create_hls_segment(self, device_id):
        """Create a new HLS segment"""
        import time

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
                wait_count = 0
                while wait_count < 100 and not video_frame:
                    try:
                        video_frame = muxer["video_queue"].get_nowait()
                    except asyncio.QueueEmpty:
                        await asyncio.sleep(0.01)
                        wait_count += 1

                if not video_frame:
                    LOGGER.error("Video ready but no frame available to start segment; retrying later")
                    muxer["container"] = None
                    return

                width = video_frame.width
                height = video_frame.height

                # Force a stable framerate to avoid mis-detected 120fps and segment glitches
                fps = 30.0
                gop = int(self.hls_segment_duration * fps)
                LOGGER.debug(f"[VIDEO] Creating video stream {width}x{height} @ {fps:.2f}fps (gop={gop})")

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

                # Put the frame back in the queue
                muxer["video_queue"].put_nowait(video_frame)
            except Exception as e:
                LOGGER.warning(f"Error adding video stream: {e}")
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
                    LOGGER.debug(f"[AUDIO] Creating audio stream: {num_channels}ch @ {sample_rate}Hz")

                    try:
                        audio_stream = container.add_stream("aac", rate=sample_rate)
                        audio_stream.channels = num_channels
                        audio_stream.time_base = Fraction(1, sample_rate)
                        muxer["audio_stream"] = audio_stream
                    except Exception:
                        # Fallback to MP3 if AAC fails
                        try:
                            audio_stream = container.add_stream("libmp3lame", rate=sample_rate)
                            audio_stream.channels = num_channels
                            audio_stream.time_base = Fraction(1, sample_rate)
                            muxer["audio_stream"] = audio_stream
                            LOGGER.info("[AUDIO] Using MP3 codec (AAC unavailable)")
                        except Exception as e:
                            LOGGER.error(f"[AUDIO] Failed to create audio stream: {e}")
                            muxer["audio_stream"] = None
                            muxer["audio_failed"] = True

                    # Put the frame back in the queue
                    if muxer["audio_stream"]:
                        muxer["audio_queue"].put_nowait(audio_frame)
            except Exception as e:
                LOGGER.error(f"[AUDIO] Error adding audio stream: {e}")
                muxer["audio_failed"] = True

        muxer["container"] = container
        muxer["current_segment_path"] = segment_path
        muxer["segment_start_time"] = time.time()
        muxer["segment_index"] += 1
        muxer["frame_count"] = 0

    async def _close_hls_segment(self, device_id):
        """Close current HLS segment and update playlist"""
        import time

        muxer = self.hls_muxers.get(device_id)
        if not muxer or not muxer["container"]:
            return

        try:
            # Flush encoders
            if muxer["video_stream"]:
                video_packets = list(muxer["video_stream"].encode(None))
                for packet in video_packets:
                    muxer["container"].mux(packet)
                LOGGER.debug(f"[VIDEO] Flushed {len(video_packets)} packets")

            if muxer["audio_stream"]:
                audio_packets = list(muxer["audio_stream"].encode(None))
                for packet in audio_packets:
                    muxer["container"].mux(packet)

            # Close container
            muxer["container"].close()

            # Debug segment stats to trace freezes
            LOGGER.debug(f"[HLS] Closed segment {muxer['segment_index'] - 1} with {muxer['frame_count']} video frames")

            # Update playlist
            self._update_hls_playlist(device_id)

            # Reset for next segment
            muxer["container"] = None
            muxer["video_stream"] = None
            muxer["audio_stream"] = None
            muxer["segment_start_time"] = None

        except Exception as e:
            LOGGER.error(f"Error closing HLS segment: {e}")

    def _update_hls_playlist(self, device_id):
        """Update HLS playlist for a device"""
        import os
        import math

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
        LOGGER.debug(f"Updated playlist for {device_id} with {segment_count} segments")

        # Clean up old segments from disk and memory
        for i in range(max(0, start_index - 10), start_index):
            old_segment_filename = f"segment{i}.ts"
            old_segment_path = f"{muxer['temp_dir']}/{old_segment_filename}"

            # Remove from disk
            if os.path.exists(old_segment_path):
                try:
                    os.remove(old_segment_path)
                except:
                    pass

            # Remove from memory
            if old_segment_filename in self.hls_segments[device_id]:
                del self.hls_segments[device_id][old_segment_filename]
