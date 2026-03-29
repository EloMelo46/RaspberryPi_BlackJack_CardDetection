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

            <!-- Panels go below the fixed recbox -->
            <div class="panel-wrapper">
                <div class="panel">
                    <div class="panel-title">Player</div>
                    <div id="player-cards" class="card-row"></div>
                </div>

                <div class="panel">
                    <div class="panel-title">Dealer</div>
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

                        (data.player || []).forEach(c => {{
                            pDiv.appendChild(makeCard(c));
                        }});

                        (data.dealer || []).forEach(c => {{
                            dDiv.appendChild(makeCard(c));
                        }});

                    }} catch (e) {{
                        console.warn("Cards load error:", e);
                    }}
                }}

                setInterval(updateCards, 300);
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
