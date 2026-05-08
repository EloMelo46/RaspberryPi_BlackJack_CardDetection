import cv2
import json
from config import OUTPUT_DIR, CARD_LABELS, DECAY_LIMIT, NUM_DECKS
import card_logic as bj
from preprocessing import limit_detections_per_class
from game_state import GameSession

# Persistent state
player_cards_persistent = []
dealer_cards_persistent = []
player_seen_counter = {}
dealer_seen_counter = {}

# Game session manages hands, splits and outcomes
session = GameSession()

# Game statistics
game_stats = {
    "player_wins": 0,
    "dealer_wins": 0,
    "pushes": 0,
    "blackjacks": 0,
    "last_outcome": None,
}
last_published_outcome = None


def load_game_stats():
    """Reset game stats on every process start."""
    global game_stats
    game_stats = {
        "player_wins": 0,
        "dealer_wins": 0,
        "pushes": 0,
        "blackjacks": 0,
        "last_outcome": None,
    }
    save_game_stats()


def save_game_stats():
    """Save game stats to JSON file."""
    stats_file = OUTPUT_DIR / "game_stats.json"
    try:
        # enrich stats with current session phase and leader
        try:
            game_stats["round_phase"] = get_round_phase()
            game_stats["current_leader"] = get_current_leader()
        except Exception:
            game_stats["round_phase"] = "unknown"
            game_stats["current_leader"] = "unknown"
        with open(stats_file, "w") as f:
            json.dump(game_stats, f, indent=2)
    except Exception as e:
        print(f"[STATS] Error writing stats: {e}")


def check_and_publish_outcomes():
    """
    Check if a game is complete (all player hands stand/bust and dealer has cards).
    If so, compute outcomes, update stats, and save results.
    """
    global game_stats, last_published_outcome
    
    # If dealer reached stand threshold, finalize round even if phase lagged.
    try:
        if session.phase == "dealer" and session.dealer_hand and session.dealer_hand.value() >= 17:
            session.phase = "compute"
    except Exception:
        pass

    # Only publish outcomes when session reached compute/complete phase
    if session.phase not in ("compute", "complete"):
        return

    # Require dealer hand to be present
    if not session.player_hands or not session.dealer_hand:
        return

    # Publish exactly once per round
    if getattr(session, "outcome_published", False):
        return

    # Compute outcomes
    outcomes = session.compute_outcomes()
    if not outcomes:
        return

    # Build a single outcome string for this round to prevent duplicate publishes
    outcome_str = None
    for res in outcomes:
        if res['result'] == 'win':
            outcome_str = "Player Win!"
            break
        if res['result'] == 'win_blackjack':
            outcome_str = "Blackjack! Player Win!"
            break
        if res['result'] == 'lose':
            outcome_str = "Dealer Wins"
            break
        if res['result'] == 'push':
            outcome_str = "Push"
            break

    if outcome_str is None:
        return

    # Update stats for each hand result (only once per round)
    for res in outcomes:
        if res['result'] == 'win':
            game_stats["player_wins"] += 1
        elif res['result'] == 'win_blackjack':
            game_stats["blackjacks"] += 1
            game_stats["player_wins"] += 1
        elif res['result'] == 'lose':
            game_stats["dealer_wins"] += 1
        elif res['result'] == 'push':
            game_stats["pushes"] += 1

    game_stats["last_outcome"] = outcome_str
    last_published_outcome = outcome_str
    session.outcome_published = True
    save_game_stats()

    # Mark round complete on session so UI can reflect it and prevent re-publishing
    try:
        # mark hands finished so all_done checks won't retrigger
        for h in session.player_hands:
            h.status = "finished"
        session.end_round()
    except Exception:
        pass


def get_round_phase() -> str:
    try:
        return session.phase
    except Exception:
        return "idle"


def get_current_leader() -> str:
    """Return who is currently leading: 'player', 'dealer', 'push', or 'unknown'.

    Logic: only decide when dealer has revealed its second card. Compare active
    player's hand value vs dealer value. If player bust -> dealer. If dealer
    bust -> player. If equal -> push.
    """
    try:
        if not session.player_hands:
            return "unknown"
        if not session.dealer_hand or len(session.dealer_hand.cards) < 2:
            return "unknown"

        active = session.get_active_hand() or session.player_hands[0]
        pv = active.value()
        dv = session.dealer_hand.value()

        if active.is_bust():
            return "dealer"
        if session.dealer_hand.is_bust():
            return "player"
        if pv > dv:
            return "player"
        if pv < dv:
            return "dealer"
        return "push"
    except Exception:
        return "unknown"


# Load stats on module import
load_game_stats()


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

    # Let the GameSession ingest current detections (it will manage hands / splits)
    session.assign_detected_cards(list(detected_player_cards), list(detected_dealer_cards))

    # NOTE: keep legacy decay counters based on raw detections, but expose the
    # session's aggregated view for counting and UI.
    player_cards_persistent = session.get_all_player_cards()
    dealer_cards_persistent = session.get_dealer_cards()

    for card in list(player_seen_counter):
        if card not in detected_player_cards:
            player_seen_counter[card] += 1

    for card in list(dealer_seen_counter):
        if card not in detected_dealer_cards:
            dealer_seen_counter[card] += 1

    player_cards_persistent = [c for c in player_cards_persistent if player_seen_counter.get(c, 0) < DECAY_LIMIT]
    dealer_cards_persistent = [c for c in dealer_cards_persistent if dealer_seen_counter.get(c, 0) < DECAY_LIMIT]
    # Identify expired cards (seen counter exceeded) and remove from session hands
    expired_player = [c for c, v in player_seen_counter.items() if v >= DECAY_LIMIT]
    expired_dealer = [c for c, v in dealer_seen_counter.items() if v >= DECAY_LIMIT]

    # Remove expired player cards from any player hands
    for c in expired_player:
        for h in session.player_hands:
            if c in h.cards:
                h.remove_card(c)
        # also drop from seen counter
        player_seen_counter.pop(c, None)

    # Remove expired dealer cards from dealer hand
    for c in expired_dealer:
        if session.dealer_hand and c in session.dealer_hand.cards:
            session.dealer_hand.remove_card(c)
        dealer_seen_counter.pop(c, None)

    # Rebuild persistent lists from session after removals
    player_cards_persistent = session.get_all_player_cards()
    dealer_cards_persistent = session.get_dealer_cards()

    # Clean up seen counters to keep only relevant keys
    player_seen_counter = {k: v for k, v in player_seen_counter.items() if k in player_cards_persistent or v < DECAY_LIMIT}
    dealer_seen_counter = {k: v for k, v in dealer_seen_counter.items() if k in dealer_cards_persistent or v < DECAY_LIMIT}

    # If both sides are empty, reset session
    if not player_cards_persistent and not dealer_cards_persistent:
        session.reset()
        # Clear last published outcome so next round can publish again
        try:
            global last_published_outcome
            last_published_outcome = None
            session.outcome_published = False
            save_game_stats()
        except Exception:
            pass
    # Persist current phase and leader for the web UI
    try:
        save_game_stats()
    except Exception:
        pass

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
    # Prefer the active player hand when available (handles splits)
    try:
        active = session.get_active_hand()
        if active and session.get_dealer_cards():
            return bj.basic_strategy(active.cards, session.get_dealer_cards())
        if not player_cards_persistent or not dealer_cards_persistent:
            return "Waiting for cards..."
        return bj.basic_strategy(player_cards_persistent, dealer_cards_persistent)
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

        # Publish outcomes if game is complete
        check_and_publish_outcomes()

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
