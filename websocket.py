from flask import Flask, Response, send_file, jsonify, request
import cv2
import json
import os
import re
import card_logic
import postprocessing
from deck_config import (
    DECK_STATE_PATH,
    DeckROI,
    deck_to_dict,
    find_deck,
    save_decks,
    DEFAULT_DECK_WIDTH,
    DEFAULT_DECK_HEIGHT,
    MIN_DECK_SIZE,
    MAX_DECK_SIZE,
)
from deck_manager import registry as deck_registry
import config

app = Flask(__name__)

IMAGE_PATH = os.path.join("outputs", "latest.jpg")
WEB_IMAGE_PATH = os.path.join("outputs", "latest_web.jpg")
TEXT_PATH = os.path.join("outputs", "latest.txt")
PLAYER_PATH = os.path.join("outputs", "player_cards.txt")
DEALER_PATH = os.path.join("outputs", "dealer_cards.txt")


def _sync_decks_from_disk():
    deck_registry.refresh_from_disk()
    return deck_registry.list_decks()


def _load_runtime_summary() -> dict:
    if not DECK_STATE_PATH.exists():
        return {}
    try:
        return json.loads(DECK_STATE_PATH.read_text())
    except Exception:
        return {}


def _load_player_stats() -> dict:
    path = os.path.join("outputs", "player_stats.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _empty_player_stats(name: str) -> dict:
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


def _merged_deck_summary() -> dict:
    deck_registry.refresh_from_disk()
    deck_count = postprocessing.load_deck_count()
    summary = deck_registry.summary(num_decks=deck_count)
    runtime = _load_runtime_summary()
    player_stats = _load_player_stats()
    runtime_by_id = {
        str(deck.get("deck_id")): deck
        for deck in runtime.get("decks", [])
        if isinstance(deck, dict) and deck.get("deck_id")
    }

    merged_decks = []
    for deck in summary.get("decks", []):
        runtime_deck = runtime_by_id.get(str(deck.get("deck_id")), {})
        merged = dict(deck)
        for key in ("cards", "seen_counter", "last_recommendation", "running_count", "true_count", "points", "best_value"):
            if key in runtime_deck:
                merged[key] = runtime_deck[key]
        if str(merged.get("role", "")).lower() != "dealer":
            merged["stats"] = player_stats.get(
                merged.get("deck_id"),
                _empty_player_stats(str(merged.get("name") or merged.get("deck_id") or "Player")),
            )
        merged_decks.append(merged)

    summary["decks"] = merged_decks
    summary["active_deck_id"] = deck_registry.active_deck_id
    summary["active_deck"] = next(
        (deck for deck in merged_decks if deck.get("deck_id") == deck_registry.active_deck_id),
        None,
    )
    summary["dealer"] = next(
        (deck for deck in merged_decks if str(deck.get("role", "")).lower() == "dealer"),
        None,
    )
    summary["running_count"] = runtime.get("running_count", summary.get("running_count", 0))
    summary["true_count"] = runtime.get("true_count", summary.get("true_count", 0.0))
    summary["decks"] = summary.get("decks", [])
    summary["deck_count"] = deck_count
    summary["player_stats"] = player_stats
    summary["ready_errors"] = deck_registry.ready_errors()
    return summary


def _active_runtime_deck(deck_id: str) -> dict:
    summary = _merged_deck_summary()
    for deck in summary.get("decks", []):
        if deck.get("deck_id") == deck_id:
            return deck
    return {}


def _can_double(deck: dict) -> bool:
    return len(deck.get("cards") or []) == 2


def _can_split(deck: dict) -> bool:
    cards = deck.get("cards") or []
    if len(cards) != 2:
        return False
    try:
        return card_logic.normalize_card(cards[0]) == card_logic.normalize_card(cards[1])
    except Exception:
        return False


def read_cards_from_file(path):
    if not os.path.exists(path):
        return []

    text = open(path).read().strip()
    if not text or text.lower() == "no cards":
        return []

    cards = [card.strip() for card in re.split(r"[,:;\s]+", text) if card.strip()]
    return [card for card in cards if card.lower() not in {"no", "cards"}]


@app.route("/")
def index():
        return f"""
        <html>
            <head>
                <title>Deck ROI Controller</title>
                <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
                <style>
                    :root {{
                        --bg: #0b0d12;
                        --panel: #121623;
                        --panel-2: #181d2b;
                        --text: #eef2ff;
                        --muted: #96a0bf;
                        --accent: #7dd3fc;
                        --accent-2: #f59e0b;
                        --danger: #fb7185;
                        --good: #22c55e;
                    }}
                    html, body {{ min-height: 100%; }}
                    body {{ margin: 0; background: radial-gradient(circle at top, #141926, var(--bg) 60%); color: var(--text); font-family: Inter, system-ui, sans-serif; }}
                    .app {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(360px, 440px); gap: 16px; padding: 16px; align-items: start; }}
                    .stage {{ background: rgba(10, 13, 20, 0.7); border: 1px solid rgba(255,255,255,0.08); border-radius: 18px; padding: 14px; box-shadow: 0 24px 80px rgba(0,0,0,.35); }}
                    .toolbar {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 12px; }}
                    .setup-panel {{ display: grid; grid-template-columns: 120px minmax(220px, 1fr) auto; gap: 8px; margin-bottom: 12px; }}
                    button {{ border: 0; border-radius: 10px; padding: 10px 12px; background: var(--panel-2); color: var(--text); cursor: pointer; }}
                    button.primary {{ background: linear-gradient(135deg, #2563eb, #7c3aed); }}
                    button.active {{ outline: 2px solid var(--accent); }}
                    .hint {{ color: var(--muted); font-size: 13px; }}
                    .frame-wrap {{ position: relative; width: 100%; max-width: 100%; aspect-ratio: {config.FRAME_WIDTH} / {config.FRAME_HEIGHT}; overflow: hidden; border-radius: 14px; background: #05070c; }}
                    #frame {{ width: 100%; height: 100%; object-fit: contain; display: block; }}
                    #overlay {{ position: absolute; inset: 0; pointer-events: auto; touch-action: none; }}
                    .deck-box {{ position: absolute; border: 2px solid var(--accent-2); border-radius: 12px; background: rgba(245,158,11,0.10); box-sizing: border-box; cursor: move; user-select: none; touch-action: none; }}
                    .deck-box.active {{ border-color: var(--good); border-width: 4px; background: rgba(34,197,94,0.16); box-shadow: 0 0 0 3px rgba(34,197,94,0.24), 0 0 28px rgba(34,197,94,0.35); }}
                    .result-pulse.outcome-win {{ --result-rgb: 34, 197, 94; --result-color: #4ade80; }}
                    .result-pulse.outcome-loss {{ --result-rgb: 244, 63, 94; --result-color: #fb7185; }}
                    .result-pulse.outcome-push {{ --result-rgb: 250, 204, 21; --result-color: #fde047; }}
                    .deck-box.result-pulse {{ border-color: var(--result-color) !important; border-width: 4px; background: rgba(var(--result-rgb), .18) !important; animation: resultBoxPulse .86s ease-in-out infinite; }}
                    .deck-box.result-pulse .deck-label {{ color: var(--result-color); border-color: rgba(var(--result-rgb), .56); }}
                    .deck-label {{ position: absolute; left: 8px; top: -12px; background: var(--panel); border: 1px solid rgba(255,255,255,0.08); padding: 3px 8px; border-radius: 999px; font-size: 12px; }}
                    .resize-handle {{ position: absolute; right: -5px; bottom: -5px; width: 12px; height: 12px; border-radius: 4px; background: rgba(238,242,255,0.72); border: 1px solid var(--panel); box-shadow: 0 1px 6px rgba(0,0,0,.28); cursor: nwse-resize; touch-action: none; }}
                    .sidebar {{ display: grid; gap: 12px; }}
                    .card {{ background: rgba(18,22,35,.9); border: 1px solid rgba(255,255,255,.07); border-radius: 16px; padding: 14px; }}
                    .selected-position-panel {{ min-width: 0; }}
                    .selected-position-head {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }}
                    .selected-position-title {{ font-size: 17px; font-weight: 800; }}
                    .selected-position-hint {{ flex: none; padding: 4px 8px; border-radius: 999px; background: rgba(125,211,252,.09); color: var(--muted); font-size: 10px; }}
                    .deck-list {{ min-width: 0; display: grid; overflow-anchor: none; }}
                    .selected-deck-card {{ min-width: 0; overflow: hidden; border: 1px solid rgba(255,255,255,.075); border-radius: 14px; background: rgba(255,255,255,.035); }}
                    .selected-deck-card.player {{ --role-rgb: 96, 165, 250; }}
                    .selected-deck-card.dealer {{ --role-rgb: 251, 113, 133; }}
                    .selected-deck-card.result-pulse {{ border-color: var(--result-color); animation: resultItemPulse .86s ease-in-out infinite; }}
                    .selected-deck-head {{ display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 10px; padding: 11px; background: linear-gradient(135deg, rgba(var(--role-rgb), .17), rgba(124,58,237,.06)); }}
                    .selected-deck-avatar {{ display: grid; place-items: center; width: 34px; height: 34px; border: 1px solid rgba(var(--role-rgb), .38); border-radius: 11px; background: rgba(var(--role-rgb), .14); color: rgb(var(--role-rgb)); font-size: 14px; font-weight: 900; }}
                    .selected-deck-identity {{ min-width: 0; }}
                    .selected-deck-role {{ margin-bottom: 2px; color: rgb(var(--role-rgb)); font-size: 9px; font-weight: 800; letter-spacing: .09em; text-transform: uppercase; }}
                    .selected-deck-name {{ overflow: hidden; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }}
                    .selected-points-pill {{ flex: none; padding: 5px 9px; border-radius: 999px; background: rgba(148,163,184,.14); color: #e2e8f0; font-size: 12px; font-weight: 900; font-variant-numeric: tabular-nums; white-space: nowrap; }}
                    .selected-cards {{ padding: 10px 11px; border-top: 1px solid rgba(255,255,255,.045); border-bottom: 1px solid rgba(255,255,255,.045); }}
                    .selected-card-row {{ display: flex; min-height: 29px; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 6px; }}
                    .playing-card-chip {{ display: inline-flex; min-width: 25px; justify-content: center; padding: 5px 7px; border: 1px solid rgba(226,232,240,.16); border-radius: 8px; background: rgba(248,250,252,.92); color: #111827; font-size: 12px; font-weight: 900; box-shadow: 0 3px 9px rgba(0,0,0,.18); }}
                    .playing-card-chip.red {{ color: #dc2626; }}
                    .selected-no-cards {{ color: var(--muted); font-size: 12px; }}
                    .selected-status {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 11px 10px; }}
                    .selected-status-value {{ min-width: 0; overflow: hidden; color: #e2e8f0; font-size: 12px; font-weight: 800; text-align: right; text-overflow: ellipsis; white-space: nowrap; }}
                    .selected-deck-card.result-pulse .selected-status-value {{ color: var(--result-color); }}
                    .small {{ font-size: 12px; color: var(--muted); }}
                    .value {{ font-variant-numeric: tabular-nums; }}
                    .rec {{ font-size: 28px; font-weight: 800; line-height: 1.1; margin-top: 6px; }}
                    .rec.outcome-win {{ color: #4ade80; text-shadow: 0 0 22px rgba(34,197,94,.34); }}
                    .rec.outcome-loss {{ color: #fb7185; text-shadow: 0 0 22px rgba(244,63,94,.34); }}
                    .rec.outcome-push {{ color: #fde047; text-shadow: 0 0 22px rgba(250,204,21,.30); }}
                    .rec-top {{ display: grid; grid-template-columns: minmax(0, 1fr) 132px; gap: 10px; align-items: start; }}
                    .count-card {{ background: rgba(255,255,255,.04); border-radius: 12px; padding: 10px; }}
                    .count-value {{ font-size: 26px; font-weight: 800; }}
                    .count-meaning {{ margin-top: 4px; }}
                    .deck-count-row {{ display: grid; grid-template-columns: 86px auto minmax(150px, auto); gap: 8px; align-items: stretch; }}
                    #deckCountInput {{ max-width: 120px; }}
                    .reset-hold {{ --hold-progress: 0%; position: relative; isolation: isolate; overflow: hidden; min-width: 150px; background: linear-gradient(135deg, #c2410c, #be123c); color: white; touch-action: none; user-select: none; }}
                    .reset-hold::before {{ content: ''; position: absolute; z-index: -1; inset: 0 auto 0 0; width: var(--hold-progress); background: linear-gradient(90deg, #f97316, #ef4444); transition: width .08s linear; }}
                    .reset-hold.holding {{ box-shadow: 0 0 0 2px rgba(251,146,60,.45), 0 0 24px rgba(239,68,68,.28); }}
                    .reset-hold:disabled {{ cursor: wait; opacity: .82; }}
                    .score-actions {{ display: grid; gap: 8px; margin-top: 12px; }}
                    .score-actions-row {{ display: grid; gap: 8px; }}
                    .score-actions-row.split-row {{ grid-template-columns: repeat(3, 1fr); }}
                    .score-actions-row.play-row {{ grid-template-columns: repeat(2, 1fr); }}
                    .score-actions button {{ padding: 9px 8px; font-size: 12px; }}
                    .score-actions .danger {{ background: rgba(251,113,133,0.24); }}
                    .score-actions .good {{ background: rgba(34,197,94,0.22); }}
                    .score-actions button.selected {{ outline: 2px solid var(--accent); }}
                    .score-actions button.recommended {{ background: rgba(125,211,252,0.20); box-shadow: 0 0 0 1px rgba(125,211,252,0.34), 0 0 14px rgba(125,211,252,0.18); }}
                    .split-hands {{ display: none; gap: 8px; margin-top: 10px; }}
                    .split-hand {{ background: rgba(255,255,255,.04); border-radius: 10px; padding: 8px; font-size: 12px; }}
                    .split-hand.active {{ outline: 2px solid var(--good); }}
                    input {{ width: 100%; box-sizing: border-box; border-radius: 10px; border: 1px solid rgba(255,255,255,.08); background: rgba(255,255,255,.04); color: var(--text); padding: 10px; }}
                    #playerCount {{ max-width: 120px; }}
                    .row {{ display: flex; gap: 8px; }}
                    .row > * {{ flex: 1; }}
                    .error {{ color: var(--danger); font-weight: 700; margin-bottom: 10px; }}
                    .dealer-box {{ border-color: var(--danger) !important; background: rgba(251,113,133,0.12) !important; }}
                    .stats-panel {{ min-width: 0; }}
                    .stats-panel-head {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }}
                    .stats-title {{ font-size: 17px; font-weight: 800; }}
                    .stats-scroll {{ min-width: 0; max-height: min(52vh, 560px); overflow: auto; padding-right: 3px; overscroll-behavior: contain; overflow-anchor: none; scrollbar-color: rgba(125,211,252,.35) transparent; }}
                    .stats-summary {{ display: grid; width: 100%; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 7px; margin-bottom: 10px; box-sizing: border-box; }}
                    .summary-stat {{ min-width: 0; overflow: hidden; padding: 9px; border: 1px solid rgba(255,255,255,.06); border-radius: 11px; background: linear-gradient(145deg, rgba(125,211,252,.08), rgba(255,255,255,.025)); box-sizing: border-box; }}
                    .summary-stat .num {{ min-width: 0; margin-top: 2px; overflow-wrap: anywhere; font-size: 19px; font-weight: 800; font-variant-numeric: tabular-nums; }}
                    .player-stat-list {{ display: grid; gap: 10px; }}
                    .player-stat-card {{ min-width: 0; overflow: hidden; border: 1px solid rgba(255,255,255,.075); border-radius: 14px; background: rgba(255,255,255,.035); }}
                    .player-stat-head {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 11px; background: linear-gradient(135deg, rgba(37,99,235,.12), rgba(124,58,237,.08)); }}
                    .player-stat-name {{ min-width: 0; font-weight: 800; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
                    .score-pill {{ flex: none; padding: 4px 9px; border-radius: 999px; background: rgba(148,163,184,.14); font-weight: 900; font-variant-numeric: tabular-nums; }}
                    .score-pill.positive, .history-delta.positive {{ color: #4ade80; }}
                    .score-pill.negative, .history-delta.negative {{ color: #fb7185; }}
                    .score-pill.neutral, .history-delta.neutral {{ color: #fde047; }}
                    .player-stat-metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; border-top: 1px solid rgba(255,255,255,.05); border-bottom: 1px solid rgba(255,255,255,.05); background: rgba(255,255,255,.045); }}
                    .player-metric {{ padding: 8px 5px; text-align: center; }}
                    .player-metric strong {{ display: block; font-size: 16px; font-variant-numeric: tabular-nums; }}
                    .history-wrap {{ max-height: 210px; overflow: auto; }}
                    .history-table {{ width: 100%; border-collapse: collapse; font-size: 11px; font-variant-numeric: tabular-nums; }}
                    .history-table th {{ position: sticky; top: 0; z-index: 1; padding: 7px 6px; background: #1a1f2d; color: var(--muted); text-align: left; font-weight: 600; }}
                    .history-table td {{ padding: 7px 6px; border-top: 1px solid rgba(255,255,255,.045); }}
                    .history-table th:nth-last-child(-n+2), .history-table td:nth-last-child(-n+2) {{ text-align: right; }}
                    .result-badge {{ display: inline-flex; min-width: 44px; justify-content: center; border-radius: 999px; padding: 3px 6px; font-size: 10px; font-weight: 900; letter-spacing: .03em; }}
                    .result-badge.win {{ color: #86efac; background: rgba(34,197,94,.15); }}
                    .result-badge.loss {{ color: #fda4af; background: rgba(244,63,94,.15); }}
                    .result-badge.push {{ color: #fde047; background: rgba(250,204,21,.14); }}
                    .stats-empty, .history-empty {{ padding: 18px 10px; color: var(--muted); text-align: center; }}
                    .history-empty {{ padding: 13px 8px; font-size: 12px; }}
                    .reset-status {{ min-height: 16px; margin-top: 7px; color: var(--muted); font-size: 11px; }}
                    #playerStatsPanel:fullscreen {{ box-sizing: border-box; width: 100vw; height: 100vh; max-width: none; margin: 0; padding: clamp(16px, 2.4vw, 34px); border: 0; border-radius: 0; background: radial-gradient(circle at top, #182034, #0b0d12 62%); display: flex; flex-direction: column; }}
                    #playerStatsPanel:fullscreen .stats-panel-head {{ margin-bottom: 18px; }}
                    #playerStatsPanel:fullscreen .stats-title {{ font-size: clamp(22px, 2.4vw, 34px); }}
                    #playerStatsPanel:fullscreen .stats-scroll {{ flex: 1; max-height: none; }}
                    #playerStatsPanel:fullscreen .stats-summary {{ grid-template-columns: repeat(3, minmax(0, 240px)); }}
                    #playerStatsPanel:fullscreen .player-stat-list {{ grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); align-items: start; }}
                    #playerStatsPanel:fullscreen .history-wrap {{ max-height: min(52vh, 520px); }}
                    .crop-modal {{ position: fixed; inset: 0; z-index: 30; display: none; align-items: center; justify-content: center; padding: 18px; background: rgba(3,7,18,0.78); backdrop-filter: blur(8px); }}
                    .crop-modal.open {{ display: flex; }}
                    .crop-panel {{ width: min(92vw, 760px); background: rgba(18,22,35,0.98); border: 1px solid rgba(255,255,255,.10); border-radius: 14px; padding: 12px; box-shadow: 0 28px 90px rgba(0,0,0,.48); }}
                    .crop-head {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }}
                    .crop-title {{ font-weight: 800; }}
                    .crop-image-wrap {{ aspect-ratio: 1 / 1; background: #05070c; border-radius: 10px; overflow: hidden; }}
                    #cropPreviewImg {{ width: 100%; height: 100%; object-fit: contain; display: block; }}
                    #overlay, .deck-box, .selected-deck-card, .crop-modal, .crop-panel, #cropPreviewImg {{ -webkit-touch-callout: none; -webkit-user-select: none; user-select: none; }}
                    html:fullscreen body {{ min-height: 100vh; background: var(--bg); }}
                    html:fullscreen .app {{ min-height: 100vh; box-sizing: border-box; }}
                    @keyframes resultBoxPulse {{
                        0%, 100% {{ box-shadow: 0 0 0 2px rgba(var(--result-rgb), .25), 0 0 14px rgba(var(--result-rgb), .25); filter: saturate(.9); }}
                        50% {{ box-shadow: 0 0 0 5px rgba(var(--result-rgb), .50), 0 0 34px rgba(var(--result-rgb), .72); filter: saturate(1.45); }}
                    }}
                    @keyframes resultItemPulse {{
                        0%, 100% {{ box-shadow: inset 0 0 0 0 rgba(var(--result-rgb), .08), 0 0 8px rgba(var(--result-rgb), .12); }}
                        50% {{ box-shadow: inset 0 0 24px rgba(var(--result-rgb), .22), 0 0 20px rgba(var(--result-rgb), .42); }}
                    }}
                    @media (max-width: 800px) {{
                        html, body {{ width: 100%; max-width: 100%; overflow-x: hidden; }}
                        body {{ overflow-y: auto; }}
                        .app {{ display: block; width: 100%; max-width: 100%; min-height: 100dvh; box-sizing: border-box; padding: 6px; overflow: hidden; }}
                        .stage {{ padding: 6px; border-radius: 12px; margin-bottom: 6px; }}
                        .setup-panel {{ grid-template-columns: 72px minmax(0, 1fr); gap: 6px; margin-bottom: 8px; }}
                        .setup-panel button {{ grid-column: 1 / -1; }}
                        .toolbar {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; margin-bottom: 8px; }}
                        .toolbar > button {{ min-width: 0; padding: 9px 5px; }}
                        .deck-count-row {{ grid-column: 1 / -1; width: 100%; min-width: 0; grid-template-columns: 72px minmax(0, .8fr) minmax(0, 1.35fr); }}
                        .deck-count-row button {{ min-width: 0; padding-inline: 5px; font-size: 11px; }}
                        .reset-hold {{ min-width: 0; }}
                        .hint {{ display: none; }}
                        .frame-wrap {{ aspect-ratio: {config.FRAME_WIDTH} / {config.FRAME_HEIGHT}; height: auto; border-radius: 10px; }}
                        .sidebar {{ display: grid; min-width: 0; gap: 6px; overflow: visible; }}
                        .card {{ min-width: 0; padding: 8px; border-radius: 12px; overflow: hidden; }}
                        .rec-top {{ grid-template-columns: minmax(0, 1fr) 92px; gap: 6px; }}
                        .rec-top > * {{ min-width: 0; }}
                        .count-card {{ padding: 8px; }}
                        .count-meaning {{ margin-top: 2px; font-size: 9px; line-height: 1.1; }}
                        .rec {{ font-size: 20px; }}
                        .count-value {{ font-size: 20px; }}
                        .deck-box {{ border-width: 1px; border-radius: 6px; }}
                        .deck-box.active {{ border-width: 2px; box-shadow: 0 0 0 1px rgba(34,197,94,0.22), 0 0 14px rgba(34,197,94,0.24); }}
                        .deck-label {{ left: 3px; top: -11px; max-width: 90%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 1px 4px; font-size: 8px; line-height: 1; }}
                        .resize-handle {{ right: -4px; bottom: -4px; width: 10px; height: 10px; border-radius: 3px; }}
                        .score-actions {{ gap: 5px; margin-top: 6px; }}
                        .score-actions-row {{ gap: 5px; }}
                        .score-actions button {{ min-width: 0; padding: 7px 3px; overflow: hidden; text-overflow: ellipsis; font-size: 10px; }}
                        .split-hands {{ margin-top: 6px; }}
                        .selected-position-head {{ margin-bottom: 8px; }}
                        .selected-deck-head {{ gap: 8px; padding: 9px; }}
                        .selected-deck-avatar {{ width: 31px; height: 31px; }}
                        .selected-cards {{ padding: 9px; }}
                        .selected-status {{ padding: 8px 9px 9px; }}
                        .stats-scroll {{ max-height: 46vh; }}
                        .stats-summary {{ gap: 5px; }}
                        .summary-stat {{ padding: 7px; }}
                        .player-stat-head {{ padding: 9px; }}
                        .history-wrap {{ overflow-x: auto; }}
                        .history-table {{ min-width: 340px; font-size: 10px; }}
                        .history-table th, .history-table td {{ padding: 6px 4px; }}
                        #playerStatsPanel:fullscreen {{ padding: 10px; }}
                        #playerStatsPanel:fullscreen .stats-summary {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
                        #playerStatsPanel:fullscreen .player-stat-list {{ grid-template-columns: 1fr; }}
                        .crop-modal {{ padding: 8px; align-items: start; }}
                        .crop-panel {{ width: 100%; margin-top: 8px; padding: 8px; border-radius: 12px; }}
                        .crop-head {{ margin-bottom: 8px; }}
                    }}
                    @media (prefers-reduced-motion: reduce) {{
                        .deck-box.result-pulse, .selected-deck-card.result-pulse {{ animation-duration: 1.8s; }}
                    }}
                </style>
            </head>
            <body>
                <div class="app">
                    <div class="stage">
                        <div class="setup-panel">
                            <input id="playerCount" type="number" min="1" max="12" value="1" title="Number of player boxes">
                            <input id="playerNames" type="text" placeholder="Player names: Alice, Bob, Chris">
                            <button class="primary" onclick="setupPlayerBoxes()">Create player boxes</button>
                        </div>
                        <div class="toolbar">
                            <button class="primary" onclick="startAddDeck()">Add player</button>
                            <button class="primary" onclick="startAddDealer()">Add dealer</button>
                            <button onclick="toggleFullscreen()">Fullscreen</button>
                            <div class="deck-count-row">
                                <input id="deckCountInput" type="number" min="1" max="12" value="{postprocessing.load_deck_count()}" title="Decks in shoe">
                                <button onclick="saveDeckCount()">Set decks</button>
                                <button id="resetStatsButton" class="reset-hold" type="button" aria-label="Hold for five seconds to reset all scores">
                                    <span id="resetStatsLabel">Hold 5s · reset</span>
                                </button>
                            </div>
                        </div>
                        <div id="errorBanner" class="error" style="display:none;"></div>
                        <div class="hint">Drag square boxes inside the full video. Pull the corner to resize from 400-1000 px. Click a player box to show its recommendation.</div>
                        <div class="frame-wrap" id="frameWrap">
                            <img id="frame" src="/image">
                            <div id="overlay"></div>
                        </div>
                    </div>

                    <div class="sidebar">
                        <div class="card">
                            <div class="rec-top">
                                <div>
                                    <div class="small">Recommendation</div>
                                    <div id="recbox" class="rec">Loading...</div>
                                </div>
                                <div class="count-card">
                                    <div class="small">Count</div>
                                    <div class="count-value value" id="trueCount">0.00</div>
                                    <div class="small count-meaning" id="countMeaning">Count neutral</div>
                                </div>
                            </div>
                            <div class="score-actions">
                                <div class="score-actions-row split-row">
                                    <button id="splitBtn" onclick="scoreAction('start_split')">Start Split</button>
                                    <button id="cancelSplitBtn" onclick="scoreAction('cancel_split')">Cancel Split</button>
                                    <button id="finishSplitBtn" onclick="scoreAction('finish_split')">Finish Split</button>
                                </div>
                                <div class="score-actions-row play-row">
                                    <button id="doubleBtn" onclick="scoreAction('double')">Mark Double</button>
                                    <button id="nextSplitBtn" onclick="scoreAction('next_split_hand')">Next Hand</button>
                                </div>
                            </div>
                            <div id="splitHands" class="split-hands"></div>
                        </div>
                        <div class="card selected-position-panel">
                            <div class="selected-position-head">
                                <div>
                                    <div class="small">Selected position</div>
                                    <div class="selected-position-title">Player / Dealer</div>
                                </div>
                                <div class="selected-position-hint">Select on camera</div>
                            </div>
                            <div id="deckList" class="deck-list"></div>
                        </div>
                        <section id="playerStatsPanel" class="card stats-panel">
                            <div class="stats-panel-head">
                                <div>
                                    <div class="small">Table overview</div>
                                    <div class="stats-title">Player Statistics</div>
                                </div>
                                <button id="statsFullscreenBtn" type="button" onclick="toggleStatsFullscreen()">Fullscreen</button>
                            </div>
                            <div id="playerStatsContent" class="stats-scroll">
                                <div class="stats-empty">No player statistics yet.</div>
                            </div>
                            <div id="resetStatus" class="reset-status" role="status" aria-live="polite"></div>
                        </section>
                    </div>
                </div>

                <div id="cropModal" class="crop-modal">
                    <div class="crop-panel">
                        <div class="crop-head">
                            <div>
                                <div id="cropPreviewTitle" class="crop-title">ROI Preview</div>
                                <div class="small">Detection view · 640x640</div>
                            </div>
                            <button onclick="closeCropPreview()">Close</button>
                        </div>
                        <div class="crop-image-wrap">
                            <img id="cropPreviewImg" alt="Selected ROI crop">
                        </div>
                    </div>
                </div>

                <script>
                    const SOURCE_WIDTH = {config.FRAME_WIDTH};
                    const SOURCE_HEIGHT = {config.FRAME_HEIGHT};
                    const DEFAULT_DECK_WIDTH = {DEFAULT_DECK_WIDTH};
                    const DEFAULT_DECK_HEIGHT = {DEFAULT_DECK_HEIGHT};
                    const MIN_DECK_SIZE = {MIN_DECK_SIZE};
                    const MAX_DECK_SIZE = {MAX_DECK_SIZE};

                    let decks = [];
                    let activeDeckId = null;
                    let selectedDeckId = null;
                    let addMode = false;
                    let dragState = null;
                    let isDragging = false;
                    let isSavingRoi = false;
                    let suppressNextDeckClick = false;
                    let cropPreviewDeckId = null;
                    let cropPreviewTimer = null;
                    let longPressPreviewOpened = false;
                    let latestPrediction = 'Loading...';
                    let activeOutcome = null;
                    let statsRenderSignature = '';
                    let resetHoldTimer = null;
                    let resetHoldFrame = null;
                    let resetHoldStartedAt = 0;
                    let deckRenderSignature = '';
                    let deckRenderPending = false;
                    let pendingStatsDeckData = null;
                    let userScrollActive = false;
                    let scrollIdleTimer = null;
                    const RESET_HOLD_MS = 5000;

                    function clamp(value, min, max) {{
                        return Math.max(min, Math.min(max, value));
                    }}

                    function getOverlayMetrics() {{
                        const overlay = document.getElementById('overlay');
                        const rect = overlay.getBoundingClientRect();
                        return {{ rect, scaleX: rect.width / SOURCE_WIDTH, scaleY: rect.height / SOURCE_HEIGHT }};
                    }}

                    function toScreen(deck) {{
                        const {{ scaleX, scaleY }} = getOverlayMetrics();
                        return {{
                            left: deck.x * scaleX,
                            top: deck.y * scaleY,
                            width: deck.width * scaleX,
                            height: deck.height * scaleY,
                        }};
                    }}

                    function toSource(clientX, clientY) {{
                        const {{ rect, scaleX, scaleY }} = getOverlayMetrics();
                        return {{
                            x: clamp(Math.round((clientX - rect.left) / scaleX), 0, SOURCE_WIDTH - DEFAULT_DECK_WIDTH),
                            y: clamp(Math.round((clientY - rect.top) / scaleY), 0, SOURCE_HEIGHT - DEFAULT_DECK_HEIGHT),
                        }};
                    }}

                    function clampDeckSize(deck, size) {{
                        const maxByFrame = Math.max(1, Math.min(MAX_DECK_SIZE, SOURCE_WIDTH - deck.x, SOURCE_HEIGHT - deck.y));
                        const minByFrame = Math.min(MIN_DECK_SIZE, maxByFrame);
                        return clamp(Math.round(size), minByFrame, maxByFrame);
                    }}

                    function clampDeckSizeForFrame(size) {{
                        const maxByFrame = Math.max(1, Math.min(MAX_DECK_SIZE, SOURCE_WIDTH, SOURCE_HEIGHT));
                        const minByFrame = Math.min(MIN_DECK_SIZE, maxByFrame);
                        return clamp(Math.round(size), minByFrame, maxByFrame);
                    }}

                    function makeSquare(deck) {{
                        const size = clampDeckSizeForFrame(Math.max(deck.width || DEFAULT_DECK_WIDTH, deck.height || DEFAULT_DECK_HEIGHT));
                        deck.width = size;
                        deck.height = size;
                        deck.x = clamp(Math.round(deck.x || 0), 0, SOURCE_WIDTH - size);
                        deck.y = clamp(Math.round(deck.y || 0), 0, SOURCE_HEIGHT - size);
                        return deck;
                    }}

                    function suppressDeckClickBriefly() {{
                        suppressNextDeckClick = true;
                        window.setTimeout(() => {{
                            suppressNextDeckClick = false;
                        }}, 350);
                    }}

                    function isMobileView() {{
                        return window.matchMedia('(max-width: 800px)').matches;
                    }}

                    function deckDisplayName(deck) {{
                        if (!deck) return 'ROI Preview';
                        return deck.role === 'dealer' ? 'Dealer' : deck.name;
                    }}

                    function playingCardDisplay(card) {{
                        const raw = String(card || '');
                        const suitCode = raw.slice(-1).toLowerCase();
                        const suits = {{ c: '♣', d: '♦', h: '♥', s: '♠' }};
                        if (!suits[suitCode]) return {{ text: raw, red: false }};
                        return {{
                            text: `${{raw.slice(0, -1)}}${{suits[suitCode]}}`,
                            red: suitCode === 'd' || suitCode === 'h',
                        }};
                    }}

                    function roundOutcome(deck) {{
                        const event = deck && deck.stats ? deck.stats.current_event : null;
                        const result = event ? event.result : null;
                        if (result === 'win') return {{ key: 'win', label: 'Win', className: 'outcome-win', event }};
                        if (result === 'loss') return {{ key: 'loss', label: 'Busted', className: 'outcome-loss', event }};
                        if (result === 'push') return {{ key: 'push', label: 'Push', className: 'outcome-push', event }};
                        return null;
                    }}

                    function renderActiveRecommendation() {{
                        const recbox = document.getElementById('recbox');
                        recbox.classList.remove('outcome-win', 'outcome-loss', 'outcome-push');
                        if (activeOutcome) {{
                            recbox.innerText = activeOutcome.label;
                            recbox.classList.add(activeOutcome.className);
                            return;
                        }}
                        recbox.innerText = latestPrediction || 'No prediction';
                    }}

                    function deckUiSignature(deckData = decks) {{
                        return JSON.stringify({{
                            activeDeckId,
                            selectedDeckId,
                            decks: (deckData || []).map(deck => ({{
                                deckId: deck.deck_id,
                                name: deck.name,
                                role: deck.role,
                                enabled: deck.enabled,
                                x: deck.x,
                                y: deck.y,
                                width: deck.width,
                                height: deck.height,
                                cards: deck.cards || [],
                                points: deck.points,
                                recommendation: deck.last_recommendation,
                                result: deck.stats && deck.stats.current_event ? deck.stats.current_event.result : null,
                            }})),
                        }});
                    }}

                    function pageScrollTop() {{
                        const scrollingElement = document.scrollingElement || document.documentElement;
                        return scrollingElement ? scrollingElement.scrollTop : window.scrollY;
                    }}

                    function restorePageScroll(scrollTop) {{
                        const apply = () => {{
                            const scrollingElement = document.scrollingElement || document.documentElement;
                            if (scrollingElement) scrollingElement.scrollTop = scrollTop;
                        }};
                        apply();
                        window.requestAnimationFrame(apply);
                    }}

                    function markScrollActivity() {{
                        userScrollActive = true;
                        if (scrollIdleTimer) window.clearTimeout(scrollIdleTimer);
                        scrollIdleTimer = window.setTimeout(() => {{
                            userScrollActive = false;
                            scrollIdleTimer = null;
                            if (deckRenderPending) {{
                                deckRenderPending = false;
                                renderDecks();
                            }}
                            if (pendingStatsDeckData) {{
                                const pendingData = pendingStatsDeckData;
                                pendingStatsDeckData = null;
                                renderPlayerStatistics(pendingData);
                            }}
                        }}, 240);
                    }}

                    function openCropPreview(deckId) {{
                        const deck = decks.find(d => d.deck_id === deckId);
                        cropPreviewDeckId = deckId;
                        document.getElementById('cropPreviewTitle').innerText = deckDisplayName(deck);
                        document.getElementById('cropModal').classList.add('open');
                        loadCropPreviewFrame();
                    }}

                    function closeCropPreview() {{
                        cropPreviewDeckId = null;
                        if (cropPreviewTimer) {{
                            window.clearTimeout(cropPreviewTimer);
                            cropPreviewTimer = null;
                        }}
                        document.getElementById('cropModal').classList.remove('open');
                        document.getElementById('cropPreviewImg').removeAttribute('src');
                    }}

                    function loadCropPreviewFrame() {{
                        if (!cropPreviewDeckId) return;
                        const next = new Image();
                        next.onload = () => {{
                            if (!cropPreviewDeckId) return;
                            document.getElementById('cropPreviewImg').src = next.src;
                            cropPreviewTimer = window.setTimeout(loadCropPreviewFrame, 160);
                        }};
                        next.onerror = () => {{
                            cropPreviewTimer = window.setTimeout(loadCropPreviewFrame, 500);
                        }};
                        next.src = `/deck-crop/${{encodeURIComponent(cropPreviewDeckId)}}?ts=${{Date.now()}}`;
                    }}

                    function openCropPreviewOnDesktop(evt, deckId) {{
                        if (isMobileView()) return;
                        evt.preventDefault();
                        evt.stopPropagation();
                        openCropPreview(deckId);
                    }}

                    function beginCropLongPress(evt, deckId) {{
                        if (!isMobileView()) return null;
                        const state = {{
                            startX: evt.clientX,
                            startY: evt.clientY,
                            timer: null,
                            opened: false,
                        }};
                        state.timer = window.setTimeout(() => {{
                            state.opened = true;
                            longPressPreviewOpened = true;
                            suppressDeckClickBriefly();
                            openCropPreview(deckId);
                        }}, 650);
                        return state;
                    }}

                    function cancelCropLongPress(state) {{
                        if (state && state.timer) {{
                            window.clearTimeout(state.timer);
                            state.timer = null;
                        }}
                    }}

                    function updateCropLongPress(state, evt) {{
                        if (!state) return;
                        if (Math.abs(evt.clientX - state.startX) > 8 || Math.abs(evt.clientY - state.startY) > 8) {{
                            cancelCropLongPress(state);
                        }}
                    }}

                    function attachListPreviewTriggers(element, deckId) {{
                        element.addEventListener('dblclick', (evt) => openCropPreviewOnDesktop(evt, deckId));
                        element.addEventListener('pointerdown', (evt) => {{
                            const state = beginCropLongPress(evt, deckId);
                            if (!state) return;
                            const onMove = (moveEvt) => updateCropLongPress(state, moveEvt);
                            const onUp = () => {{
                                cancelCropLongPress(state);
                                if (state.opened) {{
                                    longPressPreviewOpened = false;
                                }}
                                document.removeEventListener('pointermove', onMove);
                                document.removeEventListener('pointerup', onUp);
                                document.removeEventListener('pointercancel', onUp);
                            }};
                            document.addEventListener('pointermove', onMove);
                            document.addEventListener('pointerup', onUp);
                            document.addEventListener('pointercancel', onUp);
                        }});
                    }}

                    async function reloadDecks(force = false) {{
                        if (!force && (isDragging || isSavingRoi)) return;
                        const resp = await fetch('/decks');
                        if (!resp.ok) return;
                        const data = await resp.json();
                        if (!Array.isArray(data.decks)) return;
                        decks = data.decks || [];
                        decks.forEach(makeSquare);
                        activeDeckId = data.active_deck_id || null;
                        if (!selectedDeckId || !decks.some(deck => deck.deck_id === selectedDeckId)) {{
                            selectedDeckId = activeDeckId || (decks[0] && decks[0].deck_id) || null;
                        }}
                        activeOutcome = roundOutcome(decks.find(deck => deck.deck_id === activeDeckId));
                        const nextSignature = deckUiSignature();
                        if (nextSignature !== deckRenderSignature) {{
                            if (!force && userScrollActive) {{
                                deckRenderPending = true;
                            }} else {{
                                renderDecks();
                            }}
                        }}
                        renderActiveRecommendation();
                        updateErrorBanner(data.ready_errors || []);
                    }}

                    function updateErrorBanner(errors) {{
                        const banner = document.getElementById('errorBanner');
                        if (!errors || !errors.length) {{
                            banner.style.display = 'none';
                            banner.innerText = '';
                            return;
                        }}
                        banner.style.display = 'block';
                        banner.innerText = errors.join(' · ');
                    }}

                    function renderDecks() {{
                        const overlay = document.getElementById('overlay');
                        const list = document.getElementById('deckList');
                        const previousScrollTop = list.scrollTop;
                        const previousPageScrollTop = pageScrollTop();
                        overlay.innerHTML = '';
                        list.innerHTML = '';

                        decks.forEach((deck) => {{
                            const box = document.createElement('div');
                            const outcome = roundOutcome(deck);
                            box.className = 'deck-box'
                                + (deck.deck_id === activeDeckId ? ' active' : '')
                                + (deck.role === 'dealer' ? ' dealer-box' : '')
                                + (outcome ? ` result-pulse ${{outcome.className}}` : '');
                            const pos = toScreen(deck);
                            box.style.left = pos.left + 'px';
                            box.style.top = pos.top + 'px';
                            box.style.width = pos.width + 'px';
                            box.style.height = pos.height + 'px';
                            box.dataset.deckId = deck.deck_id;

                            const label = document.createElement('div');
                            label.className = 'deck-label';
                            label.innerText = overlayLabel(deck);
                            box.appendChild(label);

                            const handle = document.createElement('div');
                            handle.className = 'resize-handle';
                            handle.title = 'Resize square ROI';
                            handle.addEventListener('pointerdown', onDeckResizePointerDown);
                            box.appendChild(handle);

                            box.addEventListener('pointerdown', onDeckPointerDown);
                            box.addEventListener('dblclick', (evt) => openCropPreviewOnDesktop(evt, deck.deck_id));
                            box.addEventListener('click', async (evt) => {{
                                evt.stopPropagation();
                                if (suppressNextDeckClick) {{
                                    evt.preventDefault();
                                    suppressNextDeckClick = false;
                                    return;
                                }}
                                if (deck.role === 'dealer') {{
                                    selectedDeckId = deck.deck_id;
                                    renderDecks();
                                    return;
                                }}
                                await setActiveDeck(deck.deck_id);
                            }});

                            overlay.appendChild(box);
                        }});

                        selectedDeckForList().forEach(deck => {{
                            const item = document.createElement('article');
                            const outcome = roundOutcome(deck);
                            const isDealer = deck.role === 'dealer';
                            const cards = Array.isArray(deck.cards) ? deck.cards : [];
                            const points = deck.points || '-';
                            item.className = `selected-deck-card ${{isDealer ? 'dealer' : 'player'}}`
                                + (outcome ? ` result-pulse ${{outcome.className}}` : '');
                            item.dataset.deckId = deck.deck_id;

                            const head = document.createElement('div');
                            head.className = 'selected-deck-head';
                            const avatar = document.createElement('div');
                            avatar.className = 'selected-deck-avatar';
                            avatar.textContent = isDealer ? 'D' : String(deck.name || 'P').trim().charAt(0).toUpperCase();
                            const identity = document.createElement('div');
                            identity.className = 'selected-deck-identity';
                            const role = document.createElement('div');
                            role.className = 'selected-deck-role';
                            role.textContent = isDealer
                                ? 'Dealer'
                                : (deck.deck_id === activeDeckId ? 'Active player' : 'Player');
                            const name = document.createElement('div');
                            name.className = 'selected-deck-name';
                            name.textContent = deck.role === 'dealer' ? 'Dealer' : deck.name;
                            identity.append(role, name);
                            const pointsPill = document.createElement('div');
                            pointsPill.className = 'selected-points-pill';
                            pointsPill.textContent = `${{points}} pts`;
                            head.append(avatar, identity, pointsPill);

                            const cardsSection = document.createElement('div');
                            cardsSection.className = 'selected-cards';
                            const cardsLabel = document.createElement('div');
                            cardsLabel.className = 'small';
                            cardsLabel.textContent = 'Detected cards';
                            const cardRow = document.createElement('div');
                            cardRow.className = 'selected-card-row';
                            if (cards.length) {{
                                cards.forEach(card => {{
                                    const display = playingCardDisplay(card);
                                    const chip = document.createElement('span');
                                    chip.className = 'playing-card-chip' + (display.red ? ' red' : '');
                                    chip.textContent = display.text;
                                    cardRow.appendChild(chip);
                                }});
                            }} else {{
                                const empty = document.createElement('span');
                                empty.className = 'selected-no-cards';
                                empty.textContent = 'No cards detected';
                                cardRow.appendChild(empty);
                            }}
                            cardsSection.append(cardsLabel, cardRow);

                            const status = document.createElement('div');
                            status.className = 'selected-status';
                            const statusLabel = document.createElement('span');
                            statusLabel.className = 'small';
                            statusLabel.textContent = isDealer
                                ? 'Status'
                                : (outcome ? 'Round result' : 'Recommendation');
                            const statusValue = document.createElement('strong');
                            statusValue.className = 'selected-status-value';
                            statusValue.textContent = isDealer
                                ? (cards.length ? `${{cards.length}} card${{cards.length === 1 ? '' : 's'}} visible` : 'Waiting for cards')
                                : (outcome ? outcome.label : (deck.last_recommendation || 'Waiting for cards'));
                            status.append(statusLabel, statusValue);

                            item.append(head, cardsSection, status);
                            attachListPreviewTriggers(item, deck.deck_id);
                            list.appendChild(item);
                        }});
                        const restoreDeckListScroll = () => {{
                            list.scrollTop = previousScrollTop;
                        }};
                        restoreDeckListScroll();
                        window.requestAnimationFrame(restoreDeckListScroll);
                        deckRenderSignature = deckUiSignature();
                        restorePageScroll(previousPageScrollTop);
                    }}

                    function selectedDeckForList() {{
                        const selected = decks.find(deck => deck.deck_id === selectedDeckId);
                        if (selected) return [selected];
                        const active = decks.find(deck => deck.deck_id === activeDeckId);
                        return active ? [active] : [];
                    }}

                    function overlayLabel(deck) {{
                        const isMobile = window.matchMedia('(max-width: 800px)').matches;
                        const isActive = deck.deck_id === activeDeckId;
                        const outcome = roundOutcome(deck);
                        const resultSuffix = outcome ? ` · ${{outcome.label.toUpperCase()}}` : '';
                        if (isMobile) {{
                            const name = deck.role === 'dealer' ? 'Dealer' : deck.name;
                            return `${{isActive ? '● ' : ''}}${{name}}${{resultSuffix}}`;
                        }}
                        return `${{isActive ? 'ON TURN · ' : ''}}${{deck.role === 'dealer' ? 'Dealer' : deck.name}}${{resultSuffix}}`;
                    }}

                    async function setActiveDeck(deckId) {{
                        const resp = await fetch('/active-deck', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{ deck_id: deckId }})
                        }});
                        const data = await resp.json().catch(() => ({{ ok: false }}));
                        if (!resp.ok || !data.ok) {{
                            await reloadDecks();
                            return;
                        }}
                        activeDeckId = data.active_deck_id || deckId;
                        selectedDeckId = deckId;
                        if (Array.isArray(data.decks)) {{
                            decks = data.decks;
                            decks.forEach(makeSquare);
                        }}
                        activeOutcome = roundOutcome(decks.find(deck => deck.deck_id === activeDeckId));
                        renderDecks();
                        renderActiveRecommendation();
                    }}

                    async function setupPlayerBoxes() {{
                        const countInput = document.getElementById('playerCount');
                        const count = clamp(parseInt(countInput.value || '1', 10), 1, 12);
                        const defaultNames = Array.from({{length: count}}, (_, i) => `Player ${{i + 1}}`).join(', ');
                        const namesInput = document.getElementById('playerNames');
                        const rawNames = (namesInput.value || defaultNames);
                        const names = rawNames.split(',').map(v => v.trim()).filter(Boolean);
                        if (!namesInput.value) namesInput.value = defaultNames;
                        await fetch('/player-boxes', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{ count, names }})
                        }});
                        await reloadDecks();
                    }}

                    function startAddDeck() {{
                        addMode = true;
                        window.__addRole = 'deck';
                        alert('Click inside the video to place a new square player box.');
                    }}

                    function startAddDealer() {{
                        addMode = true;
                        window.__addRole = 'dealer';
                        alert('Click inside the video to place the dealer box.');
                    }}

                    async function createDeckAt(clientX, clientY) {{
                        const role = window.__addRole || 'deck';
                        const defaultName = role === 'dealer' ? 'Dealer' : `Player ${{decks.filter(d => d.role !== 'dealer').length + 1}}`;
                        const name = prompt(role === 'dealer' ? 'Dealer name?' : 'Player name?', defaultName) || defaultName;
                        const pos = toSource(clientX, clientY);
                        await fetch('/decks', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{
                                name,
                                role,
                                x: pos.x,
                                y: pos.y,
                                width: DEFAULT_DECK_WIDTH,
                                height: DEFAULT_DECK_HEIGHT,
                            }})
                        }});
                        addMode = false;
                        window.__addRole = 'deck';
                        await reloadDecks();
                    }}

                    async function onDeckPointerDown(evt) {{
                        evt.preventDefault();
                        evt.stopPropagation();
                        const box = evt.currentTarget;
                        const deckId = evt.currentTarget.dataset.deckId;
                        const deck = decks.find(d => d.deck_id === deckId);
                        if (!deck) return;

                        const {{ rect, scaleX, scaleY }} = getOverlayMetrics();
                        isDragging = true;
                        evt.currentTarget.setPointerCapture(evt.pointerId);
                        const cropLongPress = beginCropLongPress(evt, deckId);
                        dragState = {{
                            deckId,
                            pointerId: evt.pointerId,
                            startX: evt.clientX,
                            startY: evt.clientY,
                            moved: false,
                            offsetX: evt.clientX - rect.left - deck.x * scaleX,
                            offsetY: evt.clientY - rect.top - deck.y * scaleY,
                        }};

                        const onMove = (moveEvt) => {{
                            if (!dragState) return;
                            moveEvt.preventDefault();
                            if (Math.abs(moveEvt.clientX - dragState.startX) > 3 || Math.abs(moveEvt.clientY - dragState.startY) > 3) {{
                                dragState.moved = true;
                            }}
                            updateCropLongPress(cropLongPress, moveEvt);
                            if (!dragState.moved) return;
                            const x = clamp(Math.round((moveEvt.clientX - rect.left - dragState.offsetX) / scaleX), 0, SOURCE_WIDTH - deck.width);
                            const y = clamp(Math.round((moveEvt.clientY - rect.top - dragState.offsetY) / scaleY), 0, SOURCE_HEIGHT - deck.height);
                            deck.x = x;
                            deck.y = y;
                            const pos = toScreen(deck);
                            box.style.left = pos.left + 'px';
                            box.style.top = pos.top + 'px';
                        }};

                        const onUp = async (upEvt) => {{
                            if (upEvt) upEvt.preventDefault();
                            document.removeEventListener('pointermove', onMove);
                            document.removeEventListener('pointerup', onUp);
                            document.removeEventListener('pointercancel', onUp);
                            cancelCropLongPress(cropLongPress);
                            if (!dragState) return;
                            const wasMoved = dragState.moved;
                            dragState = null;
                            if (longPressPreviewOpened) {{
                                longPressPreviewOpened = false;
                                isDragging = false;
                                return;
                            }}
                            if (!wasMoved) {{
                                isDragging = false;
                                await setActiveDeck(deckId);
                                return;
                            }}
                            suppressDeckClickBriefly();
                            isSavingRoi = true;
                            try {{
                                await fetch(`/decks/${{deckId}}`, {{
                                    method: 'PUT',
                                    headers: {{ 'Content-Type': 'application/json' }},
                                    body: JSON.stringify(deck)
                                }});
                                await reloadDecks(true);
                            }} finally {{
                                isSavingRoi = false;
                                isDragging = false;
                            }}
                        }};

                        document.addEventListener('pointermove', onMove);
                        document.addEventListener('pointerup', onUp);
                        document.addEventListener('pointercancel', onUp);
                    }}

                    async function onDeckResizePointerDown(evt) {{
                        evt.preventDefault();
                        evt.stopPropagation();
                        const box = evt.currentTarget.parentElement;
                        const deckId = box.dataset.deckId;
                        const deck = decks.find(d => d.deck_id === deckId);
                        if (!deck) return;

                        const {{ rect, scaleX, scaleY }} = getOverlayMetrics();
                        isDragging = true;
                        evt.currentTarget.setPointerCapture(evt.pointerId);

                        const onMove = (moveEvt) => {{
                            moveEvt.preventDefault();
                            const sourceX = Math.round((moveEvt.clientX - rect.left) / scaleX);
                            const sourceY = Math.round((moveEvt.clientY - rect.top) / scaleY);
                            const requested = Math.max(sourceX - deck.x, sourceY - deck.y);
                            const size = clampDeckSize(deck, requested);
                            deck.width = size;
                            deck.height = size;
                            const pos = toScreen(deck);
                            box.style.width = pos.width + 'px';
                            box.style.height = pos.height + 'px';
                        }};

                        const onUp = async (upEvt) => {{
                            if (upEvt) upEvt.preventDefault();
                            document.removeEventListener('pointermove', onMove);
                            document.removeEventListener('pointerup', onUp);
                            document.removeEventListener('pointercancel', onUp);
                            suppressDeckClickBriefly();
                            makeSquare(deck);
                            isSavingRoi = true;
                            try {{
                                await fetch(`/decks/${{deckId}}`, {{
                                    method: 'PUT',
                                    headers: {{ 'Content-Type': 'application/json' }},
                                    body: JSON.stringify(deck)
                                }});
                                await reloadDecks(true);
                            }} finally {{
                                isSavingRoi = false;
                                isDragging = false;
                            }}
                        }};

                        document.addEventListener('pointermove', onMove);
                        document.addEventListener('pointerup', onUp);
                        document.addEventListener('pointercancel', onUp);
                    }}

                    async function updatePrediction() {{
                        const resp = await fetch('/prediction');
                        const data = await resp.json();
                        latestPrediction = data.recommendation || 'No prediction';
                        renderActiveRecommendation();
                    }}

                    async function updateStats() {{
                        const resp = await fetch('/stats');
                        const data = await resp.json();
                        const trueCount = data.counts && data.counts.true_count !== undefined ? Number(data.counts.true_count) : 0;
                        document.getElementById('trueCount').innerText = trueCount.toFixed(2);
                        document.getElementById('countMeaning').innerText = describeTrueCount(trueCount);
                        if (data.deck_count !== undefined) {{
                            const deckCountInput = document.getElementById('deckCountInput');
                            if (document.activeElement !== deckCountInput) {{
                                deckCountInput.value = data.deck_count;
                            }}
                        }}
                        const active = (data.decks || []).find(deck => deck.deck_id === data.active_deck_id);
                        const stats = active && active.stats ? active.stats : {{ score: 0, wins: 0, losses: 0, pushes: 0 }};
                        activeOutcome = roundOutcome(active);
                        renderActiveRecommendation();
                        document.getElementById('doubleBtn').classList.toggle('selected', !!stats.current_double);
                        renderSplitHands(stats.split_session || null);
                        const cards = active && active.cards ? active.cards : [];
                        const splitActive = !!stats.split_session;
                        const canDouble = cards.length === 2 && !stats.current_event && !splitActive;
                        const canSplit = canDouble && cardRank(cards[0]) === cardRank(cards[1]);
                        document.getElementById('doubleBtn').disabled = !canDouble;
                        document.getElementById('splitBtn').disabled = !canSplit;
                        const recommendation = active && active.last_recommendation ? active.last_recommendation : document.getElementById('recbox').innerText;
                        document.getElementById('doubleBtn').classList.toggle('recommended', canDouble && isDoubleRecommendation(recommendation));
                        document.getElementById('splitBtn').classList.toggle('recommended', canSplit && isSplitRecommendation(recommendation));
                        document.getElementById('nextSplitBtn').disabled = !splitActive || stats.split_session.finished || stats.split_session.active_index >= 1;
                        document.getElementById('finishSplitBtn').disabled = !splitActive || stats.split_session.finished;
                        document.getElementById('cancelSplitBtn').disabled = !splitActive;
                        renderPlayerStatistics(data.decks || []);
                    }}

                    function isDoubleRecommendation(text) {{
                        const rec = String(text || '').toLowerCase();
                        return rec.includes('double');
                    }}

                    function isSplitRecommendation(text) {{
                        const rec = String(text || '').toLowerCase();
                        return rec.includes('split');
                    }}

                    function describeTrueCount(value) {{
                        if (value >= 2) return 'High cards expected';
                        if (value <= -2) return 'Low cards expected';
                        if (value > 0) return 'Slight high-card tendency';
                        if (value < 0) return 'Slight low-card tendency';
                        return 'Count neutral';
                    }}

                    function numberValue(value) {{
                        const parsed = Number(value || 0);
                        return Number.isFinite(parsed) ? parsed : 0;
                    }}

                    function signedPoints(value) {{
                        const points = numberValue(value);
                        return points > 0 ? `+${{points}}` : String(points);
                    }}

                    function scoreTone(value) {{
                        const score = numberValue(value);
                        if (score > 0) return 'positive';
                        if (score < 0) return 'negative';
                        return 'neutral';
                    }}

                    function historyResult(result) {{
                        if (result === 'win') return {{ label: 'Win', className: 'win' }};
                        if (result === 'loss') return {{ label: 'Busted', className: 'loss' }};
                        return {{ label: 'Push', className: 'push' }};
                    }}

                    function historyEventLabel(event) {{
                        const labels = {{
                            blackjack: 'Blackjack',
                            bust: 'Bust',
                            double: 'Double',
                            split_auto: 'Split',
                            auto_win: 'Standard',
                            auto_loss: 'Standard',
                            auto_push: 'Standard',
                        }};
                        return labels[event] || String(event || 'Round').replaceAll('_', ' ');
                    }}

                    function summaryTile(label, value) {{
                        const tile = document.createElement('div');
                        tile.className = 'summary-stat';
                        const caption = document.createElement('div');
                        caption.className = 'small';
                        caption.textContent = label;
                        const number = document.createElement('div');
                        number.className = 'num';
                        number.textContent = value;
                        tile.append(caption, number);
                        return tile;
                    }}

                    function playerMetric(label, value) {{
                        const metric = document.createElement('div');
                        metric.className = 'player-metric';
                        const number = document.createElement('strong');
                        number.textContent = value;
                        const caption = document.createElement('span');
                        caption.className = 'small';
                        caption.textContent = label;
                        metric.append(number, caption);
                        return metric;
                    }}

                    function renderPlayerStatistics(deckData) {{
                        const players = (deckData || []).filter(deck => deck.role !== 'dealer');
                        const signature = JSON.stringify(players.map(deck => ({{
                            id: deck.deck_id,
                            name: deck.name,
                            stats: deck.stats || {{}},
                        }})));
                        if (signature === statsRenderSignature) return;
                        if (userScrollActive) {{
                            pendingStatsDeckData = deckData;
                            return;
                        }}
                        statsRenderSignature = signature;

                        const content = document.getElementById('playerStatsContent');
                        const previousPageScrollTop = pageScrollTop();
                        const previousStatsScrollTop = content.scrollTop;
                        const previousHistoryScroll = new Map(
                            Array.from(content.querySelectorAll('.history-wrap[data-deck-id]'))
                                .map(history => [history.dataset.deckId, history.scrollTop])
                        );
                        content.innerHTML = '';
                        if (!players.length) {{
                            const empty = document.createElement('div');
                            empty.className = 'stats-empty';
                            empty.textContent = 'No players configured yet.';
                            content.appendChild(empty);
                            restorePageScroll(previousPageScrollTop);
                            return;
                        }}

                        const totalScore = players.reduce((sum, deck) => sum + numberValue((deck.stats || {{}}).score), 0);
                        const totalRounds = players.reduce((sum, deck) => sum + numberValue((deck.stats || {{}}).rounds), 0);
                        const summary = document.createElement('div');
                        summary.className = 'stats-summary';
                        summary.append(
                            summaryTile('Players', players.length),
                            summaryTile('Total points', signedPoints(totalScore)),
                            summaryTile('Rounds', totalRounds),
                        );
                        content.appendChild(summary);

                        const playerList = document.createElement('div');
                        playerList.className = 'player-stat-list';
                        players.forEach(deck => {{
                            const stats = deck.stats || {{}};
                            const wins = numberValue(stats.wins);
                            const losses = numberValue(stats.losses);
                            const pushes = numberValue(stats.pushes);
                            const decided = wins + losses;
                            const winRate = decided ? `${{Math.round((wins / decided) * 100)}}%` : '—';
                            const score = numberValue(stats.score);
                            const history = Array.isArray(stats.history) ? stats.history : [];
                            let runningScore = 0;
                            const rounds = history.map((event, index) => {{
                                runningScore += numberValue(event.delta);
                                return {{ event, round: index + 1, runningScore }};
                            }}).reverse();

                            const card = document.createElement('article');
                            card.className = 'player-stat-card';
                            card.dataset.deckId = deck.deck_id;
                            const head = document.createElement('div');
                            head.className = 'player-stat-head';
                            const name = document.createElement('div');
                            name.className = 'player-stat-name';
                            name.textContent = deck.name || deck.deck_id;
                            const scorePill = document.createElement('div');
                            scorePill.className = `score-pill ${{scoreTone(score)}}`;
                            scorePill.textContent = `${{signedPoints(score)}} pts`;
                            head.append(name, scorePill);
                            card.appendChild(head);

                            const metrics = document.createElement('div');
                            metrics.className = 'player-stat-metrics';
                            metrics.append(
                                playerMetric('Wins', wins),
                                playerMetric('Pushes', pushes),
                                playerMetric('Losses', losses),
                                playerMetric('Win rate', winRate),
                            );
                            card.appendChild(metrics);

                            if (!rounds.length) {{
                                const emptyHistory = document.createElement('div');
                                emptyHistory.className = 'history-empty';
                                emptyHistory.textContent = 'Round history will appear here.';
                                card.appendChild(emptyHistory);
                            }} else {{
                                const historyWrap = document.createElement('div');
                                historyWrap.className = 'history-wrap';
                                historyWrap.dataset.deckId = deck.deck_id;
                                const table = document.createElement('table');
                                table.className = 'history-table';
                                const tableHead = document.createElement('thead');
                                const headingRow = document.createElement('tr');
                                ['Round', 'Result', 'Play', 'Points', 'Total'].forEach(label => {{
                                    const th = document.createElement('th');
                                    th.textContent = label;
                                    headingRow.appendChild(th);
                                }});
                                tableHead.appendChild(headingRow);
                                const body = document.createElement('tbody');
                                rounds.forEach(item => {{
                                    const row = document.createElement('tr');
                                    const roundCell = document.createElement('td');
                                    roundCell.textContent = `#${{item.round}}`;
                                    const resultCell = document.createElement('td');
                                    const result = historyResult(item.event.result);
                                    const badge = document.createElement('span');
                                    badge.className = `result-badge ${{result.className}}`;
                                    badge.textContent = result.label;
                                    resultCell.appendChild(badge);
                                    const eventCell = document.createElement('td');
                                    eventCell.textContent = historyEventLabel(item.event.event);
                                    const deltaCell = document.createElement('td');
                                    deltaCell.className = `history-delta ${{scoreTone(item.event.delta)}}`;
                                    deltaCell.textContent = signedPoints(item.event.delta);
                                    const totalCell = document.createElement('td');
                                    totalCell.textContent = signedPoints(item.runningScore);
                                    row.append(roundCell, resultCell, eventCell, deltaCell, totalCell);
                                    body.appendChild(row);
                                }});
                                table.append(tableHead, body);
                                historyWrap.appendChild(table);
                                card.appendChild(historyWrap);
                            }}
                            playerList.appendChild(card);
                        }});
                        content.appendChild(playerList);
                        const restoreStatisticsScroll = () => {{
                            content.scrollTop = previousStatsScrollTop;
                            content.querySelectorAll('.history-wrap[data-deck-id]').forEach(history => {{
                                history.scrollTop = previousHistoryScroll.get(history.dataset.deckId) || 0;
                            }});
                        }};
                        restoreStatisticsScroll();
                        window.requestAnimationFrame(restoreStatisticsScroll);
                        restorePageScroll(previousPageScrollTop);
                    }}

                    async function toggleStatsFullscreen() {{
                        const panel = document.getElementById('playerStatsPanel');
                        try {{
                            if (document.fullscreenElement === panel) {{
                                await document.exitFullscreen();
                                return;
                            }}
                            if (document.fullscreenElement) await document.exitFullscreen();
                            await panel.requestFullscreen();
                        }} catch (err) {{
                            alert('Statistics fullscreen is not available in this browser.');
                        }}
                    }}

                    function setResetProgress(progress) {{
                        const button = document.getElementById('resetStatsButton');
                        const percent = Math.max(0, Math.min(100, progress * 100));
                        button.style.setProperty('--hold-progress', `${{percent}}%`);
                        button.setAttribute('aria-valuenow', String(Math.round(percent)));
                    }}

                    function cancelResetHold() {{
                        const button = document.getElementById('resetStatsButton');
                        if (button.disabled) return;
                        if (resetHoldTimer) window.clearTimeout(resetHoldTimer);
                        if (resetHoldFrame) window.cancelAnimationFrame(resetHoldFrame);
                        resetHoldTimer = null;
                        resetHoldFrame = null;
                        resetHoldStartedAt = 0;
                        button.classList.remove('holding');
                        document.getElementById('resetStatsLabel').textContent = 'Hold 5s · reset';
                        setResetProgress(0);
                    }}

                    function updateResetHoldProgress() {{
                        if (!resetHoldStartedAt) return;
                        const elapsed = performance.now() - resetHoldStartedAt;
                        const progress = Math.min(1, elapsed / RESET_HOLD_MS);
                        setResetProgress(progress);
                        const remaining = Math.max(0, Math.ceil((RESET_HOLD_MS - elapsed) / 1000));
                        document.getElementById('resetStatsLabel').textContent = `Keep holding · ${{remaining}}s`;
                        if (progress < 1) resetHoldFrame = window.requestAnimationFrame(updateResetHoldProgress);
                    }}

                    function startResetHold(evt) {{
                        const button = document.getElementById('resetStatsButton');
                        if (button.disabled || resetHoldStartedAt) return;
                        if (evt && evt.type === 'pointerdown' && evt.button !== 0) return;
                        if (evt) evt.preventDefault();
                        resetHoldStartedAt = performance.now();
                        button.classList.add('holding');
                        updateResetHoldProgress();
                        resetHoldTimer = window.setTimeout(performStatsReset, RESET_HOLD_MS);
                    }}

                    async function performStatsReset() {{
                        const button = document.getElementById('resetStatsButton');
                        if (resetHoldTimer) window.clearTimeout(resetHoldTimer);
                        if (resetHoldFrame) window.cancelAnimationFrame(resetHoldFrame);
                        resetHoldTimer = null;
                        resetHoldFrame = null;
                        resetHoldStartedAt = 0;
                        button.classList.remove('holding');
                        button.disabled = true;
                        setResetProgress(1);
                        document.getElementById('resetStatsLabel').textContent = 'Resetting…';
                        const status = document.getElementById('resetStatus');
                        try {{
                            const resp = await fetch('/reset-stats', {{ method: 'POST' }});
                            const data = await resp.json().catch(() => ({{ ok: false }}));
                            if (!resp.ok || !data.ok) throw new Error(data.error || 'Reset failed');
                            statsRenderSignature = '';
                            activeOutcome = null;
                            renderActiveRecommendation();
                            await reloadDecks(true);
                            await updateStats();
                            status.textContent = 'All scores and history reset. Clear the table before the next round.';
                            document.getElementById('resetStatsLabel').textContent = 'Reset complete';
                        }} catch (err) {{
                            status.textContent = '';
                            alert(err.message || 'Could not reset statistics.');
                            document.getElementById('resetStatsLabel').textContent = 'Reset failed';
                        }} finally {{
                            window.setTimeout(() => {{
                                button.disabled = false;
                                document.getElementById('resetStatsLabel').textContent = 'Hold 5s · reset';
                                setResetProgress(0);
                            }}, 1400);
                        }}
                    }}

                    async function saveDeckCount() {{
                        const input = document.getElementById('deckCountInput');
                        const decks = Number(input.value || 1);
                        const resp = await fetch('/deck-count', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{ decks }})
                        }});
                        const data = await resp.json().catch(() => ({{ ok: false, error: 'Could not save deck count' }}));
                        if (!resp.ok || !data.ok) {{
                            alert(data.error || 'Could not save deck count');
                            return;
                        }}
                        input.value = data.decks;
                        await updateStats();
                    }}

                    function renderSplitHands(session) {{
                        const box = document.getElementById('splitHands');
                        if (!session) {{
                            box.style.display = 'none';
                            box.innerHTML = '';
                            return;
                        }}
                        box.style.display = 'grid';
                        box.innerHTML = '';
                        (session.hands || []).forEach((hand, idx) => {{
                            const item = document.createElement('div');
                            item.className = 'split-hand' + (idx === session.active_index && !session.finished ? ' active' : '');
                            const cards = hand.cards && hand.cards.length ? hand.cards.join(', ') : 'no cards';
                            const status = session.finished || hand.stopped ? 'stopped' : 'active';
                            item.innerHTML = `<strong>Hand ${{hand.label || idx + 1}}</strong><br>${{cards}}<br><span class="small">${{status}}</span>`;
                            box.appendChild(item);
                        }});
                    }}

                    function cardRank(card) {{
                        if (!card) return '';
                        return card.startsWith('10') ? '10' : card[0];
                    }}

                    async function scoreAction(action) {{
                        if (!activeDeckId) return;
                        const resp = await fetch('/action', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{ action, deck_id: activeDeckId }})
                        }});
                        if (!resp.ok) {{
                            const data = await resp.json().catch(() => ({{ error: 'Action rejected' }}));
                            alert(data.error || 'Action rejected');
                        }}
                        await reloadDecks();
                        await updateStats();
                    }}

                    async function toggleFullscreen() {{
                        try {{
                            if (!document.fullscreenElement) {{
                                await document.documentElement.requestFullscreen();
                                await lockPortrait();
                                return;
                            }}
                            await document.exitFullscreen();
                        }} catch (err) {{
                            alert('Fullscreen is not available in this browser.');
                        }}
                    }}

                    document.addEventListener('fullscreenchange', () => {{
                        if (!document.fullscreenElement) {{
                            unlockOrientation();
                        }}
                        const statsPanel = document.getElementById('playerStatsPanel');
                        document.getElementById('statsFullscreenBtn').innerText = document.fullscreenElement === statsPanel ? 'Exit fullscreen' : 'Fullscreen';
                        renderDecks();
                    }});

                    async function lockPortrait() {{
                        try {{
                            if (screen.orientation && screen.orientation.lock) {{
                                await screen.orientation.lock('portrait');
                            }}
                        }} catch (err) {{
                            console.warn('Portrait lock unavailable:', err);
                        }}
                    }}

                    function unlockOrientation() {{
                        try {{
                            if (screen.orientation && screen.orientation.unlock) {{
                                screen.orientation.unlock();
                            }}
                        }} catch (err) {{}}
                    }}

                    window.addEventListener('scroll', markScrollActivity, {{ passive: true }});
                    document.addEventListener('scroll', markScrollActivity, {{ capture: true, passive: true }});

                    window.addEventListener('resize', () => {{
                        if (userScrollActive) {{
                            deckRenderPending = true;
                            return;
                        }}
                        renderDecks();
                    }});

                    document.getElementById('cropModal').addEventListener('click', (evt) => {{
                        if (evt.target.id === 'cropModal') {{
                            closeCropPreview();
                        }}
                    }});
                    document.getElementById('cropModal').addEventListener('contextmenu', (evt) => evt.preventDefault());
                    document.getElementById('overlay').addEventListener('contextmenu', (evt) => evt.preventDefault());
                    document.getElementById('deckList').addEventListener('contextmenu', (evt) => evt.preventDefault());

                    const resetStatsButton = document.getElementById('resetStatsButton');
                    resetStatsButton.addEventListener('pointerdown', startResetHold);
                    resetStatsButton.addEventListener('pointerup', cancelResetHold);
                    resetStatsButton.addEventListener('pointercancel', cancelResetHold);
                    resetStatsButton.addEventListener('pointerleave', cancelResetHold);
                    resetStatsButton.addEventListener('contextmenu', (evt) => evt.preventDefault());
                    resetStatsButton.addEventListener('keydown', (evt) => {{
                        if ((evt.key === ' ' || evt.key === 'Enter') && !evt.repeat) startResetHold(evt);
                    }});
                    resetStatsButton.addEventListener('keyup', (evt) => {{
                        if (evt.key === ' ' || evt.key === 'Enter') cancelResetHold();
                    }});

                    document.addEventListener('keydown', (evt) => {{
                        if (evt.key === 'Escape') {{
                            closeCropPreview();
                        }}
                    }});

                    document.getElementById('frameWrap').addEventListener('click', async (evt) => {{
                        if (!addMode) return;
                        await createDeckAt(evt.clientX, evt.clientY);
                    }});

                    function scheduleNextFrame(delay = 200) {{
                        window.setTimeout(loadNextFrame, delay);
                    }}

                    function loadNextFrame() {{
                        const frame = document.getElementById('frame');
                        const next = new Image();
                        next.onload = () => {{
                            frame.src = next.src;
                            scheduleNextFrame(120);
                        }};
                        next.onerror = () => {{
                            scheduleNextFrame(500);
                        }};
                        next.src = '/image?ts=' + Date.now();
                    }}

                    setInterval(updatePrediction, 500);
                    setInterval(updateStats, 500);
                    setInterval(reloadDecks, 1000);

                    scheduleNextFrame(250);
                    reloadDecks();
                    updatePrediction();
                    updateStats();
                </script>
            </body>
        </html>
        """


@app.route("/image")
def image():
    """Serve latest capture."""
    if os.path.exists(WEB_IMAGE_PATH):
        return send_file(WEB_IMAGE_PATH, mimetype='image/jpeg')
    if os.path.exists(IMAGE_PATH):
        return send_file(IMAGE_PATH, mimetype='image/jpeg')
    return "No image", 404


@app.route("/deck-crop/<deck_id>")
def deck_crop(deck_id):
    """Serve the selected ROI crop resized to the model input view."""
    deck_registry.refresh_from_disk()
    deck = find_deck(deck_registry.decks, deck_id)
    if deck is None:
        return "Deck not found", 404

    if not os.path.exists(IMAGE_PATH):
        return "No image", 404

    frame = cv2.imread(IMAGE_PATH)
    if frame is None:
        return "No image", 404

    roi = deck.clamp(frame.shape[1], frame.shape[0])
    crop = frame[roi.y:roi.y + roi.height, roi.x:roi.x + roi.width]
    if crop.size == 0:
        return "Empty crop", 404

    model_view = cv2.resize(
        crop,
        (DEFAULT_DECK_WIDTH, DEFAULT_DECK_HEIGHT),
        interpolation=cv2.INTER_LINEAR,
    )
    ok, encoded = cv2.imencode(".jpg", model_view, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        return "Could not encode crop", 500

    return Response(
        encoded.tobytes(),
        mimetype="image/jpeg",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.route("/decks", methods=["GET", "POST"])
def decks():
    deck_registry.refresh_from_disk()
    if request.method == "GET":
        summary = _merged_deck_summary()
        summary["frame_width"] = config.FRAME_WIDTH
        summary["frame_height"] = config.FRAME_HEIGHT
        return jsonify(summary)

    data = request.get_json(force=True, silent=True) or {}
    name = str(data.get("name") or f"Deck {len(deck_registry.decks) + 1}")
    deck_id = str(data.get("deck_id") or name.lower().replace(" ", "-") + f"-{len(deck_registry.decks) + 1}")
    role = str(data.get("role") or "deck")
    if role.lower() == "dealer":
        deck_id = "dealer"
        for existing in list(deck_registry.decks):
            if existing.is_dealer() and existing.deck_id != deck_id:
                deck_registry.remove(existing.deck_id)
    deck = DeckROI(
        deck_id=deck_id,
        name=name,
        role=role,
        x=int(data.get("x", 0)),
        y=int(data.get("y", 0)),
        width=int(data.get("width", DEFAULT_DECK_WIDTH)),
        height=int(data.get("height", DEFAULT_DECK_HEIGHT)),
        enabled=bool(data.get("enabled", True)),
    ).clamp(config.FRAME_WIDTH, config.FRAME_HEIGHT)
    deck_registry.upsert(deck)
    return jsonify({"ok": True, "deck": deck_to_dict(deck), "decks": deck_registry.list_decks()})


@app.route("/decks/<deck_id>", methods=["PUT", "DELETE"])
def deck_item(deck_id):
    deck_registry.refresh_from_disk()
    deck = find_deck(deck_registry.decks, deck_id)
    if deck is None:
        return jsonify({"ok": False, "error": "deck not found"}), 404

    if request.method == "DELETE":
        deck_registry.remove(deck_id)
        if deck_registry.active_deck_id == deck_id:
            deck_registry.refresh_from_disk()
        return jsonify({"ok": True, "decks": deck_registry.list_decks()})

    data = request.get_json(force=True, silent=True) or {}
    updated = DeckROI(
        deck_id=deck.deck_id,
        name=str(data.get("name", deck.name)),
        role=str(data.get("role", deck.role)),
        x=int(data.get("x", deck.x)),
        y=int(data.get("y", deck.y)),
        width=int(data.get("width", deck.width)),
        height=int(data.get("height", deck.height)),
        enabled=bool(data.get("enabled", deck.enabled)),
    ).clamp(config.FRAME_WIDTH, config.FRAME_HEIGHT)
    deck_registry.upsert(updated)
    return jsonify({"ok": True, "deck": deck_to_dict(updated), "decks": deck_registry.list_decks()})


@app.route("/player-boxes", methods=["POST"])
def player_boxes():
    data = request.get_json(force=True, silent=True) or {}
    try:
        count = int(data.get("count", 1))
    except Exception:
        count = 1
    count = max(1, min(count, 12))

    raw_names = data.get("names") or []
    names = [str(name).strip() for name in raw_names if str(name).strip()]

    deck_registry.refresh_from_disk()
    dealer_decks = [deck for deck in deck_registry.decks if deck.is_dealer()]

    cols = max(1, config.FRAME_WIDTH // DEFAULT_DECK_WIDTH)
    created = []
    new_decks = list(dealer_decks)
    for idx in range(count):
        name = names[idx] if idx < len(names) else f"Player {idx + 1}"
        x = (idx % cols) * DEFAULT_DECK_WIDTH
        y = (idx // cols) * DEFAULT_DECK_HEIGHT
        deck = DeckROI(
            deck_id=f"player-{idx + 1}",
            name=name,
            role="deck",
            x=x,
            y=y,
            width=DEFAULT_DECK_WIDTH,
            height=DEFAULT_DECK_HEIGHT,
            enabled=True,
        ).clamp(config.FRAME_WIDTH, config.FRAME_HEIGHT)
        new_decks.append(deck)
        created.append(deck_to_dict(deck))

    active_id = created[0]["deck_id"] if created else None
    save_decks(new_decks, active_id)
    deck_registry.refresh_from_disk()
    if created:
        deck_registry.set_active_deck(active_id)

    return jsonify({
        "ok": True,
        "created": created,
        "decks": deck_registry.list_decks(),
        "active_deck_id": deck_registry.active_deck_id,
    })


@app.route("/active-deck", methods=["POST"])
def active_deck():
    data = request.get_json(force=True, silent=True) or {}
    deck_id = str(data.get("deck_id") or "")
    ok = deck_registry.set_active_deck(deck_id)
    return jsonify({"ok": ok, "active_deck_id": deck_registry.active_deck_id, "decks": deck_registry.list_decks()})


@app.route("/prediction")
def prediction():
    if os.path.exists(TEXT_PATH):
        return jsonify({"recommendation": open(TEXT_PATH).read()})
    return jsonify({"recommendation": None})


@app.route("/cards")
def cards():
    try:
        return jsonify(_merged_deck_summary())
    except Exception as e:
        return jsonify({"decks": [], "active_deck_id": None, "error": str(e)})


@app.route("/stats")
def stats():
    """Return game statistics and last outcome."""
    try:
        # Prefer the on-disk stats file because websocket runs in a separate process
        stats_path = os.path.join("outputs", "game_stats.json")
        counts_path = os.path.join("outputs", "card_counts.json")
        stats = {}
        if os.path.exists(stats_path):
            with open(stats_path, "r") as f:
                try:
                    stats = json.load(f)
                except Exception:
                    stats = {}

        counts = {}
        if os.path.exists(counts_path):
            with open(counts_path, "r") as f:
                try:
                    counts = json.load(f)
                except Exception:
                    counts = {}

        deck_summary = _merged_deck_summary()
        return jsonify({
            "player_wins": stats.get("player_wins", 0),
            "dealer_wins": stats.get("dealer_wins", 0),
            "pushes": stats.get("pushes", 0),
            "blackjacks": stats.get("blackjacks", 0),
            "last_outcome": stats.get("last_outcome", None),
            "round_phase": stats.get("round_phase", "unknown"),
            "current_leader": stats.get("current_leader", "unknown"),
            "counts": counts,
            "decks": deck_summary.get("decks", []),
            "deck_count": postprocessing.load_deck_count(),
            "active_deck_id": deck_summary.get("active_deck_id"),
            "active_deck": deck_summary.get("active_deck"),
            "player_stats": deck_summary.get("player_stats", {}),
        })
    except Exception as e:
        return jsonify({"error": str(e), "player_wins": 0, "dealer_wins": 0, "pushes": 0, "blackjacks": 0, "last_outcome": None})


@app.route("/deck-count", methods=["GET", "POST"])
def deck_count():
    if request.method == "GET":
        return jsonify({"decks": postprocessing.load_deck_count()})

    data = request.get_json(force=True, silent=True) or {}
    try:
        decks = int(data.get("decks", 1))
    except Exception:
        return jsonify({"ok": False, "error": "Invalid deck count"}), 400
    decks = postprocessing.save_deck_count(decks)
    return jsonify({"ok": True, "decks": decks})


@app.route("/reset-stats", methods=["POST"])
def reset_stats():
    try:
        request_id = postprocessing.request_full_reset()
        return jsonify({
            "ok": True,
            "request_id": request_id,
            "message": "All player scores and round history were reset.",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500



@app.route("/action", methods=["POST"])
def action():
    try:
        data = request.get_json() or {}
        act = data.get("action")
        if not act:
            return jsonify({"ok": False, "error": "no action"}), 400

        if act in {"double", "start_split", "next_split_hand", "finish_split", "cancel_split", "undo_current", "clear_round_flags"}:
            deck_id = str(data.get("deck_id") or deck_registry.active_deck_id or "")
            runtime_deck = _active_runtime_deck(deck_id)
            if act == "double" and not _can_double(runtime_deck):
                return jsonify({"ok": False, "error": "double requires exactly two visible cards"}), 400
            if act == "start_split" and not _can_split(runtime_deck):
                return jsonify({"ok": False, "error": "split requires a visible pair"}), 400
            postprocessing.registry.refresh_from_disk()
            if deck_id in postprocessing.registry.states:
                postprocessing.registry.states[deck_id].cards = list(runtime_deck.get("cards") or [])
            points = data.get("points", 0)
            return jsonify(postprocessing.apply_manual_score(deck_id, act, points=points))

        sess = postprocessing.session
        if act == "stand":
            sess.stand_current_hand()
            return jsonify({"ok": True})
        if act == "next_hand":
            sess.advance_hand()
            return jsonify({"ok": True})

        return jsonify({"ok": False, "error": "unknown action"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    debug = os.environ.get("BLACKJACK_FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=5000, debug=debug, use_reloader=debug)
