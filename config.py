from pathlib import Path

# Model / detection
MODEL_PATH = "./yolo26m.hef"
CONFIDENCE_THRESHOLD = 0.55
NMS_IOU_THRESHOLD = 0.45
DECAY_LIMIT = 50  # Frames until card is deleted if not seen
MAX_DETECTIONS_PER_CLASS = 1
PLAYER_BUST_CONFIRM_MS = 100  # Same bust hand must be detected continuously

# Video capture settings
FPS = 20
FRAME_WIDTH = 4056
FRAME_HEIGHT = 3040

# Browser stream output. Detection still uses the full camera frame above.
WEB_STREAM_MAX_WIDTH = 1920
WEB_STREAM_MAX_HEIGHT = 1080
WEB_STREAM_JPEG_QUALITY = 82

# Optional live calibration copied from working test pipeline.
BOX_OFFSET_X = 0.0
BOX_OFFSET_Y = 0.0
BOX_SCALE_X = 1.0
BOX_SCALE_Y = 1.0

# Directory for runtime outputs (images / text files)
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Card labels (52 cards)
CARD_LABELS = [
    '10c', '10d', '10h', '10s', '2c', '2d', '2h', '2s',
    '3c', '3d', '3h', '3s', '4c', '4d', '4h', '4s',
    '5c', '5d', '5h', '5s', '6c', '6d', '6h', '6s',
    '7c', '7d', '7h', '7s', '8c', '8d', '8h', '8s',
    '9c', '9d', '9h', '9s', 'Ac', 'Ad', 'Ah', 'As',
    'Jc', 'Jd', 'Jh', 'Js', 'Kc', 'Kd', 'Kh', 'Ks',
    'Qc', 'Qd', 'Qh', 'Qs'
]

# Default number of decks (can be overridden by CLI in main)
NUM_DECKS = 1

# Commentary frequency (can be overridden by CLI): wenig | mittel | staendig
COMMENTARY_ENABLED = False
COMMENTARY_FREQUENCY = "mittel"
