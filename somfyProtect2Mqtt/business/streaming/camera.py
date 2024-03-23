"""RTMPS Camera to JPEG"""

import logging

import cv2


LOGGER = logging.getLogger(__name__)


class VideoCamera(object):
    def __init__(self, url: str):
        self.video = cv2.VideoCapture(url)

    def __del__(self):
        self.video.release()

    def is_opened(self):
        return self.video.isOpened()

    def release(self):
        self.video.release()

    def get_frame(self):
        try:
            ret, image = self.video.read()
            if not ret:
                return None
            ret, jpeg = cv2.imencode(".jpg", image)
            if not ret:
                return None
            return jpeg.tobytes()
        except Exception as exc:
            LOGGER.debug(f"Unable to get Frame: {exc}")
            return None
