from flask import Flask, send_file, jsonify
import os

app = Flask(__name__)

IMAGE_PATH = "latest.jpg"
TEXT_PATH = "latest.txt"
PLAYER_PATH = "player_cards.txt"
DEALER_PATH = "dealer_cards.txt"


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
                    font-size: 32px;
                    font-weight: 300;
                    margin-bottom: 20px;
                }}

                #frame {{
                    width: 92%;
                    max-width: 900px;
                    border-radius: 12px;
                    box-shadow: 0 0 22px rgba(0, 255, 255, 0.15);
                    margin-bottom: 25px;
                }}

                .rec-box {{
                    margin: 20px auto;
                    padding: 18px;
                    width: 80%;
                    max-width: 420px;
                    border-radius: 12px;
                    font-size: 26px;
                    font-weight: bold;
                    background: #1a1a1a;
                    color: #ffffff;
                    transition: 0.25s ease-in-out;
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

                .cards-container {{
                    display: flex;
                    justify-content: center;
                    gap: 40px;
                    margin-top: 10px;
                    margin-bottom: 10px;
                    flex-wrap: wrap;
                }}

                .cards-column {{
                    min-width: 140px;
                }}

                .cards-column h3 {{
                    margin-bottom: 8px;
                    font-weight: 400;
                    color: #ccc;
                }}

                .card-row {{
                    display: flex;
                    justify-content: center;
                    flex-wrap: wrap;
                    gap: 8px;
                }}

                .card-pill {{
                    padding: 6px 10px;
                    border-radius: 6px;
                    background: #1e1e1e;
                    font-size: 18px;
                    min-width: 36px;
                    text-align: center;
                    box-shadow: 0 0 8px rgba(0,0,0,0.5);
                }}

                .card-black {{
                    color: #ffffff;
                }}

                .card-red {{
                    color: #ff4b4b;
                }}
            </style>

        </head>

        <body>

            <h1>Blackjack Basic Strategy</h1>

            <!-- Live-Bild -->
            <img id="frame" width="90%" src="/image">

            <!-- Panels für Player / Dealer -->
            <div class="cards-container">
                <div class="cards-column">
                    <h3>Player</h3>
                    <div id="player-cards" class="card-row"></div>
                </div>
                <div class="cards-column">
                    <h3>Dealer</h3>
                    <div id="dealer-cards" class="card-row"></div>
                </div>
            </div>

            <!-- Recommendation Box -->
            <div id="recbox" class="rec-box">
                {open(TEXT_PATH).read() if os.path.exists(TEXT_PATH) else "No prediction"}
            </div>

            <!-- ============================
                 JavaScript: Reload Bild, Rec, Cards
            ============================ -->
            <script>
                let loading = false;

                // --- Bild Reload (deine Logik + Timeout-Fix gegen Hänger) ---
                setInterval(() => {{
                    if (loading) return;
                    loading = true;

                    let timeout = setTimeout(() => {{
                        loading = false;
                    }}, 200); // 200ms Safety

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

                }}, 100);  // 10 FPS


                // --- Recommendation Reload + Farb-Logik ---
                setInterval(async () => {{
                    try {{
                        let resp = await fetch("/prediction");
                        let data = await resp.json();
                        let rec = data.recommendation || "No prediction";

                        let box = document.getElementById("recbox");
                        box.innerText = rec;

                        box.className = "rec-box";

                        let low = rec.toLowerCase();
                        if (low.includes("hit")) box.classList.add("hit");
                        if (low.includes("stand")) box.classList.add("stand");
                        if (low.includes("double")) box.classList.add("double");
                        if (low.includes("split")) box.classList.add("split");

                    }} catch (e) {{
                        console.warn("Rec load error:", e);
                    }}
                }}, 300);


                // --- Cards Reload (Player & Dealer) ---
                async function updateCards() {{
                    try {{
                        let resp = await fetch("/cards");
                        let data = await resp.json();

                        let pDiv = document.getElementById("player-cards");
                        let dDiv = document.getElementById("dealer-cards");

                        pDiv.innerHTML = "";
                        dDiv.innerHTML = "";

                        function createCardSpan(code) {{
                            let span = document.createElement("span");
                            span.classList.add("card-pill");

                            if (!code) {{
                                span.innerText = "?";
                                return span;
                            }}

                            code = code.toUpperCase().trim();  // z.B. "AS", "10H"
                            let value = code.slice(0, -1);
                            let suitLetter = code.slice(-1);
                            let suitSymbol = "?";

                            if (suitLetter === "S") suitSymbol = "♠";
                            if (suitLetter === "C") suitSymbol = "♣";
                            if (suitLetter === "H") suitSymbol = "♥";
                            if (suitLetter === "D") suitSymbol = "♦";

                            // Farbe nach Suit
                            if (suitLetter === "H" || suitLetter === "D") {{
                                span.classList.add("card-red");
                            }} else {{
                                span.classList.add("card-black");
                            }}

                            span.innerText = value + suitSymbol;
                            return span;
                        }}

                        (data.player || []).forEach(c => {{
                            pDiv.appendChild(createCardSpan(c));
                        }});

                        (data.dealer || []).forEach(c => {{
                            dDiv.appendChild(createCardSpan(c));
                        }});

                    }} catch (e) {{
                        console.warn("Cards load error:", e);
                    }}
                }}

                setInterval(updateCards, 300);  // 3–4x pro Sekunde Karten aktualisieren

            </script>

        </body>
    </html>
    """


@app.route("/image")
def image():
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
    def read_cards(path):
        if os.path.exists(path):
            return open(path).read().strip().split()
        return []

    return jsonify({
        "player": read_cards(PLAYER_PATH),
        "dealer": read_cards(DEALER_PATH)
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
