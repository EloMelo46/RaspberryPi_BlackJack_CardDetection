# Blackjack Card Detection & Strategy Assistant

A real-time Blackjack assistant for Raspberry Pi using the **Hailo 10H AI Accelerator**. The system detects playing cards in real-time, tracks them for the player and dealer, and provides optimal "Basic Strategy" recommendations via a web dashboard.

## Features
- **Real-time Detection**: Card recognition using YOLOv26 on Hailo 10H AI accelerator (2 TOPS).
- **Strategy Engine**: Automatic calculation of Hit, Stand, Double, or Split via Basic Strategy.
- **Web Dashboard**: Live camera stream and dynamic game state visualization.
- **Edge Optimized**: Specifically designed for Hailo 10H hardware with native HEF model loading.
- **Camera Support**: Raspberry Pi camera (picamera2) with USB fallback support.

## Hardware Requirements
- **Hailo 10H AI Accelerator** (2 TOPS)
- **Raspberry Pi 5** (recommended)
- **Camera**: Raspberry Pi Camera Module 3 or USB camera
- **Pre-trained Model**: `yolo26m.hef` (placed in project root)

## Installation & Setup

### 1. Clone & Create Virtual Environment
```bash
git clone https://github.com/elomelo/RaspberryPi_BlackJack_CardDetection.git
cd RaspberryPi_BlackJack_CardDetection
python3 -m venv venv_bj
source venv_bj/bin/activate
```

### 2. Install Hailo Platform (Manual Download)
The `hailo-platform` package must be downloaded from the [Hailo Developer Zone](https://hailo.ai/developer-zone/software-downloads/) (requires registration).

Download and install:
```bash
# After downloading from Hailo Developer Zone
pip install hailort-*.whl
```

**Or** follow [Hailo RPi5 Installation Guide](https://github.com/hailo-ai/hailo-rpi5-examples/blob/main/doc/install-raspberry-pi5.md) for complete setup.

### 3. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 4. Verify HEF Model
Ensure `yolo26m.hef` is in the project root directory:
```bash
ls -la yolo26m.hef
```

### 5. Install System Dependencies (Raspberry Pi)
```bash
sudo apt-get update
sudo apt-get install -y libcamera-dev
```

## Usage

### Start Card Detection & Web Server
```bash
source venv_bj/bin/activate

# Default: 1 deck (for True Count calculation)
python main.py

# Or specify deck count
python main.py --decks 6
```

Expected output:
```
[INIT] Starting Blackjack Card Detection (Hailo 10H)
[CAMERA] Initializing Raspberry Pi Camera (picamera2)...
[CAMERA] Raspberry Pi Camera initialized successfully
[HAILO] Loading HEF model from ./yolo26m.hef
[HAILO] Model loaded successfully
[INIT] Ready. Press 'q' to quit.
```

### Start Web Dashboard (in another terminal)
```bash
source venv_bj/bin/activate
python websocket.py
```

### Access Web Dashboard
Open browser and navigate to:
```
http://<raspberry-pi-ip>:5000
```

You'll see:
- **Live camera feed** with detected cards and annotations
- **Player cards** (left side, green boxes)
- **Dealer cards** (right side, red boxes)
- **Hi-Lo True Count** (displayed on frame)
- **Strategy recommendation** (Hit/Stand/Double/Split based on Basic Strategy)

## Project Structure
```
RaspberryPi_BlackJack_CardDetection/
├── main.py                      # Entrypoint with CLI deck option
├── config.py                    # Configuration constants
├── camera.py                    # Camera initialization wrapper
├── hailo_inference.py           # Hailo detector class & inference
├── preprocessing.py             # Image processing (letterbox, NMS, etc.)
├── postprocessing.py            # Card tracking, counting, annotation
├── card_logic.py                # Blackjack Basic Strategy engine
├── websocket.py                 # Flask web UI server
├── cards.yaml                   # Dataset config (reference)
├── yolo26m.hef                  # Pre-trained model (add manually)
├── requirements.txt             # Python dependencies
├── INSTALLATION.md              # Detailed setup guide
└── README.md                    # This file
```

## How It Works

### 1. Camera Capture
- Captures frames from Raspberry Pi camera (picamera2) or USB camera
- Default resolution: 640x480 @ 20 FPS

### 2. Hailo Inference
- Loads `yolo26m.hef` model into VDevice
- Runs YOLOv26 object detection
- Outputs: bounding boxes, class IDs, confidence scores

### 3. Card Tracking
- **Memory Decay System**: Cards persisted for 20 frames if not detected
- **Player/Dealer Classification**: Divided by vertical center line
- **Best Detection**: Only highest confidence box per card class

### 4. Strategy Calculation
- Uses **Blackjack Basic Strategy** (4-8 Deck, Dealer Hits Soft 17)
- Takes player cards + dealer upcard as input
- Returns: Hit, Stand, Double, or Split

### 5. Web Output
- Saves frame: `latest.jpg`
- Saves strategy: `latest.txt`
- Saves cards: `player_cards.txt`, `dealer_cards.txt`
- Flask server serves these to web dashboard

## Configuration

Edit `config.py` to adjust:

```python
MODEL_PATH = "./yolo26m.hef"              # HEF model path
CONFIDENCE_THRESHOLD = 0.55               # Detection confidence
DECAY_LIMIT = 50                          # Frames until card removal
NMS_IOU_THRESHOLD = 0.45                  # NMS threshold
MAX_DETECTIONS_PER_CLASS = 1              # Max detections per card
FPS = 20                                  # Target frame rate
FRAME_WIDTH = 640                         # Camera resolution
FRAME_HEIGHT = 480
NUM_DECKS = 1                             # Default decks (override with --decks)
```

Or override deck count at runtime:
```bash
python main.py --decks 6  # For True Count in 6-deck shoe
```

## Troubleshooting

### Error: `hailo-platform` not found
**Solution**: Download and install manually from [Hailo Developer Zone](https://hailo.ai/developer-zone/software-downloads/)

### Error: `yolo26m.hef` not found
**Solution**: Place the pre-trained model in project root:
```bash
cp /path/to/yolo26m.hef ./
```

### Camera not detected
**Solution**: Check camera is connected:
```bash
# For Raspberry Pi camera
v4l2-ctl --list-devices

# Or test picamera2
libcamera-hello
```

## References
- [Hailo Documentation](https://docs.hailo.ai/)
- [Hailo RPi5 Examples](https://github.com/hailo-ai/hailo-rpi5-examples)
- [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics)
