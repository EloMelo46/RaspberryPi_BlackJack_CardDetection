from flask import Flask, send_file, jsonify, request
import os
import re
import postprocessing

app = Flask(__name__)

IMAGE_PATH = os.path.join("outputs", "latest.jpg")
TEXT_PATH = os.path.join("outputs", "latest.txt")
PLAYER_PATH = os.path.join("outputs", "player_cards.txt")
DEALER_PATH = os.path.join("outputs", "dealer_cards.txt")


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
           <title>Blackjack Basic Strategy</title> 

            <style>
                body {{
                    background: #0f0f0f;
                    color: #fff;
                    font-family: Arial, sans-serif;
                    text-align: center;
                    margin: 0;
                    padding: 20px;
                }}

                h1 {{
                    font-size: 42px;  
                    font-weight: 600;
                    letter-spacing: 1px; 
                    margin-bottom: 30px; 
                    color: #fff;            /* White */
                    text-shadow: 0 0 12px rgba(255, 255, 255, 0.6);
                    font-family: "URW Gothic", 'Arial', sans-serif; 
                }}


                #frame {{
                    width: 90%;
                    max-width: 900px;
                    border-radius: 16px;
                    box-shadow: 0 0 22px rgba(0, 255, 255, 0.15);
                    margin-bottom: 20px;
                }}

                .panel-wrapper {{
                    display: flex;
                    width: 90%;
                    max-width: 900px;
                    margin: 0 auto;
                    margin-top: 10px;
                    justify-content: space-between;
                }}

                .panel {{
                    width: 48%;
                    padding: 14px 0;
                    border-radius: 12px;
                    background: rgba(20,20,20,0.9);
                    box-shadow: 0 0 12px rgba(0,0,0,0.6);
                }}

                .panel-title {{
                    font-size: 35px;
                    font-weight: 500;
                    margin-bottom: 20px;
                    opacity: 0.85;
                }}

                .card-row {{
                    display: flex;
                    justify-content: center;
                    flex-wrap: wrap;
                    gap: 12px;
                }}

                .card-pill {{
                    display: flex;
                    justify-content: center;
                    align-items: center;

                    width: 70px;     
                    height: 110px;      
                    font-size: 28px;

                    background: #1e1e1e;
                    border-radius: 8px;
                    box-shadow: 0 0 10px rgba(0,0,0,0.5);

                    text-align: center;
                }}


                .card-black {{
                    color: #ffffff;
                }}

                .card-red {{
                    color: #ff4b4b;
                }}

                /* --- RECOMMENDATION BOX --- */
                .recbox-wrapper {{
                    width: 100%;
                    height: 140px;          /* FIXED height */
                    margin-top: 40px;       /* spacing from panels */
                    position: relative;     
                }}

                #recbox {{
                    width: 85%;
                    max-width: 900px;
                    padding: 18px;
                    border-radius: 12px;
                    font-size: 40px;
                    font-weight: bold;
                    background: #1a1a1a;
                    color: white;
                    transition: 0.25s ease;
                    text-align: center;
                    position: absolute;
                    top: 20px;              /* fixed vertical position */
                    left: 50%;
                    transform: translateX(-50%);
                }}

                .hit {{
                    background: rgba(0, 200, 0, 0.35);
                    box-shadow: 0 0 12px rgba(0, 255, 0, 0.7);
                }}

                .stand {{
                    background: rgba(230, 0, 0, 0.35);
                    box-shadow: 0 0 12px rgba(255, 0, 0, 0.7);
                }}

                .double {{
                    background: rgba(255, 200, 0, 0.35);
                    box-shadow: 0 0 12px rgba(255, 220, 0, 0.8);
                }}

                .split {{
                    background: rgba(0, 180, 255, 0.35);
                    box-shadow: 0 0 12px rgba(0, 180, 255, 0.7);
                }}

                /* --- OUTCOME & STATS --- */
                .outcome-wrapper {{
                    width: 90%;
                    max-width: 900px;
                    margin: 20px auto;
                    display: flex;
                    gap: 20px;
                    justify-content: space-between;
                }}

                .outcome-box {{
                    flex: 1;
                    padding: 16px;
                    background: rgba(20,20,20,0.9);
                    border-radius: 12px;
                    box-shadow: 0 0 12px rgba(0,0,0,0.6);
                    text-align: center;
                }}

                .outcome-title {{
                    font-size: 18px;
                    font-weight: 600;
                    margin-bottom: 12px;
                    opacity: 0.7;
                }}

                #last-outcome {{
                    font-size: 32px;
                    font-weight: bold;
                    min-height: 45px;
                    color: #fff;
                }}

                .outcome-win {{
                    color: #00ff00;
                }}

                .outcome-loss {{
                    color: #ff4444;
                }}

                .outcome-push {{
                    color: #ffdd00;
                }}

                .stat-row {{
                    display: flex;
                    justify-content: space-around;
                    gap: 8px;
                    margin-top: 8px;
                }}

                .stat-item {{
                    flex: 1;
                    font-size: 14px;
                    padding: 6px;
                }}

                .stat-label {{
                    opacity: 0.6;
                    font-size: 12px;
                }}

                .stat-value {{
                    font-size: 20px;
                    font-weight: bold;
                    color: #00dd00;
                }}
                .dealer-active {{
                    border: 2px solid rgba(0,200,255,0.9);
                    box-shadow: 0 0 18px rgba(0,200,255,0.12);
                }}

                #dealer-status {{
                    font-size: 14px;
                    opacity: 0.85;
                    margin-bottom: 6px;
                }}
            </style>
        </head>

        <body>

            <h1>Blackjack Basic Strategy</h1>

            <!-- Video -->
            <img id="frame" src="/image">

            <!-- Fixed recommendation area before panels -->
            <div class="recbox-wrapper">
                <div id="recbox">{open(TEXT_PATH).read() if os.path.exists(TEXT_PATH) else "No prediction"}</div>
            </div>

            <div style="margin-top: 12px;">
                <button onclick="sendAction('split')">Split</button>
                <button onclick="sendAction('stand')">Stand</button>
            </div>

            <!-- Outcome and Stats -->
            <div class="outcome-wrapper">
                <div class="outcome-box">
                    <div class="outcome-title">Last Result</div>
                    <div id="last-outcome">-</div>
                </div>
                <div class="outcome-box">
                    <div class="outcome-title">Game Statistics</div>
                    <div class="stat-row">
                        <div class="stat-item">
                            <div class="stat-label">Player W</div>
                            <div class="stat-value" id="stat-player-wins">0</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-label">Dealer W</div>
                            <div class="stat-value" id="stat-dealer-wins">0</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-label">Push</div>
                            <div class="stat-value" id="stat-pushes">0</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-label">True Count</div>
                            <div class="stat-value" id="stat-true-count">0.00</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Panels go below the fixed recbox -->
            <div class="panel-wrapper">
                <div class="panel" id="player-panel">
                    <div class="panel-title">Player</div>
                    <div id="player-cards" class="card-row"></div>
                </div>

                <div class="panel" id="dealer-panel">
                    <div class="panel-title">Dealer</div>
                    <div id="dealer-status" style="font-size:14px;opacity:0.8;margin-bottom:8px;"></div>
                    <div id="dealer-cards" class="card-row"></div>
                </div>
            </div>


            <script>
                let loading = false;

                setInterval(() => {{
                    if (loading) return;
                    loading = true;

                    let timeout = setTimeout(() => {{
                        loading = false;
                    }}, 200);

                    let img = document.getElementById("frame");
                    let newSrc = "/image?ts=" + new Date().getTime();

                    let tempImage = new Image();
                    tempImage.onload = () => {{
                        clearTimeout(timeout);
                        img.src = newSrc;
                        loading = false;
                    }};
                    tempImage.onerror = () => {{
                        clearTimeout(timeout);
                        loading = false;
                    }};
                    tempImage.src = newSrc;

                }}, 100);

                setInterval(async () => {{
                    try {{
                        let resp = await fetch("/prediction");
                        let data = await resp.json();
                        let rec = data.recommendation || "No prediction";

                        let box = document.getElementById("recbox");
                        box.innerText = rec;

                        box.className = "";
                        let low = rec.toLowerCase();
                        if (low.includes("hit"))   box.classList.add("hit");
                        if (low.includes("stand")) box.classList.add("stand");
                        if (low.includes("double")) box.classList.add("double");
                        if (low.includes("split"))  box.classList.add("split");

                    }} catch (e) {{
                        console.warn("Rec load error:", e);
                    }}
                }}, 300);

                async function updateCards() {{
                    try {{
                        let resp = await fetch("/cards");
                        let data = await resp.json();
                        let pDiv = document.getElementById("player-cards");
                        let dDiv = document.getElementById("dealer-cards");

                        pDiv.innerHTML = "";
                        dDiv.innerHTML = "";

                        function makeCard(code) {{
                            let span = document.createElement("span");
                            span.classList.add("card-pill");

                            if (!code) {{
                                span.innerText = "?";
                                return span;
                            }}

                            code = code.toUpperCase().trim();
                            let value = code.slice(0, -1);
                            let s = code.slice(-1);
                            let symbol = "?";

                            if (s === "S") symbol = "♠";
                            if (s === "C") symbol = "♣";
                            if (s === "H") symbol = "♥";
                            if (s === "D") symbol = "♦";

                            if (s === "H" || s === "D")
                                span.classList.add("card-red");
                            else
                                span.classList.add("card-black");

                            span.innerText = value + symbol;
                            return span;
                        }}

                        // Render split hands with separators
                        (data.hands || []).forEach((hand, idx) => {{
                            let handWrapper = document.createElement('div');
                            handWrapper.style.display = 'flex';
                            handWrapper.style.flexDirection = 'column';
                            handWrapper.style.alignItems = 'center';
                            handWrapper.style.margin = '6px';
                            handWrapper.style.padding = '8px';
                            handWrapper.style.borderRadius = '8px';
                            handWrapper.style.background = hand.is_active ? 'rgba(0,200,0,0.08)' : 'transparent';

                            let title = document.createElement('div');
                            title.innerText = hand.is_active ? 'Hand (active)' : 'Hand';
                            title.style.fontWeight = '600';
                            title.style.marginBottom = '6px';
                            handWrapper.appendChild(title);

                            let row = document.createElement('div');
                            row.style.display = 'flex';
                            row.style.gap = '8px';
                            hand.cards.forEach(c => row.appendChild(makeCard(c)));
                            handWrapper.appendChild(row);

                            pDiv.appendChild(handWrapper);
                        }});

                        // Dealer
                        let dRow = document.createElement('div');
                        dRow.style.display = 'flex';
                        dRow.style.gap = '8px';
                        (data.dealer || []).forEach(c => dRow.appendChild(makeCard(c)));
                        dDiv.appendChild(dRow);

                    }} catch (e) {{
                        console.warn("Cards load error:", e);
                    }}
                }}

                async function updateStats() {{
                    try {{
                        let resp = await fetch("/stats");
                        let data = await resp.json();
                        
                        document.getElementById("stat-player-wins").innerText = data.player_wins || 0;
                        document.getElementById("stat-dealer-wins").innerText = data.dealer_wins || 0;
                        document.getElementById("stat-pushes").innerText = data.pushes || 0;
                        
                        let outcomeDiv = document.getElementById("last-outcome");
                        let outcome = data.last_outcome || "-";
                        outcomeDiv.innerText = outcome;

                        // Update true count if available
                        try {{
                            let tc = (data.counts && data.counts.true_count) ? data.counts.true_count.toFixed(2) : null;
                            if (tc !== null) {{
                                document.getElementById('stat-true-count').innerText = tc;
                            }}
                        }} catch (e) {{}}
                        
                        outcomeDiv.className = "";
                        if (outcome.toLowerCase().includes("player") || outcome.toLowerCase().includes("blackjack")) {{
                            outcomeDiv.classList.add("outcome-win");
                        }} else if (outcome.toLowerCase().includes("dealer")) {{
                            outcomeDiv.classList.add("outcome-loss");
                        }} else if (outcome.toLowerCase().includes("push")) {{
                            outcomeDiv.classList.add("outcome-push");
                        }}
                            // Dealer-phase visual cue
                            try {{
                                let dealerPanel = document.getElementById('dealer-panel');
                                let dealerStatus = document.getElementById('dealer-status');
                                if (data.round_phase && data.round_phase.toLowerCase() === 'dealer') {{
                                    dealerPanel.classList.add('dealer-active');
                                    dealerStatus.innerText = 'Dealer zieht...';
                                }} else if (data.round_phase && data.round_phase.toLowerCase() === 'complete') {{
                                    dealerPanel.classList.remove('dealer-active');
                                    dealerStatus.innerText = data.last_outcome || '';
                                }} else {{
                                    dealerPanel.classList.remove('dealer-active');
                                    dealerStatus.innerText = '';
                                }}
                            }} catch (e) {{
                                // ignore DOM errors
                            }}
                    }} catch (e) {{
                        console.warn("Stats load error:", e);
                    }}
                }}

                setInterval(updateCards, 300);
                setInterval(updateStats, 300);

                async function sendAction(action) {{
                    try {{
                        await fetch('/action', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{ action }})
                        }});
                    }} catch (e) {{
                        console.warn('Action error', e);
                    }}
                }}
            </script>

        </body>
    </html>
    """


@app.route("/image")
def image():
    """Serve latest capture."""
    if os.path.exists(IMAGE_PATH):
        return send_file(IMAGE_PATH, mimetype='image/jpeg')
    return "No image", 404


@app.route("/prediction")
def prediction():
    if os.path.exists(TEXT_PATH):
        return jsonify({"recommendation": open(TEXT_PATH).read()})
    return jsonify({"recommendation": None})


@app.route("/cards")
def cards():
    try:
        sess = postprocessing.session
        hands = []
        for idx, h in enumerate(sess.player_hands):
            hands.append({
                "id": h.id,
                "cards": h.cards,
                "status": h.status,
                # only mark a player hand active during the player phase
                "is_active": (sess.phase == "player" and idx == sess.current_hand_idx),
            })

        dealer_cards = sess.get_dealer_cards()

        # Fallback for split-process setup:
        # websocket.py usually runs in a different process than main.py,
        # so in-memory session can be empty while files still contain cards.
        if not hands:
            player_cards = read_cards_from_file(PLAYER_PATH)
            if player_cards:
                hands = [{
                    "id": 1,
                    "cards": player_cards,
                    "status": "active",
                    "is_active": True,
                }]

        if not dealer_cards:
            dealer_cards = read_cards_from_file(DEALER_PATH)

        return jsonify({
            "hands": hands,
            "dealer": dealer_cards,
            "active_index": sess.current_hand_idx if sess.player_hands else None,
        })
    except Exception as e:
        # Final fallback: serve file-based cards even if session access failed.
        player_cards = read_cards_from_file(PLAYER_PATH)
        dealer_cards = read_cards_from_file(DEALER_PATH)
        hands = []
        if player_cards:
            hands.append({
                "id": 1,
                "cards": player_cards,
                "status": "active",
                "is_active": True,
            })
        return jsonify({"hands": hands, "dealer": dealer_cards, "active_index": 0 if hands else None, "error": str(e)})


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

        return jsonify({
            "player_wins": stats.get("player_wins", 0),
            "dealer_wins": stats.get("dealer_wins", 0),
            "pushes": stats.get("pushes", 0),
            "blackjacks": stats.get("blackjacks", 0),
            "last_outcome": stats.get("last_outcome", None),
            "round_phase": stats.get("round_phase", "unknown"),
            "current_leader": stats.get("current_leader", "unknown"),
            "counts": counts,
        })
    except Exception as e:
        return jsonify({"error": str(e), "player_wins": 0, "dealer_wins": 0, "pushes": 0, "blackjacks": 0, "last_outcome": None})









@app.route("/action", methods=["POST"])
def action():
    try:
        data = request.get_json() or {}
        act = data.get("action")
        if not act:
            return jsonify({"ok": False, "error": "no action"}), 400

        sess = postprocessing.session
        if act == "split":
            idx = sess.current_hand_idx if hasattr(sess, 'current_hand_idx') else 0
            ok = sess.start_split(idx)
            return jsonify({"ok": ok})
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
