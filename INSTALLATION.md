# Hailo 10H Installation Guide

This guide covers the complete setup for Blackjack Card Detection on Hailo 10H.

## Prerequisites

- **Raspberry Pi 5** with Hailo 10H module installed
- **Python 3.10+** (check with `python3 --version`)
- **Camera**: Raspberry Pi Camera Module 3 or USB camera
- **Internet connection** for downloads

## Step 1: System Setup

### Update System Packages
```bash
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y libcamera-dev python3-pip python3-venv
```

### Check Python Version
```bash
python3 --version
# Should be 3.10 or higher
```

## Step 2: Create Virtual Environment

```bash
cd ~/RaspberryPi_BlackJack_CardDetection
python3 -m venv venv_bj
source venv_bj/bin/activate
```

## Step 3: Install PyPI Dependencies (Excluding hailo-platform)

```bash
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

This installs all packages EXCEPT `hailo-platform` (which must be installed separately).

## Step 4: Install Hailo Platform (CRITICAL)

### Option A: Manual Download from Hailo Developer Zone

1. Register at [Hailo Developer Zone](https://hailo.ai/developer-zone/software-downloads/)
2. Download **HailoRT wheel package** for your architecture:
   - Look for `hailort-X.Y.Z-cp310-cp310-linux_aarch64.whl` (or your Python version)
3. Install locally:
   ```bash
   pip install /path/to/hailort-X.Y.Z-cp310-cp310-linux_aarch64.whl
   ```

### Option B: Automated Setup (Recommended)

Follow the official Hailo RPi5 installation guide:
```bash
git clone https://github.com/hailo-ai/hailo-rpi5-examples.git
cd hailo-rpi5-examples
./install.sh
```

This handles driver installation + Python bindings automatically.

### Verify Installation
```bash
python3 -c "from hailo_platform import VDevice; print('✓ Hailo installed successfully')"
```

Expected output:
```
✓ Hailo installed successfully
```

## Step 5: Verify Camera

### For Raspberry Pi Camera Module 3:
```bash
libcamera-hello  # Should show camera preview
```

### For USB Camera:
```bash
v4l2-ctl --list-devices  # Should list USB camera
```

## Step 6: Prepare Model File

Ensure `yolo26m.hef` is in the project root:
```bash
ls -la yolo26m.hef
# Output: -rw-r--r-- ... yolo26m.hef
```

If missing, download from Hailo Model Zoo or your training setup.

## Step 7: Test Installation

### Test Hailo Inference
```bash
source venv_bj/bin/activate
python3 -c "
from hailo_platform import HEF, VDevice
import numpy as np

# Try loading the model
try:
    hef = HEF('./yolo26m.hef')
    vdevice = VDevice(hef)
    print('✓ Model loaded successfully')
    vdevice.close()
except Exception as e:
    print(f'✗ Error: {e}')
"
```

### Test Camera
```bash
python3 -c "
import cv2
cap = cv2.VideoCapture(0)
if cap.isOpened():
    print('✓ Camera available')
    cap.release()
else:
    print('✗ Camera not found')
"
```

## Step 8: Run Application

### Terminal 1: Start Detection
```bash
source venv_bj/bin/activate
python3 run_card_detection.py
```

Expected output:
```
[INIT] Starting Blackjack Card Detection (Hailo 10H)
[CAMERA] Initializing Raspberry Pi Camera (picamera2)...
[CAMERA] Raspberry Pi Camera initialized successfully
[HAILO] Loading HEF model from ./yolo26m.hef
[HAILO] Model loaded successfully
[HAILO] Input shape: (1, 480, 640, 3)
[HAILO] Output layers: ['output']
[INIT] Ready. Press 'q' to quit.
```

Press 'q' to exit.

### Terminal 2: Start Web Server
```bash
source venv_bj/bin/activate
python3 server.py
```

Expected output:
```
 * Running on http://0.0.0.0:5000
```

### Terminal 3: Access Dashboard
```bash
# On any device with browser:
open http://<raspberry-pi-ip>:5000
# or
firefox http://<raspberry-pi-ip>:5000
```

## Troubleshooting

### Error: `ModuleNotFoundError: No module named 'hailo_platform'`

**Cause**: Hailo platform not installed

**Solution**:
```bash
# Verify installation
python3 -c "from hailo_platform import VDevice"

# If fails, reinstall:
pip install /path/to/hailort-*.whl

# Or follow Option B above
```

### Error: `FileNotFoundError: yolo26m.hef not found`

**Cause**: Model file missing

**Solution**:
```bash
# Check if file exists
ls -la yolo26m.hef

# If missing, copy from your training setup
cp /path/to/yolo26m.hef ./
```

### Error: Camera not found

**Cause**: Camera not connected or driver issue

**Solution for Raspberry Pi Camera**:
```bash
# Enable camera in raspi-config
sudo raspi-config
# Navigate: Interface Options > Camera > Enable

# Reboot
sudo reboot

# Test
libcamera-hello
```

**Solution for USB Camera**:
```bash
# List cameras
v4l2-ctl --list-devices

# Test with OpenCV
python3 -c "
import cv2
cap = cv2.VideoCapture(0)
ret, frame = cap.read()
print(f'Captured: {frame.shape if ret else \"Failed\"}')
cap.release()
"
```

### Error: Low FPS or slow inference

**Causes**:
- Hailo 10H not properly connected
- Thermal throttling
- High resolution/frame rate

**Solutions**:
```python
# Edit run_card_detection.py and reduce:
FPS = 8              # Lower frame rate
FRAME_WIDTH = 480    # Lower resolution
FRAME_HEIGHT = 360
```

### Error: `cv2.error: (-215:Assertion failed)`

**Cause**: Frame format/shape mismatch

**Solution**: Ensure camera returns correct RGB format:
```bash
# Test camera output
python3 -c "
from picamera2 import Picamera2
picam2 = Picamera2()
config = picam2.create_preview_configuration(
    main={'size': (640, 480), 'format': 'RGB888'}
)
picam2.configure(config)
picam2.start()
frame = picam2.capture_array()
print(f'Frame shape: {frame.shape}, dtype: {frame.dtype}')
"
```

## Performance Optimization

### Check Current Performance
```bash
# Monitor FPS in console output
python3 run_card_detection.py | grep "FPS:"
```

### Optimize Settings
```python
# In run_card_detection.py:

# Reduce inference load
CONFIDENCE_THRESHOLD = 0.5      # Higher = fewer detections
DECAY_LIMIT = 15                # Faster card removal

# Reduce I/O
# Only save frame every N frames:
if frame_count % 3 == 0:
    save_frame_and_info(annotated_frame)
```

### Monitor Hailo Device
```bash
# Check device status
hailortcli info

# Monitor temperature
watch -n 1 hailortcli fw-logger  # If available
```

## Next Steps

1. ✅ System prepared
2. ✅ Hailo installed
3. ✅ Camera tested
4. ✅ Model loaded
5. 🎮 **Start detecting cards!**

```bash
python3 run_card_detection.py & python3 server.py
```

## References

- [Hailo Documentation](https://docs.hailo.ai/)
- [Hailo RPi5 Examples](https://github.com/hailo-ai/hailo-rpi5-examples)
- [Hailo Python API](https://hailo.ai/developer-zone/documentation/hailort-v4-18-0/?page=api%2Fpython_api.html)
- [Blackjack Basic Strategy](https://www.blackjackappraisal.com/)
