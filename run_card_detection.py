#!/usr/bin/env python3

"""
Blackjack Card Detection for Hailo 10H
Detects playing cards in real-time using Hailo 10H AI accelerator.
Tracks cards for player/dealer and provides Basic Strategy recommendations via web interface.
"""

import cv2
import numpy as np
import time
from pathlib import Path

try:
    from picamera2 import Picamera2
    PICAMERA2_AVAILABLE = True
except ImportError:
    PICAMERA2_AVAILABLE = False
    print("Warning: picamera2 not available, will try OpenCV")

try:
    from hailo_platform import HEF, VDevice
    HAILO_AVAILABLE = True
    HAILO_IMPORT_ERROR = None
except ImportError as e:
    HEF = None
    VDevice = None
    HAILO_AVAILABLE = False
    HAILO_IMPORT_ERROR = e

import bj_logic as bj


# ============================================================================
# CONFIGURATION
# ============================================================================

MODEL_PATH = "./yolo26m.hef"
CONFIDENCE_THRESHOLD = 0.55
NMS_IOU_THRESHOLD = 0.45
DECAY_LIMIT = 40  # Frames until card is deleted if not seen
MAX_DETECTIONS_PER_CLASS = 1

# Video capture settings
FPS = 20
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

# Optional live calibration copied from working test pipeline.
BOX_OFFSET_X = 0.0
BOX_OFFSET_Y = 0.0
BOX_SCALE_X = 1.0
BOX_SCALE_Y = 1.0

# Directory for runtime outputs (images / text files)
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Card labels (52 cards)
CARD_LABELS = [
    '10c', '10d', '10h', '10s', '2c', '2d', '2h', '2s',
    '3c', '3d', '3h', '3s', '4c', '4d', '4h', '4s',
    '5c', '5d', '5h', '5s', '6c', '6d', '6h', '6s',
    '7c', '7d', '7h', '7s', '8c', '8d', '8h', '8s',
    '9c', '9d', '9h', '9s', 'Ac', 'Ad', 'Ah', 'As',
    'Jc', 'Jd', 'Jh', 'Js', 'Kc', 'Kd', 'Kh', 'Ks',
    'Qc', 'Qd', 'Qh', 'Qs'
]

# ============================================================================
# GLOBAL STATE
# ============================================================================

player_cards_persistent = []
dealer_cards_persistent = []
player_seen_counter = {}
dealer_seen_counter = {}


def limit_detections_per_class(detections, max_per_class=1):
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


def nms(detections, iou_threshold=0.45):
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


def letterbox_image(image, target_width, target_height, color=(114, 114, 114)):
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


# ============================================================================
# CAMERA INITIALIZATION
# ============================================================================

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


def print_hailo_install_hint():
    """Print a clear setup hint when Hailo Python bindings are missing."""
    print("[HAILO] Python module 'hailo_platform' is not installed in this environment.")
    if HAILO_IMPORT_ERROR is not None:
        print(f"[HAILO] Import error: {HAILO_IMPORT_ERROR}")
    print("[HAILO] Install the HailoRT wheel provided by Hailo Developer Zone, then retry.")
    print("[HAILO] Example:")
    print("  source venv_bj/bin/activate")
    print("  pip install /path/to/hailort-<version>-cp<pyver>-linux_aarch64.whl")
    print("  python3 -c \"from hailo_platform import VDevice; print('Hailo OK')\"")


# ============================================================================
# HAILO INFERENCE ENGINE
# ============================================================================

class HailoCardDetector:
    """Wraps Hailo inference for card detection."""

    def __init__(self, hef_path: str):
        if not HAILO_AVAILABLE:
            raise RuntimeError(
                "hailo_platform is not available. Run with a Hailo-enabled environment "
                "and install the correct hailort wheel for your Raspberry Pi/Python version."
            )

        print(f"[HAILO] Loading HEF model from {hef_path}")

        if not Path(hef_path).exists():
            raise FileNotFoundError(f"Model file not found: {hef_path}")

        self.hef = HEF(hef_path)
        self.vdevice = VDevice()
        self.infer_model = self.vdevice.create_infer_model(hef_path)
        self.infer_model.set_batch_size(1)

        self.input_name = self.infer_model.input_names[0]
        input_info = self.infer_model.input()
        self.input_shape = tuple(input_info.shape)
        self.input_dtype = self._hailo_dtype_to_numpy(input_info.format.type)

        self.output_names = list(self.infer_model.output_names)
        self.output_specs = {
            out.name: {
                "shape": tuple(out.shape),
                "dtype": self._hailo_dtype_to_numpy(out.format.type),
            }
            for out in self.infer_model.outputs
        }

        # Pair the 3 box/class output heads exactly like the working diagnostic script.
        self.head_meta = {}
        outputs_by_shape = {tuple(o.shape): o for o in self.infer_model.outputs}
        paired_shapes = [
            ((80, 80, 4), (80, 80, 52), 8, "p8"),
            ((40, 40, 4), (40, 40, 52), 16, "p16"),
            ((20, 20, 4), (20, 20, 52), 32, "p32"),
        ]
        for box_shape, cls_shape, stride, scale_name in paired_shapes:
            if box_shape not in outputs_by_shape or cls_shape not in outputs_by_shape:
                continue
            box_out = outputs_by_shape[box_shape]
            cls_out = outputs_by_shape[cls_shape]
            self.head_meta[scale_name] = {
                "grid": (box_shape[0], box_shape[1]),
                "stride": stride,
                "box_name": box_out.name,
                "cls_name": cls_out.name,
                "box_scale": float(box_out.quant_infos[0].qp_scale),
                "box_zp": float(box_out.quant_infos[0].qp_zp),
                "cls_scale": float(cls_out.quant_infos[0].qp_scale),
                "cls_zp": float(cls_out.quant_infos[0].qp_zp),
            }

        if not self.head_meta:
            raise RuntimeError(
                "Could not build head metadata from HEF outputs. "
                f"Found output shapes: {[tuple(o.shape) for o in self.infer_model.outputs]}"
            )

        self.configured_infer_model_ctx = self.infer_model.configure()
        self.configured_infer_model = self.configured_infer_model_ctx.__enter__()

        self.calib = {
            "off_x": BOX_OFFSET_X,
            "off_y": BOX_OFFSET_Y,
            "scale_x": BOX_SCALE_X,
            "scale_y": BOX_SCALE_Y,
        }

        print("[HAILO] Model loaded successfully")
        print(f"[HAILO] Input shape: {self.input_shape}, dtype: {self.input_dtype.__name__}")
        print(f"[HAILO] Output layers: {self.output_names}")
        print(f"[HAILO] Decoding heads: {list(self.head_meta.keys())}")

    def _hailo_dtype_to_numpy(self, hailo_format_type):
        fmt_name = str(hailo_format_type).split(".")[-1].upper()
        if fmt_name == "UINT8":
            return np.uint8
        if fmt_name == "UINT16":
            return np.uint16
        if fmt_name == "FLOAT32":
            return np.float32
        return np.uint8

    def infer(self, frame: np.ndarray):
        """
        Run inference on frame.
        Returns: list of dicts with class_id, confidence, x, y, w, h
        """
        if len(self.input_shape) >= 3:
            input_h, input_w = int(self.input_shape[0]), int(self.input_shape[1])
        else:
            input_h, input_w = FRAME_HEIGHT, FRAME_WIDTH

        letterboxed, lb_scale, pad_x, pad_y = letterbox_image(frame, input_w, input_h)
        input_data = letterboxed.astype(self.input_dtype, copy=False)

        output_buffers = {
            name: np.empty(spec["shape"], dtype=spec["dtype"])
            for name, spec in self.output_specs.items()
        }

        try:
            bindings = self.configured_infer_model.create_bindings(
                input_buffers={self.input_name: input_data},
                output_buffers=output_buffers,
            )
            self.configured_infer_model.run([bindings], 10000)

            # The working test script decodes directly from the prepared output buffers.
            decoded = self._decode_heads(
                output_buffers,
                frame.shape[:2],
                (lb_scale, pad_x, pad_y),
            )

            detections = []
            for det in decoded:
                x1, y1, x2, y2 = det["box"]
                detections.append({
                    "class_id": det["class_id"],
                    "confidence": det["confidence"],
                    "x": (x1 + x2) / 2.0,
                    "y": (y1 + y2) / 2.0,
                    "w": max(0.0, x2 - x1),
                    "h": max(0.0, y2 - y1),
                    "box": det["box"],
                    "head": det["head"],
                })
            return detections
        except Exception as e:
            print(f"[HAILO] Inference error: {e}")
            return []

    def _decode_heads(self, output_data, image_shape, letterbox_meta):
        """Decode the 3 detection scales into bounding boxes."""
        img_h, img_w = image_shape
        lb_scale, pad_x, pad_y = letterbox_meta
        decoded = []

        for scale_name, meta in self.head_meta.items():
            box_arr = np.asarray(output_data[meta["box_name"]], dtype=np.float32)
            cls_arr = np.asarray(output_data[meta["cls_name"]], dtype=np.float32)

            box_map = (box_arr - meta["box_zp"]) * meta["box_scale"]
            cls_map = (cls_arr - meta["cls_zp"]) * meta["cls_scale"]
            stride = meta["stride"]

            cls_probs = sigmoid(cls_map)
            best_class_ids = np.argmax(cls_probs, axis=-1)
            best_scores = np.max(cls_probs, axis=-1)

            ys, xs = np.where(best_scores >= CONFIDENCE_THRESHOLD)
            for y, x in zip(ys, xs):
                score = float(best_scores[y, x])
                class_id = int(best_class_ids[y, x])
                tx, ty, tw, th = box_map[y, x]

                sx = sigmoid(float(tx))
                sy = sigmoid(float(ty))
                sw = sigmoid(float(tw))
                sh = sigmoid(float(th))

                cx = (x + (2.0 * sx - 0.5)) * stride
                cy = (y + (2.0 * sy - 0.5)) * stride
                bw = ((2.0 * sw) ** 2) * stride
                bh = ((2.0 * sh) ** 2) * stride

                x1 = (cx - bw / 2.0 - pad_x) / lb_scale
                y1 = (cy - bh / 2.0 - pad_y) / lb_scale
                x2 = (cx + bw / 2.0 - pad_x) / lb_scale
                y2 = (cy + bh / 2.0 - pad_y) / lb_scale

                x1 = max(0.0, min(float(img_w - 1), x1))
                y1 = max(0.0, min(float(img_h - 1), y1))
                x2 = max(0.0, min(float(img_w - 1), x2))
                y2 = max(0.0, min(float(img_h - 1), y2))

                if x2 <= x1 or y2 <= y1:
                    continue

                x1, y1, x2, y2 = calibrate_box((x1, y1, x2, y2), (img_h, img_w), self.calib)
                decoded.append({
                    "class_id": class_id,
                    "confidence": score,
                    "box": (x1, y1, x2, y2),
                    "head": scale_name,
                })

        decoded = nms(decoded, NMS_IOU_THRESHOLD)
        decoded = limit_detections_per_class(decoded, MAX_DETECTIONS_PER_CLASS)
        return decoded

    def close(self):
        """Cleanup resources."""
        try:
            if hasattr(self, "configured_infer_model_ctx"):
                self.configured_infer_model_ctx.__exit__(None, None, None)
            self.vdevice.release()
        except Exception:
            pass


# ============================================================================
# CARD TRACKING
# ============================================================================

def update_card_tracking(detections, frame_width):
    """
    Update persistent card lists based on detections.
    Classifies cards as player (left) or dealer (right) based on frame midpoint.
    """
    global player_cards_persistent, dealer_cards_persistent
    global player_seen_counter, dealer_seen_counter

    middle_x = frame_width // 2
    best_detections = limit_detections_per_class(detections, MAX_DETECTIONS_PER_CLASS)

    detected_player_cards = set()
    detected_dealer_cards = set()

    for det in best_detections:
        card_label = CARD_LABELS[det['class_id']]
        det_x = det['x']

        if det_x < middle_x:
            detected_player_cards.add(card_label)
            player_seen_counter[card_label] = 0
        else:
            detected_dealer_cards.add(card_label)
            dealer_seen_counter[card_label] = 0

    # NOTE:
    # This preserves your current behavior, but it does not truly keep cards across missed frames.
    # I left it unchanged so only the inference path is fixed.
    player_cards_persistent = list(detected_player_cards)
    dealer_cards_persistent = list(detected_dealer_cards)

    for card in list(player_seen_counter):
        if card not in detected_player_cards:
            player_seen_counter[card] += 1

    for card in list(dealer_seen_counter):
        if card not in detected_dealer_cards:
            dealer_seen_counter[card] += 1

    player_cards_persistent = [c for c in player_cards_persistent if player_seen_counter.get(c, 0) < DECAY_LIMIT]
    dealer_cards_persistent = [c for c in dealer_cards_persistent if dealer_seen_counter.get(c, 0) < DECAY_LIMIT]

    player_seen_counter = {k: v for k, v in player_seen_counter.items() if k in player_cards_persistent or v < DECAY_LIMIT}
    dealer_seen_counter = {k: v for k, v in dealer_seen_counter.items() if k in dealer_cards_persistent or v < DECAY_LIMIT}

    globals()["player_cards_persistent"] = player_cards_persistent
    globals()["dealer_cards_persistent"] = dealer_cards_persistent
    globals()["player_seen_counter"] = player_seen_counter
    globals()["dealer_seen_counter"] = dealer_seen_counter


# ============================================================================
# STRATEGY & OUTPUT
# ============================================================================

def compute_strategy():
    """Compute Basic Strategy recommendation."""
    if not player_cards_persistent or not dealer_cards_persistent:
        return "Waiting for cards..."

    try:
        strategy = bj.basic_strategy(player_cards_persistent, dealer_cards_persistent)
        return strategy
    except Exception as e:
        print(f"[STRATEGY] Error: {e}")
        return "Error"


def save_frame_and_info(frame, filename=str(OUTPUT_DIR / "latest.jpg")):
    """Save frame to file for web interface."""
    try:
        cv2.imwrite(filename, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    except Exception as e:
        print(f"[OUTPUT] Failed to save frame: {e}")


def update_text_files():
    """Update text files for web interface."""
    try:
        strategy = compute_strategy()

        with open(OUTPUT_DIR / "latest.txt", "w") as f:
            f.write(strategy)

        with open(OUTPUT_DIR / "player_cards.txt", "w") as f:
            f.write(", ".join(player_cards_persistent) if player_cards_persistent else "No cards")

        with open(OUTPUT_DIR / "dealer_cards.txt", "w") as f:
            f.write(", ".join(dealer_cards_persistent) if dealer_cards_persistent else "No cards")
    except Exception as e:
        print(f"[OUTPUT] Error writing text files: {e}")


# ============================================================================
# FRAME ANNOTATION
# ============================================================================

def annotate_frame(frame, detections, frame_width):
    """Draw annotations on frame."""
    middle_x = frame_width // 2
    h, w = frame.shape[:2]

    cv2.line(frame, (middle_x, 0), (middle_x, h), (255, 255, 255), 2)

    best_detections = limit_detections_per_class(detections, MAX_DETECTIONS_PER_CLASS)

    for det in best_detections:
        if "box" in det:
            x1, y1, x2, y2 = det["box"]
        else:
            x, y, det_w, det_h = det['x'], det['y'], det['w'], det['h']
            x1 = x - det_w / 2.0
            y1 = y - det_h / 2.0
            x2 = x + det_w / 2.0
            y2 = y + det_h / 2.0

        conf = det['confidence']
        card_label = CARD_LABELS[det['class_id']]
        color = (0, 255, 0) if det['x'] < middle_x else (0, 0, 255)

        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
        cv2.putText(
            frame,
            f"{card_label} {conf:.2f}",
            (max(0, int(x1)), max(20, int(y1) - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
        )

    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(frame, "PLAYER", (20, 30), font, 0.8, (0, 255, 0), 2)
    cv2.putText(frame, "DEALER", (middle_x + 20, 30), font, 0.8, (0, 0, 255), 2)

    strategy = compute_strategy()
    cv2.putText(frame, f"Strategy: {strategy}", (20, h - 20), font, 1.0, (255, 255, 255), 2)

    return frame


# ============================================================================
# MAIN INFERENCE LOOP
# ============================================================================

def main():
    print("[INIT] Starting Blackjack Card Detection (Hailo 10H)")
    if not HAILO_AVAILABLE:
        print_hailo_install_hint()
        return

    camera, camera_type = init_camera()
    detector = HailoCardDetector(MODEL_PATH)
    print("[INIT] Ready. Press 'q' to quit.")

    frame_count = 0
    start_time = time.time()

    try:
        while True:
            if camera_type == "picamera2":
                frame = cv2.cvtColor(camera.capture_array(), cv2.COLOR_BGR2RGB)
            else:
                ret, frame_bgr = camera.read()
                if not ret:
                    print("[CAMERA] Failed to capture frame")
                    break
                frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

            detections = detector.infer(frame)
            update_card_tracking(detections, frame.shape[1])
            update_text_files()

            annotated_frame = annotate_frame(frame.copy(), detections, frame.shape[1])
            save_frame_and_info(annotated_frame)

            display_frame = cv2.cvtColor(annotated_frame, cv2.COLOR_RGB2BGR)
            cv2.imshow("Blackjack Card Detection", display_frame)

            frame_count += 1
            if frame_count % 30 == 0:
                elapsed = time.time() - start_time
                fps = frame_count / elapsed
                print(
                    f"[INFO] Frame {frame_count}, FPS: {fps:.2f}, "
                    f"Player: {player_cards_persistent}, Dealer: {dealer_cards_persistent}"
                )

            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("[EXIT] Quitting...")
                break

    except KeyboardInterrupt:
        print("\n[EXIT] Interrupted by user")
    except Exception as e:
        print(f"[ERROR] {e}")

    finally:
        print("[CLEANUP] Closing resources...")
        if camera_type == "picamera2":
            try:
                camera.stop()
            except Exception:
                pass
        else:
            camera.release()

        detector.close()
        cv2.destroyAllWindows()
        print("[CLEANUP] Done")


if __name__ == "__main__":
    main()
