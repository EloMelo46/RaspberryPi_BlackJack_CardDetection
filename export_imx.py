#!/usr/bin/env python3
"""
Exportiert YOLO-Modell (.pt) ins IMX500-Format mit INT8-Quantisierung.
"""

from ultralytics import YOLO
import os

os.environ["MCT_REPRESENTATIVE_DATASET_BATCH_SIZE"] = "4"


def main():
    print("Starte YOLO >> IMX500 Export...")

    MODEL_PATH = "/home/elomelo/card_detection/best_y11n.pt"
    DATASET_YAML = "/home/elomelo/card_detection/cards.yaml" 

    print(f"Lade Modell: {MODEL_PATH}")
    model = YOLO(MODEL_PATH)

    try:
        export_dir = model.export(
            format="imx",          # offizieller Sony-IMX-Exporter
            imgsz=640,             # Eingangsgrösse (muss zu Training passen)
            device='cpu',          # kein CUDA
            int8=True,             # INT8-Quantisierung aktivieren
            data=DATASET_YAML,     # repräsentatives Dataset
            fraction=0.01,         # 1 % der Trainingsdaten für Kalibrierung
            nms=True               # Non-Maximum Suppression 
        )

        print("\nIMX-Export abgeschlossen!")
        print(f"Exportiertes Modellverzeichnis: {export_dir}")
        print("Inhalt:")
        print(" ├─ model.dlc         → kompiliertes IMX-Netz")
        print(" ├─ labels.txt        → Klassenbezeichnungen")
        print(" ├─ metadata.json     → Modelldaten")
        print(" └─ calibration_data/ → verwendete Kalibrierungsbilder")

        print("\nNächster Schritt:")
        print("  Lade das Packer-File auf deinen IMX500-Sensor (AITRIOS SDK oder Edge-Toolchain).")

    except Exception as e:
        print("Fehler beim Export:", e)
        print("Sicherstellen, dass das OS Linux ist und ultralytics[export] installiert ist.")

if __name__ == "__main__":
    main()
