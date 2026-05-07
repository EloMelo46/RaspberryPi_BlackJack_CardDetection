#!/usr/bin/env python3
"""
Train YOLO26 on card dataset and export as ONNX for Hailo deployment.
"""

from ultralytics import YOLO
import os
import numpy as np
import onnx
import onnxruntime as ort
from onnx import shape_inference
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

if __name__ == "__main__":
    # ===========================
    # TRAINING
    # ===========================
    print("Starting YOLO26m training ...")

    model = YOLO("yolo26m.pt")  # pretrained COCO model
    results = model.train(
        data="cards.yaml",
        epochs=200,
        imgsz=640,
        batch=16,
        device=0,
        workers=8,
        name="cards_yolo26m"
    )

    # model path
    run_dir = getattr(results, "save_dir", "runs/detect/cards_yolo26m_hailo_onnx")
    best_model_path = os.path.join(run_dir, "weights", "best.pt")

    if os.path.exists(best_model_path):
        print("\nTraining complete!")
        print(f"Best model: {best_model_path}")
    else:
        raise FileNotFoundError("Could not find 'best.pt' - check training output.")

    # ===========================
    # EXPORT: ONNX for Hailo
    # ===========================
    print("\nExporting model as ONNX (opset=11, static)...")

    model = YOLO(best_model_path)
    export_dir = model.export(
        format="onnx",
        imgsz=640,
        opset=11,
        simplify=True,
        dynamic=False
    )

    if isinstance(export_dir, str) and export_dir.endswith(".onnx"):
        onnx_path = export_dir
    elif isinstance(export_dir, str) and os.path.isdir(export_dir):
        onnx_candidates = [
            os.path.join(export_dir, fname)
            for fname in os.listdir(export_dir)
            if fname.endswith(".onnx")
        ]
        onnx_path = onnx_candidates[0] if onnx_candidates else None
    else:
        onnx_path = None

    if not onnx_path or not os.path.exists(onnx_path):
        raise FileNotFoundError(f"Could not find exported ONNX file: {export_dir}")

    print("\nONNX export complete!")
    print(f"Exported file: {onnx_path}")

    # ===========================
    # ONNX VALIDATION
    # ===========================
    print("\nChecking ONNX model (checker + shape inference + runtime test) ...")

    model_onnx = onnx.load(onnx_path)
    onnx.checker.check_model(model_onnx)
    print("ONNX checker: OK")

    inferred = shape_inference.infer_shapes(model_onnx)
    inferred_path = onnx_path.replace(".onnx", "_inferred.onnx")
    onnx.save(inferred, inferred_path)
    print(f"Shape inference: OK ({inferred_path})")

    session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    dummy = np.random.randn(1, 3, 640, 640).astype(np.float32)
    outputs = session.run(None, {input_name: dummy})
    print(f"ONNX Runtime Test: OK ({len(outputs)} Outputs)")

    # ===========================
    # VISUALIZE TRAINING METRICS
    # ===========================
    print("\nCreating training metrics plot ...")

    # Path to the CSV file with metrics
    results_csv = os.path.join(run_dir, "results.csv")

    if not os.path.exists(results_csv):
        raise FileNotFoundError("Could not find 'results.csv' - check training output.")

    # Load data
    df = pd.read_csv(results_csv)
    df.columns = df.columns.str.strip()

    # Subplots
    fig, axs = plt.subplots(nrows=5, ncols=2, figsize=(15, 15))

    # Draw charts
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

    # Titles and layout
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

    print("\nVisualization complete - chart displayed.")
