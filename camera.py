import cv2
from pathlib import Path
try:
    from picamera2 import Picamera2
    PICAMERA2_AVAILABLE = True
except Exception:
    PICAMERA2_AVAILABLE = False

from config import FRAME_WIDTH, FRAME_HEIGHT, FPS


def init_camera():
    """Initialize camera (picamera2 preferred, fallback to OpenCV)."""
    if PICAMERA2_AVAILABLE:
        try:
            print("[CAMERA] Initializing Raspberry Pi Camera (picamera2)...")
            picam2 = Picamera2()
            config = picam2.create_preview_configuration(
                main={"size": (FRAME_WIDTH, FRAME_HEIGHT), "format": "RGB888"}
            )
            picam2.configure(config)
            picam2.start()
            print("[CAMERA] Raspberry Pi Camera initialized successfully")
            return picam2, "picamera2"
        except Exception as e:
            print(f"[CAMERA] picamera2 failed: {e}, falling back to OpenCV")

    print("[CAMERA] Initializing USB camera via OpenCV...")
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, FPS)

    if not cap.isOpened():
        raise RuntimeError("Failed to open camera")

    print("[CAMERA] USB camera initialized successfully")
    return cap, "opencv"
