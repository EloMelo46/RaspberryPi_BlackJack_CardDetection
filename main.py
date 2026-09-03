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


def _environment_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return bool(default)
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _offset_detections(detections, offset_x: int, offset_y: int):
    adjusted = []
    for det in detections:
        item = dict(det)
        item["x"] = float(item.get("x", 0.0)) + offset_x
        item["y"] = float(item.get("y", 0.0)) + offset_y
        if "box" in item:
            x1, y1, x2, y2 = item["box"]
            item["box"] = (
                float(x1) + offset_x,
                float(y1) + offset_y,
                float(x2) + offset_x,
                float(y2) + offset_y,
            )
        adjusted.append(item)
    return adjusted


def main():
    print("[INIT] Starting Blackjack Card Detection (Hailo 10H)")
    if not HAILO_AVAILABLE:
        print_hailo_install_hint()
        return

    deck_registry = post.deck_registry
    deck_registry.refresh_from_disk()
    post.reset_player_stats()
    ready_errors = deck_registry.ready_errors()
    if ready_errors:
        print(f"[INIT] Setup incomplete: {', '.join(ready_errors)}")
        print("[INIT] Starting camera stream anyway so ROIs can be defined in the web UI.")

    camera, camera_type = init_camera()
    detector = HailoCardDetector(config.MODEL_PATH)

    engine = None
    commentary_enabled = bool(getattr(config, "COMMENTARY_ENABLED", False))
    if not commentary_enabled:
        print("[COMMENTARY] Disabled: explicit opt-in not enabled")
    elif os.environ.get("OPENAI_API_KEY"):
        engine = CommentaryEngine(output_dir="commentary_output", enable_audio=False, enabled=True)
        frequency = getattr(config, "COMMENTARY_FREQUENCY", "mittel")
        engine.set_frequency(frequency)
        print(f"[COMMENTARY] Frequency={frequency}, cooldown={engine.cooldown_seconds:.1f}s")
    else:
        print("[COMMENTARY] Disabled: OPENAI_API_KEY not set")

    print("[INIT] Ready. Camera preview is served through the app window.")

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

            deck_registry.refresh_from_disk()

            all_detections = []
            detections_by_deck = {}
            dealer_state = deck_registry.dealer_state()
            if dealer_state is not None:
                dealer_roi = dealer_state.deck.clamp(frame.shape[1], frame.shape[0])
                dealer_crop = frame[dealer_roi.y:dealer_roi.y + dealer_roi.height, dealer_roi.x:dealer_roi.x + dealer_roi.width]
                dealer_detections = detector.infer(dealer_crop) if dealer_crop.size else []
                dealer_detections = _offset_detections(dealer_detections, dealer_roi.x, dealer_roi.y)
                detections_by_deck[dealer_state.deck.deck_id] = dealer_detections
                all_detections.extend(dealer_detections)

            for deck in deck_registry.decks:
                if not deck.enabled or deck.is_dealer():
                    continue
                roi = deck.clamp(frame.shape[1], frame.shape[0])
                crop = frame[roi.y:roi.y + roi.height, roi.x:roi.x + roi.width]
                if crop.size == 0:
                    continue
                deck_detections = detector.infer(crop)
                deck_detections = _offset_detections(deck_detections, roi.x, roi.y)
                detections_by_deck[deck.deck_id] = deck_detections
                all_detections.extend(deck_detections)

            post.update_deck_tracking(detections_by_deck, frame.shape[1], frame.shape[0])
            post.update_text_files()

            # Build state and run commentary engine in background (non-blocking)
            try:
                state = post.get_game_state_dict()
                if engine is not None:
                    engine.process_state_non_blocking(state)
            except Exception as e:
                print(f"[COMMENTARY] Error: {e}")

            annotated_frame = post.annotate_frame(frame.copy(), all_detections, frame.shape[1])
            post.save_frame_and_info(annotated_frame)

            frame_count += 1
            if frame_count % 30 == 0:
                elapsed = time.time() - start_time
                fps = frame_count / elapsed
                print(
                    f"[INFO] Frame {frame_count}, FPS: {fps:.2f}, "
                    f"Active deck: {deck_registry.active_deck_id}, Cards: {deck_registry.get_active_state().cards if deck_registry.get_active_state() else []}, Dealer: {dealer_state.cards if dealer_state else []}"
                )

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
        print("[CLEANUP] Done")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Blackjack card detection with optional card counting decks")
    parser.add_argument("--decks", type=int, default=None, help="Number of decks used for True Count calculation")
    parser.add_argument(
        "--commentary-frequency",
        type=str,
        default="mittel",
        choices=["wenig", "mittel", "staendig"],
        help="Commentary frequency: wenig, mittel, staendig (default: mittel)",
    )
    parser.add_argument(
        "--enable-commentary",
        action="store_true",
        help="Explicitly enable OpenAI commentary API calls",
    )
    args = parser.parse_args()
    if args.decks is not None:
        try:
            config.NUM_DECKS = post.save_deck_count(int(args.decks))
        except Exception:
            config.NUM_DECKS = post.load_deck_count()
    else:
        config.NUM_DECKS = post.load_deck_count()
    config.COMMENTARY_ENABLED = bool(
        args.enable_commentary
        or _environment_flag("COMMENTARY_ENABLED", getattr(config, "COMMENTARY_ENABLED", False))
    )
    config.COMMENTARY_FREQUENCY = args.commentary_frequency

    main()
