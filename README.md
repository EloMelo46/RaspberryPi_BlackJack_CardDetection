# Blackjack Card Detection & Strategy Assistant

A real-time Blackjack assistant for Raspberry Pi using the **Hailo 10H AI Accelerator**. The system captures the full 12MP camera image, lets you define smaller player/dealer ROIs in a web UI, runs card detection inside those ROIs, and provides Blackjack recommendations, card counting, and per-player scoring.

## Features
- **Full-frame Capture, ROI Detection**: Uses the full 4056x3040 camera frame as the source image while detecting cards in smaller 640x480 player/dealer ROIs.
- **Multi-player Table Setup**: Define named player boxes and a dealer box directly in the browser; drag boxes on top of the live video.
- **Strategy Engine**: Automatic recommendation for the active player using detected player cards and dealer cards.
- **Card Counting**: Global Hi-Lo True Count across all visible player/dealer ROIs, with configurable shoe deck count.
- **Scoring Flow**: Tracks wins, losses, pushes, score, blackjacks, doubles, and split hands per player.
- **Web Dashboard**: Desktop and mobile-friendly live camera stream, ROI controls, active player selection, recommendations, and score dashboard.
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

### Start Card Detection
```bash
source venv_bj/bin/activate

# Uses saved deck count from the web UI, or default 1 deck
python main.py

# Optional: explicitly set and save deck count for True Count
python main.py --decks 6
```

Expected output:
```
[INIT] Starting Blackjack Card Detection (Hailo 10H)
[CAMERA] Initializing Raspberry Pi Camera (picamera2)...
[CAMERA] Raspberry Pi Camera initialized successfully
[HAILO] Loading HEF model from ./yolo26m.hef
[HAILO] Model loaded successfully
[INIT] Setup incomplete: Dealer ROI missing
[INIT] Starting camera stream anyway so ROIs can be defined in the web UI.
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

### Deck ROI Mode

The web dashboard is the table setup and gameplay controller:
- Enter the number of players and player names, then click **Create player boxes**.
- Add or replace a dealer ROI with **Add dealer**.
- Drag the 640x480 ROI boxes on top of the full camera image.
- Click a player box or player row to select the active player.
- Set the number of decks in the shoe with **Set decks** so True Count is correct.
- Use **Fullscreen** on desktop/mobile for a cleaner play view.
- ROI layouts are stored in `outputs/decks.json`; runtime state is stored separately.

You'll see:
- **Live camera feed** downscaled for the browser while detection still uses full-resolution ROI crops
- **Player/dealer ROI overlays** on the full table image
- **Active-player recommendation** for the selected player
- **True Count** and count meaning, e.g. high/low cards expected
- **Wins / Pushes / Losses / Score** for the selected player
- **Split and Double controls** for cases that need manual player decisions

## Project Structure
```
RaspberryPi_BlackJack_CardDetection/
├── main.py                      # Entrypoint with CLI deck option
├── config.py                    # Configuration constants
├── camera.py                    # Camera initialization wrapper
├── hailo_inference.py           # Hailo detector class & inference
├── preprocessing.py             # Image processing (letterbox, NMS, etc.)
├── postprocessing.py            # Card tracking, counting, annotation
├── deck_config.py               # Persistent player/dealer ROI config
├── deck_manager.py              # Per-ROI card state, scoring helpers, count summary
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
- Default Raspberry Pi camera resolution: 4056x3040 @ target 20 FPS
- Browser stream is saved separately as a downscaled Full HD JPEG for smoother web UI FPS

### 2. Hailo Inference
- Loads `yolo26m.hef` model into VDevice
- Runs YOLOv26 object detection on each configured ROI, not the whole 12MP frame
- Each ROI defaults to 640x480 but is cropped from the full-resolution source frame
- Outputs: bounding boxes, class IDs, confidence scores

### 3. ROI and Card Tracking
- `outputs/decks.json` stores persistent player/dealer ROI boxes and active player ID
- `outputs/deck_state.json` stores runtime card state, recommendations, counts, and per-player stats
- `outputs/decks.bak.json` is written as a backup before ROI config is replaced
- **Memory Decay System**: Cards persist for `DECAY_LIMIT` frames if not detected again
- **Player/Dealer Classification**: Based on explicitly configured ROIs
- **Best Detection**: Only highest confidence box per card class

### 4. Strategy Calculation
- Uses **Blackjack Basic Strategy** (4-8 Deck, Dealer Hits Soft 17)
- Takes active player's cards + dealer cards as input
- Returns: Hit, Stand, Double, or Split

### 5. Counting and Scoring
- Uses Hi-Lo card counting over all visible player/dealer ROIs
- Displays only True Count in the UI
- Deck count can be set in the web UI or via `python main.py --decks N`
- Scores players when the dealer reaches terminal state: dealer stands at 17+ or busts
- Blackjack wins count as +2
- Marked doubles score double in either direction
- Split flow is guided with Start Split, Next Hand, Finish Split, and Cancel Split controls
- Current-round undo is kept internal, but not exposed as a normal gameplay button

### 6. Web Output
- Saves frame: `latest.jpg`
- Saves browser frame: `latest_web.jpg`
- Saves strategy: `latest.txt`
- Saves cards, counts, deck state, and player stats in `outputs/`
- Flask server serves the dashboard and JSON endpoints

## Configuration

Edit `config.py` to adjust:

```python
MODEL_PATH = "./yolo26m.hef"              # HEF model path
CONFIDENCE_THRESHOLD = 0.55               # Detection confidence
DECAY_LIMIT = 50                          # Frames until card removal
NMS_IOU_THRESHOLD = 0.45                  # NMS threshold
MAX_DETECTIONS_PER_CLASS = 1              # Max detections per card
FPS = 20                                  # Target frame rate
FRAME_WIDTH = 4056                        # Full camera source width
FRAME_HEIGHT = 3040                       # Full camera source height
WEB_STREAM_MAX_WIDTH = 1920               # Browser stream max width
WEB_STREAM_MAX_HEIGHT = 1080              # Browser stream max height
WEB_STREAM_JPEG_QUALITY = 82              # Browser stream JPEG quality
NUM_DECKS = 1                             # Default decks for True Count
```

Set deck count in the web UI, or override it at startup:
```bash
python main.py --decks 6  # For True Count in 6-deck shoe
```

## Runtime Files

The following files are generated under `outputs/` and are intentionally ignored by Git:

```text
outputs/decks.json         # Persistent player/dealer ROI layout
outputs/decks.bak.json     # Backup of previous ROI layout
outputs/deck_count.json    # Shoe deck count for True Count
outputs/deck_state.json    # Current runtime deck/card state
outputs/player_stats.json  # Per-player score and result history
outputs/card_counts.json   # Current Hi-Lo count summary
outputs/latest.jpg         # Full annotated frame
outputs/latest_web.jpg     # Downscaled browser frame
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
