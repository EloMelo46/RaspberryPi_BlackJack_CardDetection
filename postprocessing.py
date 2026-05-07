import cv2
import json
from config import OUTPUT_DIR, CARD_LABELS, DECAY_LIMIT, NUM_DECKS
import card_logic as bj
from preprocessing import limit_detections_per_class

# Persistent state
player_cards_persistent = []
dealer_cards_persistent = []
player_seen_counter = {}
dealer_seen_counter = {}


def update_card_tracking(detections, frame_width):
    """
    Update persistent card lists based on detections.
    Classifies cards as player (left) or dealer (right) based on frame midpoint.
    """
    global player_cards_persistent, dealer_cards_persistent
    global player_seen_counter, dealer_seen_counter

    middle_x = frame_width // 2
    best_detections = limit_detections_per_class(detections)

    detected_player_cards = set()
    detected_dealer_cards = set()

    for det in best_detections:
        card_label = CARD_LABELS[det['class_id']]
        det_x = det['x']

        if det_x < middle_x:
            detected_player_cards.add(card_label)
            player_seen_counter[card_label] = 0
        else:
            detected_dealer_cards.add(card_label)
            dealer_seen_counter[card_label] = 0

    # NOTE:
    # This preserves your current behavior, but it does not truly keep cards across missed frames.
    # I left it unchanged so only the inference path is fixed.
    player_cards_persistent = list(detected_player_cards)
    dealer_cards_persistent = list(detected_dealer_cards)

    for card in list(player_seen_counter):
        if card not in detected_player_cards:
            player_seen_counter[card] += 1

    for card in list(dealer_seen_counter):
        if card not in detected_dealer_cards:
            dealer_seen_counter[card] += 1

    player_cards_persistent = [c for c in player_cards_persistent if player_seen_counter.get(c, 0) < DECAY_LIMIT]
    dealer_cards_persistent = [c for c in dealer_cards_persistent if dealer_seen_counter.get(c, 0) < DECAY_LIMIT]

    player_seen_counter = {k: v for k, v in player_seen_counter.items() if k in player_cards_persistent or v < DECAY_LIMIT}
    dealer_seen_counter = {k: v for k, v in dealer_seen_counter.items() if k in dealer_cards_persistent or v < DECAY_LIMIT}

    globals()["player_cards_persistent"] = player_cards_persistent
    globals()["dealer_cards_persistent"] = dealer_cards_persistent
    globals()["player_seen_counter"] = player_seen_counter
    globals()["dealer_seen_counter"] = dealer_seen_counter


def card_hi_lo(card_label: str) -> int:
    """Return Hi-Lo weight for a card label (e.g. 'Kd', '10c', 'As')."""
    try:
        rank = bj.normalize_card(card_label)
    except Exception:
        rank = str(card_label)

    if rank in ["2", "3", "4", "5", "6"]:
        return 1
    if rank in ["7", "8", "9"]:
        return 0
    # 10, J, Q, K, A
    return -1


def compute_counts(num_decks: int = NUM_DECKS) -> dict:
    """Compute Hi-Lo running and true counts (combined for all cards).
    
    Running count: sum of all card values seen
    True count: running count / decks in shoe (parameter)
    """
    all_cards = player_cards_persistent + dealer_cards_persistent
    running_count = sum(card_hi_lo(c) for c in all_cards)
    
    # Avoid division by zero
    if num_decks <= 0:
        num_decks = 1
    
    true_count = running_count / float(num_decks)
    
    return {
        "running_count": int(running_count),
        "true_count": float(true_count),
        "decks": int(num_decks),
    }


def compute_strategy():
    """Compute Basic Strategy recommendation."""
    if not player_cards_persistent or not dealer_cards_persistent:
        return "Waiting for cards..."

    try:
        strategy = bj.basic_strategy(player_cards_persistent, dealer_cards_persistent)
        return strategy
    except Exception as e:
        print(f"[STRATEGY] Error: {e}")
        return "Error"


def save_frame_and_info(frame, filename=str(OUTPUT_DIR / "latest.jpg")):
    """Save frame to file for web interface."""
    try:
        cv2.imwrite(filename, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    except Exception as e:
        print(f"[OUTPUT] Failed to save frame: {e}")


def update_text_files():
    """Update text files for web interface."""
    try:
        strategy = compute_strategy()

        with open(OUTPUT_DIR / "latest.txt", "w") as f:
            f.write(strategy)

        with open(OUTPUT_DIR / "player_cards.txt", "w") as f:
            f.write(", ".join(player_cards_persistent) if player_cards_persistent else "No cards")

        with open(OUTPUT_DIR / "dealer_cards.txt", "w") as f:
            f.write(", ".join(dealer_cards_persistent) if dealer_cards_persistent else "No cards")
        # Also write Hi-Lo running/true counts to JSON for the web UI
        counts = compute_counts()
        try:
            with open(OUTPUT_DIR / "card_counts.json", "w") as jf:
                json.dump(counts, jf)
        except Exception as e:
            print(f"[OUTPUT] Failed to write card_counts.json: {e}")
    except Exception as e:
        print(f"[OUTPUT] Error writing text files: {e}")


def annotate_frame(frame, detections, frame_width):
    """Draw annotations on frame."""
    middle_x = frame_width // 2
    h, w = frame.shape[:2]

    cv2.line(frame, (middle_x, 0), (middle_x, h), (255, 255, 255), 2)

    best_detections = limit_detections_per_class(detections)

    for det in best_detections:
        if "box" in det:
            x1, y1, x2, y2 = det["box"]
        else:
            x, y, det_w, det_h = det['x'], det['y'], det['w'], det['h']
            x1 = x - det_w / 2.0
            y1 = y - det_h / 2.0
            x2 = x + det_w / 2.0
            y2 = y + det_h / 2.0

        conf = det['confidence']
        card_label = CARD_LABELS[det['class_id']]
        color = (0, 255, 0) if det['x'] < middle_x else (0, 0, 255)

        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
        cv2.putText(
            frame,
            f"{card_label} {conf:.2f}",
            (max(0, int(x1)), max(20, int(y1) - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
        )

    font = cv2.FONT_HERSHEY_SIMPLEX
    # Remove strategy text from frame — UI shows recommendation
    cv2.putText(frame, "PLAYER", (20, 30), font, 0.8, (0, 255, 0), 2)
    # Keep dealer label at top-left of dealer area
    # Dealer label moved only if needed by caller
    cv2.putText(frame, "DEALER", (middle_x + 20, 30), font, 0.8, (0, 0, 255), 2)

    # Compute and display Hi-Lo count (true count normalized by decks)
    counts = compute_counts()
    count_text = f"Count: {counts['true_count']:+.2f}  ({NUM_DECKS} deck)"
    cv2.putText(frame, count_text, (w - 380, h - 30), font, 0.8, (255, 255, 0), 2)

    return frame
