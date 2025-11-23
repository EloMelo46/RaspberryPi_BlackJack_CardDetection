#!/usr/bin/env python3

import numpy as np
import cv2
from modlib.apps import Annotator
from modlib.devices import AiCamera
from modlib.models import COLOR_FORMAT, MODEL_TYPE, Model
from modlib.models.post_processors import pp_od_yolo_ultralytics
import bj_logic as bj


# PERSISTENTE LISTEN
player_cards_persistent = []
dealer_cards_persistent = []

# MEMORY DECAY COUNTER (Frames seit letzter Sichtung)
player_seen_counter = {}
dealer_seen_counter = {}

# Anzahl Frames bis Karte gelöscht wird
DECAY_LIMIT = 20  


class YOLO(Model):
    """YOLO model for IMX500 deployment."""

    def __init__(self):
        super().__init__(
            model_file="/home/elomelo/card_detection/best_imx_model/packerOut.zip",
            model_type=MODEL_TYPE.CONVERTED,
            color_format=COLOR_FORMAT.RGB,
            preserve_aspect_ratio=False,
        )

        self.labels = np.genfromtxt(
            "/home/elomelo/card_detection/best_imx_model/labels.txt",
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
        
        # Detections ist ein objekt mit attributen bounding boxes, Klassen IDs, confidence werte
        # Filtert die liste nach confidenz wert
        detections = frame.detections[frame.detections.confidence > 0.6]

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
        # Erstellt eine liste von mit karten ID und detection confidence pro index
        labels = [
            f"{model.labels[int(c)]}: {s:.2f}"
            for c, s in zip(detections.class_id, detections.confidence)
        ]

        # Zeichnet für jedes frame das detection objekt mit label ein, alpha = opazität
        annotator.annotate_boxes(
            frame, detections, labels=labels, alpha=0.3, corner_radius=8
        )

        # === Linie + Text Overlay ===
        img = frame.image  # Zugriff auf das eigentliche RGB-Bild (NumPy-Array)

        h, w, _ = img.shape
        middle_x = w // 2

        # Vertikale weisse Mittellinie
        cv2.line(img, (middle_x, 0), (middle_x, h), (255, 255, 255), thickness=2)

        # Texte oben links und rechts
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.6
        color = (255, 255, 255)
        thickness = 2

        cv2.putText(
            img,
            "Player",
            (120, 20),
            font,
            font_scale,
            color,
            thickness,
            cv2.LINE_AA,
        )
        cv2.putText(
            img,
            "Dealer",
            (w - 190, 20),
            font,
            font_scale,
            color,
            thickness,
            cv2.LINE_AA,
        )

        # geändertes Bild speichern
        frame.image = img

        # Frame für Webserver speichern
        cv2.imwrite("latest.jpg", frame.image)

        # Bild streamen
        frame.display()

        # prüfen ob karten erkennt werden
        if len(detections.bbox) > 0:

            # center der erkannten bboxes ermitteln
            centers = [] 

            for bbox in detections.bbox:
                cx = (bbox[0] + bbox[2]) / 2
                cy = (bbox[1] + bbox[3]) / 2
                centers.append([cx, cy])

            centers = np.array(centers)    

            player_seen_this_frame = [] 
            dealer_seen_this_frame = []

            for i, (cx, cy) in enumerate(centers):
                card = model.labels[int(detections.class_id[i])]    # von der klasse model rufe die labels ab 

                # BBOX Format z.B: [0.4078125 0.78125   0.50625   0.8796875]
                # Normierte Werte 0 - 1 der bildbreite
                if cx <  0.5:
                    player_seen_this_frame.append(card)

                else:
                    dealer_seen_this_frame.append(card)   


            # ============================
            #  UPDATE PLAYER MEMORY
            # ============================

            # 1) reset counter for seen cards
            for c in player_seen_this_frame:
                if c not in player_cards_persistent:
                    player_cards_persistent.append(c)
                player_seen_counter[c] = 0

            # 2) increment counter for NOT seen cards
            for c in list(player_cards_persistent):
                if c not in player_seen_this_frame:
                    player_seen_counter[c] += 1
                    # DELETE card if unseen for too long
                    if player_seen_counter[c] > DECAY_LIMIT:
                        player_cards_persistent.remove(c)
                        del player_seen_counter[c]

            # ============================
            #  UPDATE DEALER MEMORY
            # ============================

            for c in dealer_seen_this_frame:
                if c not in dealer_cards_persistent:
                    dealer_cards_persistent.append(c)
                dealer_seen_counter[c] = 0

            for c in list(dealer_cards_persistent):
                if c not in dealer_seen_this_frame:
                    dealer_seen_counter[c] += 1
                    if dealer_seen_counter[c] > DECAY_LIMIT:
                        dealer_cards_persistent.remove(c)
                        del dealer_seen_counter[c]


            def log(msg):
                with open("bj_log.txt", "a") as f:
                    f.write(msg + "\n")


            log(f"Dealer Cards: {dealer_cards_persistent}")
            log(f"Player Cards: {player_cards_persistent}")   

            action = bj.basic_strategy(player_cards_persistent, dealer_cards_persistent)
            log(f"Recommendation: {action}")
            # tail -f bj_log.txt >> to see in other terminal

            # Informationen für Webserver in .txt files speichern
            with open("latest.txt", "w") as f:
                f.write(action)

            with open("player_cards.txt", "w") as f:
                f.write(" ".join(player_cards_persistent))

            with open("dealer_cards.txt", "w") as f:
                f.write(" ".join(dealer_cards_persistent))
    
