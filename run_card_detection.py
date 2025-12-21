#!/usr/bin/env python3

import numpy as np
from modlib.apps import Annotator
from modlib.devices import AiCamera
from modlib.models import COLOR_FORMAT, MODEL_TYPE, Model
from modlib.models.post_processors import pp_od_yolo_ultralytics

class YOLO(Model):
    """YOLO model for IMX500 deployment."""

    def __init__(self):
        super().__init__(
            model_file="/home/elomelo/card_detection/yolov8n_imx_model/packerOut.zip",
            model_type=MODEL_TYPE.CONVERTED,
            color_format=COLOR_FORMAT.RGB,
            preserve_aspect_ratio=False,
        )

        self.labels = np.genfromtxt(
            "/home/elomelo/card_detection/yolov8n_imx_model/labels.txt",
            dtype=str,
            delimiter="\n",
        )

    def post_process(self, output_tensors):
        return pp_od_yolo_ultralytics(output_tensors)


# ====== Kamera + Modell starten ======
device = AiCamera(frame_rate=12)
model = YOLO()
device.deploy(model)
annotator = Annotator()

with device as stream:
    for frame in stream:
        detections = frame.detections[frame.detections.confidence > 0.4]

        # === Nur beste Box pro Klasse ===
        keep_indices = []
        seen = {}
        for i, (conf, cls) in enumerate(zip(detections.confidence, detections.class_id)):
            if cls not in seen or conf > detections.confidence[seen[cls]]:
                seen[cls] = i
        keep_indices = list(seen.values())
        

        # erzeugt neues Detections-Objekt vom gleichen Typ
        DetectionsType = type(detections)
        detections = DetectionsType(
            bbox=detections.bbox[keep_indices],
            class_id=detections.class_id[keep_indices],
            confidence=detections.confidence[keep_indices],
        )
        # =================================

        labels = [f"{model.labels[int(c)]}: {s:.2f}" for c, s in zip(detections.class_id, detections.confidence)]
        annotator.annotate_boxes(frame, detections, labels=labels, alpha=0.3, corner_radius=8)
        frame.display()
