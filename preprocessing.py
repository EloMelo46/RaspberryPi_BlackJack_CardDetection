import cv2
import numpy as np
from typing import Tuple
from config import FRAME_WIDTH, FRAME_HEIGHT, NMS_IOU_THRESHOLD, MAX_DETECTIONS_PER_CLASS


def sigmoid(x):
    x = np.clip(x, -60.0, 60.0)
    return 1.0 / (1.0 + np.exp(-x))


def box_iou(box_a, box_b):
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter = inter_w * inter_h
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def nms(detections, iou_threshold: float = NMS_IOU_THRESHOLD):
    if not detections:
        return []

    detections = sorted(detections, key=lambda d: d["confidence"], reverse=True)
    kept = []
    while detections:
        best = detections.pop(0)
        kept.append(best)
        detections = [
            d for d in detections
            if d["class_id"] != best["class_id"] or box_iou(best["box"], d["box"]) < iou_threshold
        ]
    return kept


def letterbox_image(image: np.ndarray, target_width: int, target_height: int, color=(114, 114, 114)) -> Tuple[np.ndarray, float, int, int]:
    """Resize with aspect ratio preserved and return padding metadata."""
    src_h, src_w = image.shape[:2]
    scale = min(target_width / src_w, target_height / src_h)
    new_w = int(round(src_w * scale))
    new_h = int(round(src_h * scale))

    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((target_height, target_width, 3), color, dtype=image.dtype)

    pad_x = (target_width - new_w) // 2
    pad_y = (target_height - new_h) // 2
    canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized
    return canvas, scale, pad_x, pad_y


def calibrate_box(box, image_shape, calib):
    img_h, img_w = image_shape
    x1, y1, x2, y2 = box
    off_x = calib["off_x"]
    off_y = calib["off_y"]
    scale_x = max(0.3, calib["scale_x"])
    scale_y = max(0.3, calib["scale_y"])

    cx = (x1 + x2) / 2.0 + off_x
    cy = (y1 + y2) / 2.0 + off_y
    bw = max(2.0, (x2 - x1) * scale_x)
    bh = max(2.0, (y2 - y1) * scale_y)

    nx1 = cx - bw / 2.0
    ny1 = cy - bh / 2.0
    nx2 = cx + bw / 2.0
    ny2 = cy + bh / 2.0

    nx1 = max(0.0, min(float(img_w - 1), nx1))
    ny1 = max(0.0, min(float(img_h - 1), ny1))
    nx2 = max(0.0, min(float(img_w - 1), nx2))
    ny2 = max(0.0, min(float(img_h - 1), ny2))
    return nx1, ny1, nx2, ny2


def limit_detections_per_class(detections, max_per_class: int = MAX_DETECTIONS_PER_CLASS):
    """Keep only the highest-confidence detections per class."""
    if max_per_class <= 0:
        return detections

    counts = {}
    limited = []
    for det in sorted(detections, key=lambda d: d["confidence"], reverse=True):
        class_id = det["class_id"]
        class_count = counts.get(class_id, 0)
        if class_count >= max_per_class:
            continue
        counts[class_id] = class_count + 1
        limited.append(det)
    return limited
