#!/usr/bin/env python3
import time
import argparse
import os
import cv2
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

import config
from camera import init_camera
from hailo_inference import HailoCardDetector, HAILO_AVAILABLE, print_hailo_install_hint
import postprocessing as post
from commentary_engine import CommentaryEngine


def main():
    print("[INIT] Starting Blackjack Card Detection (Hailo 10H)")
    if not HAILO_AVAILABLE:
        print_hailo_install_hint()
        return

    camera, camera_type = init_camera()
    detector = HailoCardDetector(config.MODEL_PATH)
    # Initialize commentary engine; enable audio only if OPENAI_API_KEY present
    commentary_enabled = bool(os.environ.get("OPENAI_API_KEY"))
    engine = CommentaryEngine(output_dir="commentary_output", enable_audio=commentary_enabled)
    # Configure commentary frequency (wenig|mittel|staendig)
    frequency = getattr(config, "COMMENTARY_FREQUENCY", "mittel")
    engine.set_frequency(frequency)
    print(f"[COMMENTARY] Frequency={frequency}, cooldown={engine.cooldown_seconds:.1f}s")

    print("[INIT] Ready. Press 'q' to quit.")

    frame_count = 0
    start_time = time.time()

    try:
        while True:
            if camera_type == "picamera2":
                frame = cv2.cvtColor(camera.capture_array(), cv2.COLOR_BGR2RGB)
            else:
                ret, frame_bgr = camera.read()
                if not ret:
                    print("[CAMERA] Failed to capture frame")
                    break
                frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

            detections = detector.infer(frame)
            post.update_card_tracking(detections, frame.shape[1])
            post.update_text_files()

            # Build state and run commentary engine in background (non-blocking)
            try:
                state = post.get_game_state_dict()
                engine.process_state_non_blocking(state)
            except Exception as e:
                print(f"[COMMENTARY] Error: {e}")

            annotated_frame = post.annotate_frame(frame.copy(), detections, frame.shape[1])
            post.save_frame_and_info(annotated_frame)

            display_frame = cv2.cvtColor(annotated_frame, cv2.COLOR_RGB2BGR)
            cv2.imshow("Blackjack Card Detection", display_frame)

            frame_count += 1
            if frame_count % 30 == 0:
                elapsed = time.time() - start_time
                fps = frame_count / elapsed
                print(
                    f"[INFO] Frame {frame_count}, FPS: {fps:.2f}, "
                    f"Player: {post.player_cards_persistent}, Dealer: {post.dealer_cards_persistent}"
                )

            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("[EXIT] Quitting...")
                break

    except KeyboardInterrupt:
        print("\n[EXIT] Interrupted by user")
    except Exception as e:
        print(f"[ERROR] {e}")

    finally:
        print("[CLEANUP] Closing resources...")
        if camera_type == "picamera2":
            try:
                camera.stop()
            except Exception:
                pass
        else:
            camera.release()

        detector.close()
        cv2.destroyAllWindows()
        print("[CLEANUP] Done")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Blackjack card detection with optional card counting decks")
    parser.add_argument("--decks", type=int, default=1, help="Number of decks used for True Count calculation (default: 1)")
    parser.add_argument(
        "--commentary-frequency",
        type=str,
        default="mittel",
        choices=["wenig", "mittel", "staendig"],
        help="Commentary frequency: wenig, mittel, staendig (default: mittel)",
    )
    args = parser.parse_args()
    try:
        config.NUM_DECKS = int(args.decks)
    except Exception:
        config.NUM_DECKS = 1
    config.COMMENTARY_FREQUENCY = args.commentary_frequency

    main()
