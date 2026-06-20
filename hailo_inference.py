import numpy as np
from pathlib import Path
from config import MODEL_PATH, BOX_OFFSET_X, BOX_OFFSET_Y, BOX_SCALE_X, BOX_SCALE_Y, CONFIDENCE_THRESHOLD, FRAME_HEIGHT, FRAME_WIDTH
from preprocessing import letterbox_image, sigmoid, calibrate_box, nms, limit_detections_per_class

try:
    from hailo_platform import HEF, VDevice
    HAILO_AVAILABLE = True
    HAILO_IMPORT_ERROR = None
except ImportError as e:
    HEF = None
    VDevice = None
    HAILO_AVAILABLE = False
    HAILO_IMPORT_ERROR = e


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

        decoded = nms(decoded)
        decoded = limit_detections_per_class(decoded)
        return decoded

    def close(self):
        """Cleanup resources."""
        try:
            if hasattr(self, "configured_infer_model_ctx"):
                self.configured_infer_model_ctx.__exit__(None, None, None)
            self.vdevice.release()
        except Exception:
            pass
