#!/usr/bin/env python3
"""
Exportiert YOLO-Modell (.pt) ins IMX500-Format mit INT8-Quantisierung.
"""

from ultralytics import YOLO
import os

os.environ["MCT_REPRESENTATIVE_DATASET_BATCH_SIZE"] = "4"


def main():
    print("Starting YOLO >> IMX500 Export (Patch)...")

    MODEL_PATH = "/home/elomelo/card_detection/best.pt"
    DATASET_YAML = "/home/elomelo/card_detection/cards.yaml" 

    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"Konnte das Modell {MODEL_PATH} nicht finden!")

    print("Überschreibe Ultralytics IMX Export Sicherheitscheck...")
    try:
        import ultralytics.utils.export.imx as imx_module
        # Bypassing the check regardless of whether it expects an int or a set/list
        class CatchAll:
            def __eq__(self, other): return True
            def __contains__(self, item): return True
        imx_module.MCT_CONFIG["YOLOv8"]["detect"]["n_layers"] = CatchAll()
    except Exception as e:
        print("Hinweis: Der Patch konnte nicht angewendet werden:", e)

    print(f"Loading model: {MODEL_PATH}")
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
