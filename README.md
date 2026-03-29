# Blackjack Card Detection & Strategy Assistant

A real-time Blackjack assistant for Raspberry Pi using the Sony IMX500 AI Camera. The system detects playing cards, tracks them for the player and dealer, and provides optimal "Basic Strategy" recommendations via a web dashboard.

## Features
- **Real-time Detection**: Card recognition using YOLOv8 on edge AI hardware.
- **Strategy Engine**: Automatic calculation of Hit, Stand, Double, or Split.
- **Web Dashboard**: Live camera stream and dynamic game state visualization.
- **Edge Optimized**: Specifically designed for the Sony IMX500 application module library.

## Dataset & Finetuning
The model has been finetuned to improve accuracy for the specific setup.
- **Dataset**: A custom dataset is available publicly on Roboflow Universe: [card detection Computer Vision Dataset](https://universe.roboflow.com/elomelo/card-detection-2vulo).

## Model Export (Sony IMX500)
To run the model on the Sony IMX500 AI Camera, the YOLO `.pt` model must be exported to the `.dlc` format with INT8 quantization.
**Important**: The Sony IMX500 exporter (`ultralytics[export]`) currently requires a **Linux OS**. You must run the export script on Linux (e.g., WSL2 or native Linux).
- Export Script: `python export_imx.py`

## Installation & Usage
1. Clone the repository.
2. Install dependencies: `pip install -r requirements.txt`.
3. Start the detection: `python run_card_detection.py`.
4. Start the web server: `python server.py`.
5. Open your browser at `http://<pi-ip>:5000`.
