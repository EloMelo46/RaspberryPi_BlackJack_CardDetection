from flask import Flask, send_file, jsonify
import os

app = Flask(__name__)

IMAGE_PATH = "latest.jpg"
TEXT_PATH = "latest.txt"


@app.route("/")
def index():
    return f"""
    <html>
        <head>
            <title>Blackjack Vision</title>

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
            </style>

        </head>

        <body>

            <h1>Blackjack Vision</h1>

            <!-- Bild -->
            <img id="frame" width="90%" src="/image">

            <!-- Recommendation Box -->
            <div id="recbox" class="rec-box">
                {open(TEXT_PATH).read() if os.path.exists(TEXT_PATH) else "No prediction"}
            </div>

            <!-- ============================
                 JavaScript (deine Logik + Anti-Hänger Fix)
            ============================ -->
            <script>
                let loading = false;

                // --- Bild Reload (identische Logik, aber mit Timeout-Fix) ---
                setInterval(() => {{
                    if (loading) return;
                    loading = true;

                    // Timeout verhindert Freeze
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

                }}, 100);  // 10 FPS


                // --- Empfehlung Reload ---
                setInterval(async () => {{
                    try {{
                        let resp = await fetch("/prediction");
                        let data = await resp.json();
                        let rec = data.recommendation || "No prediction";

                        let box = document.getElementById("recbox");
                        box.innerText = rec;

                        // Reset styles
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
