#!/usr/bin/env python3
"""
Exportiert YOLOv8-Modell (.pt) ins IMX500-Format mit INT8-Quantisierung.
Perfekt für Sony IMX500 AI-Kamera (Raspberry Pi).
"""

from ultralytics import YOLO
import os

os.environ["MCT_REPRESENTATIVE_DATASET_BATCH_SIZE"] = "4"


def main():
    print("🔹 Starte YOLO → IMX500 Export...")

    MODEL_PATH = "/home/elomelo/card_detection/best.pt"
    DATASET_YAML = "/home/elomelo/card_detection/cards.yaml"  # wichtig für Calibration
    EXPORT_DIR = os.path.join(os.path.dirname(MODEL_PATH), "imx_export_int8")
    os.makedirs(EXPORT_DIR, exist_ok=True)

    print(f"📦 Lade Modell: {MODEL_PATH}")
    model = YOLO(MODEL_PATH)

    try:
        export_dir = model.export(
            format="imx",          # offizieller Sony-IMX-Exporter
            imgsz=640,             # Eingangsgröße (muss zu deinem Training passen)
            device='cpu',          # kein CUDA auf dem Pi
            int8=True,             # INT8-Quantisierung aktivieren
            data=DATASET_YAML,     # repräsentatives Dataset
            fraction=0.02,         # 2 % der Trainingsdaten für Kalibrierung
            nms=True               # Non-Maximum Suppression für saubere Detections
        )

        print("\n✅ IMX-Export abgeschlossen!")
        print(f"📁 Exportiertes Modellverzeichnis: {export_dir}")
        print("Inhalt:")
        print(" ├─ model.dlc         → kompiliertes IMX-Netz")
        print(" ├─ labels.txt        → Klassenbezeichnungen")
        print(" ├─ metadata.json     → Modelldaten")
        print(" └─ calibration_data/ → verwendete Kalibrierungsbilder")

        print("\n💡 Nächster Schritt:")
        print("  ➜ Lade den Ordner auf deinen IMX500-Sensor (AITRIOS SDK oder Edge-Toolchain).")

    except Exception as e:
        print("❌ Fehler beim Export:", e)
        print("   ➜ Stelle sicher, dass du auf Linux bist und ultralytics[export] installiert ist.")

if __name__ == "__main__":
    main()
