"""RTMPS Camera to JPEG"""

import logging

import cv2

LOGGER = logging.getLogger(__name__)


class VideoCamera:
    """OpenCV-backed video capture helper."""

    def __init__(self, url: str):
        """Initialize the camera stream.

        Args:
            url (str): Video stream URL.
        """
        video_capture = getattr(cv2, "VideoCapture")
        self.video = video_capture(url)

    def __del__(self):
        """Release camera resources on deletion."""
        self.video.release()

    def is_opened(self) -> bool:
        """Return True if the stream is open."""
        return self.video.isOpened()

    def release(self) -> None:
        """Release the video capture."""
        self.video.release()

    def get_frame(self) -> bytes | None:
        """Get a single JPEG-encoded frame.

        Returns:
            bytes | None: JPEG-encoded frame bytes, or None on failure.
        """
        try:
            ret, image = self.video.read()
            if not ret:
                return None
            imencode = getattr(cv2, "imencode")
            ret, jpeg = imencode(".jpg", image)
            if not ret:
                return None
            return jpeg.tobytes()
        except (ValueError, RuntimeError) as e:
            LOGGER.debug("Unable to get Frame: {}".format(e))
            return None
