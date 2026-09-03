import os
import subprocess
import time
import webview

project_dir = os.path.dirname(os.path.abspath(__file__))
env = os.environ.copy()
env["BLACKJACK_FLASK_DEBUG"] = "0"

server = subprocess.Popen(
    ["venv_bj/bin/python", "websocket.py"],
    cwd=project_dir,
    env=env,
)

main_process = subprocess.Popen(
    ["venv_bj/bin/python", "main.py"],
    cwd=project_dir
)

time.sleep(2)

try:
    webview.create_window(
        "BlackJack Card Detection",
        "http://192.168.1.65:5000",
        fullscreen=True
    )
    webview.start()
finally:
    for process in (main_process, server):
        process.terminate()
