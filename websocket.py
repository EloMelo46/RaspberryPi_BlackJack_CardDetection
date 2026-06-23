from flask import Flask, send_file, jsonify, request
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
        for key in ("cards", "seen_counter", "last_recommendation", "running_count", "true_count", "points", "best_value", "stats"):
            if key in runtime_deck:
                merged[key] = runtime_deck[key]
        if merged.get("deck_id") in player_stats:
            merged["stats"] = player_stats[merged["deck_id"]]
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
    summary["player_stats"] = player_stats or runtime.get("player_stats", {})
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
                    .app {{ display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 16px; padding: 16px; align-items: start; }}
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
                    .deck-label {{ position: absolute; left: 8px; top: -12px; background: var(--panel); border: 1px solid rgba(255,255,255,0.08); padding: 3px 8px; border-radius: 999px; font-size: 12px; }}
                    .resize-handle {{ position: absolute; right: -5px; bottom: -5px; width: 12px; height: 12px; border-radius: 4px; background: rgba(238,242,255,0.72); border: 1px solid var(--panel); box-shadow: 0 1px 6px rgba(0,0,0,.28); cursor: nwse-resize; touch-action: none; }}
                    .sidebar {{ display: grid; gap: 12px; }}
                    .card {{ background: rgba(18,22,35,.9); border: 1px solid rgba(255,255,255,.07); border-radius: 16px; padding: 14px; }}
                    .deck-list {{ display: grid; gap: 8px; margin-top: 10px; }}
                    .deck-item {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 10px; border-radius: 12px; background: rgba(255,255,255,.04); cursor: pointer; }}
                    .deck-item.active {{ outline: 2px solid var(--good); background: rgba(34,197,94,0.16); box-shadow: 0 0 0 2px rgba(34,197,94,0.18); }}
                    .deck-name {{ font-weight: 600; }}
                    .small {{ font-size: 12px; color: var(--muted); }}
                    .value {{ font-variant-numeric: tabular-nums; }}
                    .rec {{ font-size: 28px; font-weight: 800; line-height: 1.1; margin-top: 6px; }}
                    .rec-top {{ display: grid; grid-template-columns: minmax(0, 1fr) 132px; gap: 10px; align-items: start; }}
                    .count-card {{ background: rgba(255,255,255,.04); border-radius: 12px; padding: 10px; }}
                    .count-value {{ font-size: 26px; font-weight: 800; }}
                    .count-meaning {{ margin-top: 4px; }}
                    .result-title {{ margin-top: 10px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,.08); }}
                    .deck-count-row {{ display: grid; grid-template-columns: 86px auto; gap: 8px; }}
                    #deckCountInput {{ max-width: 120px; }}
                    .stats {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }}
                    .score-grid {{ display: grid; gap: 8px; }}
                    .score-row {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }}
                    .stat {{ background: rgba(255,255,255,.04); border-radius: 12px; padding: 10px; }}
                    .stat .label {{ font-size: 12px; color: var(--muted); }}
                    .stat .num {{ font-size: 22px; font-weight: 800; }}
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
                    html:fullscreen body {{ min-height: 100vh; background: var(--bg); }}
                    html:fullscreen .app {{ min-height: 100vh; box-sizing: border-box; }}
                    @media (max-width: 800px) {{
                        body {{ overflow-y: auto; }}
                        .app {{ display: block; min-height: 100dvh; box-sizing: border-box; padding: 6px; }}
                        .stage {{ padding: 6px; border-radius: 12px; margin-bottom: 6px; }}
                        .setup-panel {{ grid-template-columns: 72px minmax(0, 1fr); gap: 6px; margin-bottom: 8px; }}
                        .setup-panel button {{ grid-column: 1 / -1; }}
                        .toolbar {{ gap: 6px; margin-bottom: 8px; }}
                        .toolbar button {{ flex: 1 1 30%; padding: 9px 8px; }}
                        .deck-count-row {{ flex: 1 1 100%; grid-template-columns: 78px 1fr; }}
                        .hint {{ display: none; }}
                        .frame-wrap {{ aspect-ratio: {config.FRAME_WIDTH} / {config.FRAME_HEIGHT}; height: auto; border-radius: 10px; }}
                        .sidebar {{ display: grid; gap: 6px; overflow: visible; }}
                        .card {{ padding: 8px; border-radius: 12px; }}
                        .rec-top {{ grid-template-columns: minmax(0, 1fr) 92px; gap: 6px; }}
                        .count-card {{ padding: 8px; }}
                        .count-meaning {{ margin-top: 2px; font-size: 9px; line-height: 1.1; }}
                        .result-title {{ margin-top: 6px; padding-top: 6px; }}
                        .rec {{ font-size: 20px; }}
                        .count-value {{ font-size: 20px; }}
                        .deck-box {{ border-width: 1px; border-radius: 6px; }}
                        .deck-box.active {{ border-width: 2px; box-shadow: 0 0 0 1px rgba(34,197,94,0.22), 0 0 14px rgba(34,197,94,0.24); }}
                        .deck-label {{ left: 3px; top: -11px; max-width: 90%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 1px 4px; font-size: 8px; line-height: 1; }}
                        .resize-handle {{ right: -4px; bottom: -4px; width: 10px; height: 10px; border-radius: 3px; }}
                        .stat {{ padding: 7px; }}
                        .stat .label {{ font-size: 11px; }}
                        .stat .num {{ font-size: 17px; }}
                        .score-grid {{ gap: 5px; }}
                        .score-row {{ gap: 5px; }}
                        .score-actions {{ gap: 5px; margin-top: 6px; }}
                        .score-actions-row {{ gap: 5px; }}
                        .score-actions button {{ padding: 7px 5px; font-size: 11px; }}
                        .split-hands {{ margin-top: 6px; }}
                        .deck-list {{ max-height: 116px; overflow: auto; overscroll-behavior: contain; -webkit-overflow-scrolling: touch; }}
                        .deck-item {{ padding: 8px; }}
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
                            <div class="small result-title">Player Result</div>
                            <div class="score-grid">
                                <div class="score-row">
                                    <div class="stat"><div class="label">Wins</div><div class="num value" id="activeWins">0</div></div>
                                    <div class="stat"><div class="label">Pushes</div><div class="num value" id="activePushes">0</div></div>
                                    <div class="stat"><div class="label">Losses</div><div class="num value" id="activeLosses">0</div></div>
                                </div>
                                <div class="stat"><div class="label">Current Score</div><div class="num value" id="activeScore">0</div></div>
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
                        <div class="card">
                            <div class="small">Players / Dealer</div>
                            <div id="deckList" class="deck-list"></div>
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
                    let addMode = false;
                    let dragState = null;
                    let isDragging = false;
                    let isSavingRoi = false;
                    let suppressNextDeckClick = false;

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

                    async function reloadDecks(force = false) {{
                        if (!force && (isDragging || isSavingRoi)) return;
                        const resp = await fetch('/decks');
                        if (!resp.ok) return;
                        const data = await resp.json();
                        if (!Array.isArray(data.decks)) return;
                        decks = data.decks || [];
                        decks.forEach(makeSquare);
                        activeDeckId = data.active_deck_id || null;
                        renderDecks();
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
                        overlay.innerHTML = '';
                        list.innerHTML = '';

                        decks.forEach((deck) => {{
                            const box = document.createElement('div');
                            box.className = 'deck-box' + (deck.deck_id === activeDeckId ? ' active' : '') + (deck.role === 'dealer' ? ' dealer-box' : '');
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
                            box.addEventListener('click', async (evt) => {{
                                evt.stopPropagation();
                                if (suppressNextDeckClick) {{
                                    evt.preventDefault();
                                    suppressNextDeckClick = false;
                                    return;
                                }}
                                await setActiveDeck(deck.deck_id);
                            }});

                            overlay.appendChild(box);
                        }});

                        sortedDecksForList().forEach(deck => {{
                            const item = document.createElement('div');
                            item.className = 'deck-item' + (deck.deck_id === activeDeckId ? ' active' : '');
                            const cards = deck.cards && deck.cards.length ? deck.cards.join(', ') : 'no cards';
                            const rec = deck.last_recommendation || '';
                            const points = deck.points || '-';
                            item.innerHTML = `<div><div class="deck-name">${{deck.role === 'dealer' ? 'Dealer' : deck.name}}</div><div class="small">${{cards}}</div><div class="small">${{rec}}</div></div><div class="small value">${{points}} pts</div>`;
                            if (deck.role !== 'dealer') {{
                                item.addEventListener('click', async () => {{
                                    await setActiveDeck(deck.deck_id);
                                }});
                            }}
                            list.appendChild(item);
                        }});
                        list.scrollTop = previousScrollTop;
                    }}

                    function sortedDecksForList() {{
                        return [...decks].sort((a, b) => {{
                            const aDealer = a.role === 'dealer';
                            const bDealer = b.role === 'dealer';
                            if (a.deck_id === activeDeckId && !aDealer) return -1;
                            if (b.deck_id === activeDeckId && !bDealer) return 1;
                            if (aDealer && !bDealer) return 1;
                            if (!aDealer && bDealer) return -1;
                            return 0;
                        }});
                    }}

                    function overlayLabel(deck) {{
                        const isMobile = window.matchMedia('(max-width: 800px)').matches;
                        const isActive = deck.deck_id === activeDeckId;
                        if (isMobile) {{
                            const name = deck.role === 'dealer' ? 'Dealer' : deck.name;
                            return `${{isActive ? '● ' : ''}}${{name}}`;
                        }}
                        return `${{isActive ? 'ON TURN · ' : ''}}${{deck.role === 'dealer' ? 'Dealer' : deck.name}}`;
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
                        if (Array.isArray(data.decks)) {{
                            decks = data.decks;
                            decks.forEach(makeSquare);
                        }}
                        renderDecks();
                        document.getElementById('deckList').scrollTop = 0;
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
                            if (!dragState) return;
                            const wasMoved = dragState.moved;
                            dragState = null;
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
                        const rec = data.recommendation || 'No prediction';
                        document.getElementById('recbox').innerText = rec;
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
                        document.getElementById('activeScore').innerText = stats.score || 0;
                        document.getElementById('activeWins').innerText = stats.wins || 0;
                        document.getElementById('activeLosses').innerText = stats.losses || 0;
                        document.getElementById('activePushes').innerText = stats.pushes || 0;
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

                    window.addEventListener('resize', () => {{
                        renderDecks();
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
    app.run(host="0.0.0.0", port=5000, debug=True)
