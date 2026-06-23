import cv2
import json
import config
from config import OUTPUT_DIR, CARD_LABELS, DECAY_LIMIT
import card_logic as bj
from preprocessing import limit_detections_per_class
from game_state import GameSession
from deck_manager import best_hand_value, registry
from deck_config import DECK_STATE_PATH

deck_registry = registry

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
PLAYER_STATS_PATH = OUTPUT_DIR / "player_stats.json"
DECK_COUNT_PATH = OUTPUT_DIR / "deck_count.json"
player_stats = {}
round_locked = False
no_detection_frames = 0
EMPTY_ROUND_RESET_FRAMES = 5


def load_deck_count() -> int:
    try:
        raw = json.loads(DECK_COUNT_PATH.read_text())
        decks = int(raw.get("decks", config.NUM_DECKS))
    except Exception:
        decks = int(getattr(config, "NUM_DECKS", 1) or 1)
    return max(1, min(decks, 12))


def save_deck_count(decks: int) -> int:
    deck_count = max(1, min(int(decks), 12))
    config.NUM_DECKS = deck_count
    try:
        DECK_COUNT_PATH.write_text(json.dumps({"decks": deck_count}, indent=2))
    except Exception as e:
        print(f"[COUNT] Failed to write deck count: {e}")
    return deck_count


def _deck_summary() -> dict:
    try:
        _refresh_player_stats()
        summary = registry.summary(num_decks=load_deck_count())
        for deck in summary.get("decks", []):
            if str(deck.get("role", "")).lower() != "dealer":
                deck["stats"] = player_stats.get(deck.get("deck_id"), {
                    "name": deck.get("name"),
                    "score": 0,
                    "wins": 0,
                    "losses": 0,
                    "pushes": 0,
                    "rounds": 0,
                    "blackjacks": 0,
                    "doubles": 0,
                    "splits": 0,
                    "history": [],
                })
        active = summary.get("active_deck") or {}
        active_id = active.get("deck_id")
        if active_id:
            active["stats"] = player_stats.get(active_id, {
                "name": active.get("name"),
                "score": 0,
                "wins": 0,
                "losses": 0,
                "pushes": 0,
                "rounds": 0,
                "blackjacks": 0,
                "doubles": 0,
                "splits": 0,
                "history": [],
            })
        summary["player_stats"] = player_stats
        return summary
    except Exception:
        return {"active_deck_id": None, "decks": [], "active_deck": None, "running_count": 0, "true_count": 0.0}


def load_player_stats() -> dict:
    if not PLAYER_STATS_PATH.exists():
        return {}
    try:
        raw = json.loads(PLAYER_STATS_PATH.read_text())
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _refresh_player_stats() -> None:
    global player_stats
    player_stats = load_player_stats()


def save_player_stats() -> None:
    try:
        PLAYER_STATS_PATH.write_text(json.dumps(player_stats, indent=2))
    except Exception as e:
        print(f"[STATS] Failed to write player stats: {e}")


def reset_player_stats() -> None:
    global player_stats, round_locked, no_detection_frames
    player_stats = {}
    round_locked = False
    no_detection_frames = 0
    save_player_stats()


def _reset_round_state() -> None:
    global round_locked
    round_locked = False
    _refresh_player_stats()
    changed = False
    for stats in player_stats.values():
        if stats.get("current_double") or stats.get("split_session") or stats.get("current_event"):
            stats["current_double"] = False
            stats["split_session"] = None
            stats["current_event"] = None
            changed = True
    if changed:
        save_player_stats()
    registry.clear()
    session.reset()


def _snapshot_deck_cards() -> dict:
    return {
        deck_id: {
            "name": state.deck.name,
            "role": state.deck.role,
            "cards": list(state.cards),
        }
        for deck_id, state in registry.states.items()
    }


def _default_player_stats(name: str) -> dict:
    return {
        "name": name,
        "score": 0,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "rounds": 0,
        "blackjacks": 0,
        "doubles": 0,
        "splits": 0,
        "current_double": False,
        "split_session": None,
        "current_event": None,
        "history": [],
    }


def _get_player_stats(deck_id: str, name: str) -> dict:
    _refresh_player_stats()
    stats = player_stats.setdefault(deck_id, _default_player_stats(name or deck_id))
    defaults = _default_player_stats(name or deck_id)
    for key, value in defaults.items():
        stats.setdefault(key, value)
    stats["name"] = name or deck_id
    return stats


def _append_score_event(deck_id: str, name: str, delta: int, event: str, result: str = "manual") -> dict:
    stats = _get_player_stats(deck_id, name)
    stats["score"] = int(stats.get("score", 0)) + int(delta)
    if result == "win":
        stats["wins"] = int(stats.get("wins", 0)) + 1
    elif result == "loss":
        stats["losses"] = int(stats.get("losses", 0)) + 1
    elif result == "push":
        stats["pushes"] = int(stats.get("pushes", 0)) + 1
    if event == "blackjack":
        stats["blackjacks"] = int(stats.get("blackjacks", 0)) + 1
    elif event == "double":
        stats["doubles"] = int(stats.get("doubles", 0)) + 1
    elif event.startswith("split"):
        stats["splits"] = int(stats.get("splits", 0)) + 1
    if result in {"win", "loss", "push"} and (not event.startswith("split") or event == "split_auto"):
        stats["rounds"] = int(stats.get("rounds", 0)) + 1

    history = list(stats.get("history", []))
    history.append({"delta": int(delta), "event": event, "result": result})
    stats["history"] = history[-50:]
    stats["current_event"] = {"delta": int(delta), "event": event, "result": result}
    save_player_stats()
    return stats


def _undo_current_event(stats: dict) -> None:
    current = stats.get("current_event")
    if not current:
        return
    history = list(stats.get("history", []))
    if history and history[-1] == current:
        history.pop()
    stats["score"] = int(stats.get("score", 0)) - int(current.get("delta", 0))
    result = current.get("result")
    event = current.get("event", "")
    if result == "win":
        stats["wins"] = max(0, int(stats.get("wins", 0)) - 1)
    elif result == "loss":
        stats["losses"] = max(0, int(stats.get("losses", 0)) - 1)
    elif result == "push":
        stats["pushes"] = max(0, int(stats.get("pushes", 0)) - 1)
    if event == "blackjack":
        stats["blackjacks"] = max(0, int(stats.get("blackjacks", 0)) - 1)
    elif event == "double":
        stats["doubles"] = max(0, int(stats.get("doubles", 0)) - 1)
    elif str(event).startswith("split"):
        stats["splits"] = max(0, int(stats.get("splits", 0)) - 1)
    if result in {"win", "loss", "push"} and (not str(event).startswith("split") or event == "split_auto"):
        stats["rounds"] = max(0, int(stats.get("rounds", 0)) - 1)
    stats["history"] = history
    stats["current_event"] = None


def _split_session_cards(session: dict) -> set:
    cards = set()
    for hand in session.get("hands", []):
        cards.update(hand.get("cards", []))
    return cards


def _update_split_session(deck_id: str, visible_cards: list[str]) -> None:
    state = registry.states.get(deck_id)
    if state is None:
        return
    stats = _get_player_stats(deck_id, state.deck.name)
    session = stats.get("split_session")
    if not session or session.get("finished"):
        return
    hands = session.get("hands", [])
    active_idx = int(session.get("active_index", 0))
    if active_idx < 0 or active_idx >= len(hands):
        return
    assigned = _split_session_cards(session)
    for card in visible_cards:
        if card not in assigned:
            hands[active_idx].setdefault("cards", []).append(card)
            assigned.add(card)
    session["hands"] = hands
    stats["split_session"] = session
    save_player_stats()


def _score_single_hand(cards: list[str], dealer_value: int, dealer_bust: bool, dealer_blackjack: bool) -> tuple[int, str]:
    player_value = best_hand_value(cards)
    player_bust = player_value > 21
    player_blackjack = _is_blackjack(cards)
    if player_blackjack and not dealer_blackjack:
        return 2, "win"
    if player_blackjack and dealer_blackjack:
        return 0, "push"
    if player_bust:
        return -1, "loss"
    if dealer_bust or player_value > dealer_value:
        return 1, "win"
    if player_value == dealer_value:
        return 0, "push"
    return -1, "loss"


def _append_split_score_event(deck_id: str, name: str, hand_results: list[dict]) -> dict:
    stats = _get_player_stats(deck_id, name)
    delta = int(sum(item.get("delta", 0) for item in hand_results))
    stats["score"] = int(stats.get("score", 0)) + delta
    stats["wins"] = int(stats.get("wins", 0)) + sum(1 for item in hand_results if item.get("result") == "win")
    stats["losses"] = int(stats.get("losses", 0)) + sum(1 for item in hand_results if item.get("result") == "loss")
    stats["pushes"] = int(stats.get("pushes", 0)) + sum(1 for item in hand_results if item.get("result") == "push")
    stats["splits"] = int(stats.get("splits", 0)) + 1
    stats["rounds"] = int(stats.get("rounds", 0)) + 1
    if delta > 0:
        result = "win"
    elif delta < 0:
        result = "loss"
    else:
        result = "push"
    event = {"delta": delta, "event": "split_auto", "result": result, "hands": hand_results}
    history = list(stats.get("history", []))
    history.append(event)
    stats["history"] = history[-50:]
    stats["current_event"] = event
    save_player_stats()
    return stats


def apply_manual_score(deck_id: str, action: str, points: int = 0) -> dict:
    state = registry.states.get(deck_id)
    if state is None or state.deck.is_dealer():
        return {"ok": False, "error": "player not found"}

    stats = _get_player_stats(deck_id, state.deck.name)

    if action == "double":
        if stats.get("current_event") or stats.get("split_session"):
            return {"ok": False, "error": "round already scored"}
        stats["current_double"] = not bool(stats.get("current_double"))
        save_player_stats()
        return {"ok": True, "stats": stats}

    if action == "start_split":
        if stats.get("current_event") or stats.get("split_session"):
            return {"ok": False, "error": "round already has a split or score"}
        cards = list(state.cards)
        if len(cards) != 2:
            return {"ok": False, "error": "split requires exactly two visible cards"}
        try:
            if bj.normalize_card(cards[0]) != bj.normalize_card(cards[1]):
                return {"ok": False, "error": "split requires a visible pair"}
        except Exception:
            return {"ok": False, "error": "split requires a visible pair"}
        stats["current_double"] = False
        stats["split_session"] = {
            "active_index": 0,
            "finished": False,
            "hands": [
                {"label": "A", "cards": [cards[0]], "stopped": False},
                {"label": "B", "cards": [cards[1]], "stopped": False},
            ],
        }
        save_player_stats()
        return {"ok": True, "stats": stats}

    if action == "next_split_hand":
        session = stats.get("split_session")
        if not session:
            return {"ok": False, "error": "no split in progress"}
        active_idx = int(session.get("active_index", 0))
        hands = session.get("hands", [])
        if 0 <= active_idx < len(hands):
            hands[active_idx]["stopped"] = True
        session["hands"] = hands
        session["active_index"] = min(active_idx + 1, len(hands) - 1)
        stats["split_session"] = session
        save_player_stats()
        return {"ok": True, "stats": stats}

    if action == "finish_split":
        session = stats.get("split_session")
        if not session:
            return {"ok": False, "error": "no split in progress"}
        active_idx = int(session.get("active_index", 0))
        hands = session.get("hands", [])
        if 0 <= active_idx < len(hands):
            hands[active_idx]["stopped"] = True
        session["hands"] = hands
        session["finished"] = True
        stats["split_session"] = session
        save_player_stats()
        return {"ok": True, "stats": stats}

    if action == "cancel_split":
        stats["split_session"] = None
        save_player_stats()
        return {"ok": True, "stats": stats}

    if action == "undo_current":
        stats = _get_player_stats(deck_id, state.deck.name)
        _undo_current_event(stats)
        save_player_stats()
        return {"ok": True, "stats": stats}

    if action == "clear_round_flags":
        stats["current_double"] = False
        stats["current_event"] = None
        stats["split_session"] = None
        save_player_stats()
        return {"ok": True, "stats": stats}

    return {"ok": False, "error": "unknown score action"}


def _is_blackjack(cards: list[str]) -> bool:
    return len(cards) == 2 and best_hand_value(cards) == 21


def _publish_round_if_dealer_terminal() -> None:
    global round_locked

    snapshot = _snapshot_deck_cards()
    if not any(item["cards"] for item in snapshot.values()):
        _reset_round_state()
        return

    if round_locked:
        return

    dealer = next(
        (item for item in snapshot.values() if str(item.get("role", "")).lower() == "dealer"),
        None,
    )
    if not dealer or not dealer.get("cards"):
        return

    dealer_value = best_hand_value(dealer["cards"])
    if dealer_value < 17:
        return

    dealer_bust = dealer_value > 21
    dealer_blackjack = _is_blackjack(dealer["cards"])

    for deck_id, item in snapshot.items():
        if str(item.get("role", "")).lower() == "dealer" or not item.get("cards"):
            continue

        stats = _get_player_stats(deck_id, item.get("name") or deck_id)
        if stats.get("current_event"):
            continue

        split_session = stats.get("split_session")
        if split_session:
            hands = split_session.get("hands", [])
            results = []
            for hand in hands:
                hand_cards = hand.get("cards", [])
                hand_delta, hand_result = _score_single_hand(hand_cards, dealer_value, dealer_bust, dealer_blackjack)
                results.append({"label": hand.get("label"), "cards": hand_cards, "delta": hand_delta, "result": hand_result})
            updated = _append_split_score_event(deck_id, item.get("name") or deck_id, results)
            updated["split_session"] = None
            updated["current_double"] = False
            save_player_stats()
            continue

        player_value = best_hand_value(item["cards"])
        player_bust = player_value > 21
        player_blackjack = _is_blackjack(item["cards"])
        is_double = bool(stats.get("current_double"))
        if player_blackjack and not dealer_blackjack:
            result = "win"
            delta = 2
            event = "blackjack"
        elif player_blackjack and dealer_blackjack:
            result = "push"
            delta = 0
            event = "auto_push"
        elif player_bust:
            result = "loss"
            delta = -2 if is_double else -1
            event = "double" if is_double else "auto_loss"
        elif dealer_bust or player_value > dealer_value:
            result = "win"
            delta = 2 if is_double else 1
            event = "double" if is_double else "auto_win"
        elif player_value == dealer_value:
            result = "push"
            delta = 0
            event = "auto_push"
        else:
            result = "loss"
            delta = -2 if is_double else -1
            event = "double" if is_double else "auto_loss"

        updated = _append_score_event(deck_id, item.get("name") or deck_id, delta, event, result)
        updated["current_double"] = False
        save_player_stats()

    round_locked = True


def _sync_active_deck_to_session() -> None:
    """Expose ROI deck state through the older session/text-file interface."""
    global player_cards_persistent, dealer_cards_persistent

    active = registry.get_active_state()
    dealer = registry.dealer_state()

    player_cards_persistent = list(active.cards) if active else []
    dealer_cards_persistent = list(dealer.cards) if dealer else []

    current_player = session.get_all_player_cards()
    current_dealer = session.get_dealer_cards()
    if set(current_player) != set(player_cards_persistent) or set(current_dealer) != set(dealer_cards_persistent):
        session.reset()
        if player_cards_persistent or dealer_cards_persistent:
            session.assign_detected_cards(player_cards_persistent, dealer_cards_persistent)


def update_deck_tracking(detections_by_deck: dict, frame_width: int, frame_height: int) -> None:
    """Update shared deck registry with per-deck detections."""
    global no_detection_frames
    try:
        registry.refresh_from_disk()
        any_raw_cards = False
        for deck_id, deck_detections in detections_by_deck.items():
            cards = []
            for det in deck_detections:
                class_id = det.get("class_id")
                if class_id is None:
                    continue
                if 0 <= int(class_id) < len(CARD_LABELS):
                    cards.append(CARD_LABELS[int(class_id)])
            if cards:
                any_raw_cards = True
            registry.update_deck_cards(deck_id, cards)
            _update_split_session(deck_id, registry.states.get(deck_id).cards if deck_id in registry.states else cards)

        if any_raw_cards:
            no_detection_frames = 0
        else:
            no_detection_frames += 1
            if no_detection_frames >= EMPTY_ROUND_RESET_FRAMES:
                _reset_round_state()

        _sync_active_deck_to_session()
        _publish_round_if_dealer_terminal()
    except Exception as e:
        print(f"[DECK] update_deck_tracking error: {e}")


def get_active_deck_state():
    return registry.get_active_state()


def set_active_deck(deck_id: str) -> bool:
    return registry.set_active_deck(deck_id)


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
        # Add player hands summary (id, status, points, type, cards)
        try:
            ph_summary = []
            for h in session.player_hands:
                try:
                    htype, hval = bj.hand_type(h.cards)
                except Exception:
                    htype, hval = None, None
                ph_summary.append({"id": h.id, "status": h.status, "points": hval, "type": htype, "cards": h.cards})
            game_stats["player_hands"] = ph_summary
        except Exception:
            game_stats["player_hands"] = []

        # Dealer hand summary (points and type)
        try:
            if session.dealer_hand:
                dtype, dval = bj.hand_type(session.dealer_hand.cards)
                game_stats["dealer_hand"] = {"points": dval, "type": dtype, "cards": session.dealer_hand.cards}
            else:
                game_stats["dealer_hand"] = None
        except Exception:
            game_stats["dealer_hand"] = None

        # Add card counting summary if available
        try:
            game_stats["counts"] = compute_counts()
        except Exception:
            game_stats["counts"] = {}
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
player_stats = load_player_stats()
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


def compute_counts(num_decks: int = None) -> dict:
    """Compute Hi-Lo running and true counts from the active deck registry."""
    if num_decks is None:
        num_decks = load_deck_count()
    summary = _deck_summary()
    return {
        "running_count": int(summary.get("running_count", 0)),
        "true_count": float(summary.get("true_count", 0.0)),
        "decks": int(num_decks if num_decks > 0 else 1),
        "active_deck_id": summary.get("active_deck_id"),
        "decks_state": summary.get("decks", []),
    }


def compute_strategy():
    """Return recommendation for the currently selected deck."""
    try:
        return registry.get_active_recommendation()
    except Exception as e:
        print(f"[STRATEGY] Error: {e}")
        return "Error"


def save_frame_and_info(frame, filename=str(OUTPUT_DIR / "latest.jpg")):
    """Save frame to file for web interface."""
    try:
        import os

        bgr_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        tmp_filename = f"{filename}.tmp.jpg"
        ok = cv2.imwrite(tmp_filename, bgr_frame)
        if ok:
            os.replace(tmp_filename, filename)

        web_filename = str(OUTPUT_DIR / "latest_web.jpg")
        max_w = max(1, int(getattr(config, "WEB_STREAM_MAX_WIDTH", 1920)))
        max_h = max(1, int(getattr(config, "WEB_STREAM_MAX_HEIGHT", 1080)))
        h, w = bgr_frame.shape[:2]
        scale = min(max_w / float(w), max_h / float(h), 1.0)
        if scale < 1.0:
            web_frame = cv2.resize(
                bgr_frame,
                (int(round(w * scale)), int(round(h * scale))),
                interpolation=cv2.INTER_AREA,
            )
        else:
            web_frame = bgr_frame

        web_tmp_filename = f"{web_filename}.tmp.jpg"
        quality = int(getattr(config, "WEB_STREAM_JPEG_QUALITY", 82))
        web_ok = cv2.imwrite(web_tmp_filename, web_frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if web_ok:
            os.replace(web_tmp_filename, web_filename)
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
        try:
            with open(DECK_STATE_PATH, "w") as jf:
                json.dump(_deck_summary(), jf, indent=2)
        except Exception as e:
            print(f"[OUTPUT] Failed to write deck_state.json: {e}")
    except Exception as e:
        print(f"[OUTPUT] Error writing text files: {e}")


def get_game_state_dict() -> dict:
    """
    Return a serializable dict representing the current game state.
    Uses the in-memory GameSession and existing helpers to avoid file I/O
    and race conditions.
    """
    try:
        deck_summary = _deck_summary()
        # Basic card lists
        player_cards = session.get_all_player_cards()
        dealer_cards = session.get_dealer_cards()

        # Active hand and dealer info
        active = session.get_active_hand()
        player_score = active.value() if active else None
        dealer_score = session.dealer_hand.value() if session.dealer_hand and len(session.dealer_hand.cards) >= 2 else None
        dealer_upcard = dealer_cards[0] if dealer_cards else None

        # Per-hand breakdown
        player_hands = []
        for h in session.player_hands:
            player_hands.append({
                "id": h.id,
                "cards": list(h.cards),
                "value": h.value(),
                "status": h.status,
            })

        # Counts and strategy
        counts = compute_counts()
        strategy = compute_strategy()

        # Winner / outcomes (if round complete)
        winner = None
        outcomes = []
        if session.phase == "complete":
            outcomes = session.compute_outcomes()
            wins = sum(1 for o in outcomes if o.get("result", "").startswith("win"))
            loses = sum(1 for o in outcomes if o.get("result") == "lose")
            pushes = sum(1 for o in outcomes if o.get("result") == "push")
            if wins > loses:
                winner = "player"
            elif loses > wins:
                winner = "dealer"
            elif pushes and not wins and not loses:
                winner = "push"

        # Round id / minimal metadata
        round_id = getattr(session, "next_hand_id", None)
        stats_snapshot = {
            "player_wins": game_stats.get("player_wins", 0),
            "dealer_wins": game_stats.get("dealer_wins", 0),
            "pushes": game_stats.get("pushes", 0),
            "blackjacks": game_stats.get("blackjacks", 0),
            "last_outcome": game_stats.get("last_outcome"),
        }

        state = {
            "player_cards": player_cards,
            "dealer_cards": dealer_cards,
            "player_hands": player_hands,
            "player_score": player_score,
            "dealer_score": dealer_score,
            "dealer_upcard": dealer_upcard,
            "phase": session.phase,
            "winner": winner,
            "outcomes": outcomes,
            "recommended_action": strategy,
            "running_count": counts.get("running_count"),
            "true_count": counts.get("true_count"),
            "counts_decks": counts.get("decks"),
            "round_id": round_id,
            "stats": stats_snapshot,
            "decks": deck_summary.get("decks", []),
            "active_deck_id": deck_summary.get("active_deck_id"),
            "active_deck": deck_summary.get("active_deck"),
            "player_stats": player_stats,
        }
        return state
    except Exception as e:
        # return minimal state on error
        return {
            "player_cards": player_cards if 'player_cards' in locals() else [],
            "dealer_cards": dealer_cards if 'dealer_cards' in locals() else [],
            "phase": getattr(session, "phase", "unknown"),
            "error": str(e),
        }


def annotate_frame(frame, detections, frame_width):
    """Draw annotations on frame."""
    h, w = frame.shape[:2]
    deck_summary = _deck_summary()
    active_deck_id = deck_summary.get("active_deck_id")
    dealer_state = registry.dealer_state()
    dealer_id = dealer_state.deck.deck_id if dealer_state else None

    for deck in deck_summary.get("decks", []):
        if not deck.get("enabled", True):
            continue
        x = int(deck.get("x", 0))
        y = int(deck.get("y", 0))
        width = int(deck.get("width", 640))
        height = int(deck.get("height", 640))
        is_active = deck.get("deck_id") == active_deck_id
        is_dealer = deck.get("deck_id") == dealer_id or str(deck.get("role", "")).lower() == "dealer"
        color = (0, 0, 255) if is_dealer else ((0, 255, 255) if is_active else (255, 180, 0))
        cv2.rectangle(frame, (x, y), (min(w - 1, x + width), min(h - 1, y + height)), color, 2)
        cv2.putText(
            frame,
            f"{deck.get('name', 'Deck')} [{deck.get('deck_id')}]",
            (max(0, x), max(20, y - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
        )

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
        color = (0, 255, 0)

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
    cv2.putText(frame, "DECKS", (20, 30), font, 0.8, (0, 255, 0), 2)

    # Compute and display Hi-Lo count (true count normalized by decks)
    counts = compute_counts()
    count_text = f"Count: {counts['true_count']:+.2f}  ({counts['decks']} deck)"
    cv2.putText(frame, count_text, (w - 380, h - 30), font, 0.8, (255, 255, 0), 2)

    return frame
