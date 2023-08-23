import cv2


class VideoCamera(object):
    def __init__(self, url: str):
        self.video = cv2.VideoCapture(url)

    def __del__(self):
        self.video.release()

    def get_frame(self):
        try:
            _, image = self.video.read()
            _, jpeg = cv2.imencode(".jpg", image)
            return jpeg.tobytes()
        except Exception as exc:
            return None
