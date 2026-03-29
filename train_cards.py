#!/usr/bin/env python3
"""
Train YOLOv8n on card dataset and export for IMX500.
"""

from ultralytics import YOLO
import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

if __name__ == "__main__":
    # ===========================
    # TRAINING
    # ===========================
    print("Starte YOLOv8n-Training ...")

    model = YOLO("yolov8n.pt")  # vortrainiertes COCO-Modell
    results = model.train(
        data="/home/elomelo/card_detection/cards.yaml",
        epochs=25,
        imgsz=640,
        batch=8,
        name="cards_yolov8n"
    )

    # model path
    run_dir = getattr(results, "save_dir", "runs/detect/cards_yolov8n")
    best_model_path = os.path.join(run_dir, "weights", "best.pt")

    if os.path.exists(best_model_path):
        print(f"\nTraining abgeschlossen!")
        print(f"Bestes Modell: {best_model_path}")
    else:
        raise FileNotFoundError("Konnte 'best.pt' nicht finden – prüfe Trainingsergebnisse.")

    # ===========================
    # EXPORT FÜR IMX500
    # ===========================
    print("\nExportiere Modell für Sony IMX500 ...")

    model = YOLO(best_model_path)
    export_dir = model.export(
        format="imx",                      # offizieller IMX-Exporter (ab v8.3.223+)
        imgsz=640,                         # Eingangsgröße
        int8=True,                         # INT8-Quantisierung aktivieren
        data="/home/elomelo/card_detection/cards.yaml",  # repräsentatives Dataset für Calibration
        fraction=0.05                      # 5 % der Trainingsbilder für Kalibrierung
    )

    print(f"\nIMX-Export abgeschlossen!")
    print(f"Exportiertes Modellverzeichnis: {export_dir}")
    print("\nInhalt:")
    print(" ├─ model.dlc         → kompiliertes IMX-Netz")
    print(" ├─ labels.txt        → Klassenbezeichnungen")
    print(" ├─ metadata.json     → Modelldaten")
    print(" └─ calibration_data/ → verwendete Kalibrierungsbilder")
    print("\nNächster Schritt:")
    print("  Lade den Ordner auf deinen IMX500-Sensor (AITRIOS SDK oder Edge-Toolchain).")

    # ===========================
    # TRAININGSMETRIKEN VISUALISIEREN
    # ===========================
    print("\nErstelle Trainingsmetriken-Plot ...")

    # Pfad zur CSV-Datei mit den Metriken
    results_csv = os.path.join(run_dir, "results.csv")

    if not os.path.exists(results_csv):
        raise FileNotFoundError("Konnte 'results.csv' nicht finden – prüfe Trainingsausgabe.")

    # Daten laden
    df = pd.read_csv(results_csv)
    df.columns = df.columns.str.strip()

    # Subplots
    fig, axs = plt.subplots(nrows=5, ncols=2, figsize=(15, 15))

    # Diagramme zeichnen
    sns.lineplot(x='epoch', y='train/box_loss', data=df, ax=axs[0,0])
    sns.lineplot(x='epoch', y='train/cls_loss', data=df, ax=axs[0,1])
    sns.lineplot(x='epoch', y='train/dfl_loss', data=df, ax=axs[1,0])
    sns.lineplot(x='epoch', y='metrics/precision(B)', data=df, ax=axs[1,1])
    sns.lineplot(x='epoch', y='metrics/recall(B)', data=df, ax=axs[2,0])
    sns.lineplot(x='epoch', y='metrics/mAP50(B)', data=df, ax=axs[2,1])
    sns.lineplot(x='epoch', y='metrics/mAP50-95(B)', data=df, ax=axs[3,0])
    sns.lineplot(x='epoch', y='val/box_loss', data=df, ax=axs[3,1])
    sns.lineplot(x='epoch', y='val/cls_loss', data=df, ax=axs[4,0])
    sns.lineplot(x='epoch', y='val/dfl_loss', data=df, ax=axs[4,1])

    # Titel und Layout
    axs[0,0].set(title='Train Box Loss')
    axs[0,1].set(title='Train Class Loss')
    axs[1,0].set(title='Train DFL Loss')
    axs[1,1].set(title='Metrics Precision (B)')
    axs[2,0].set(title='Metrics Recall (B)')
    axs[2,1].set(title='Metrics mAP50 (B)')
    axs[3,0].set(title='Metrics mAP50-95 (B)')
    axs[3,1].set(title='Validation Box Loss')
    axs[4,0].set(title='Validation Class Loss')
    axs[4,1].set(title='Validation DFL Loss')

    plt.suptitle('Training Metrics and Loss', fontsize=24)
    plt.subplots_adjust(top=0.8)
    plt.tight_layout()
    plt.show()

    print("\nVisualisierung abgeschlossen – Diagramm angezeigt.")
