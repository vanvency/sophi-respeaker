#!/usr/bin/env python3
"""LAN dashboard for chunked ReSpeaker capture and local Whisper ASR."""
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, render_template

ROOT = Path(__file__).resolve().parent
RECORDINGS = ROOT / "recordings"
ASR_URL = os.environ.get("ASR_URL", "http://172.17.120.11:32184/v1/audio/transcriptions")
CHUNK_SECONDS = int(os.environ.get("CHUNK_SECONDS", "5"))
DEVICE = "hw:CARD=seeed8micvoicec,DEV=0"

app = Flask(__name__)
state = {"running": False, "lines": [], "error": None}
lock = threading.Lock()

def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def transcribe(wav):
    command = ["curl", "--noproxy", "*", "--fail", "--silent", "--show-error",
               ASR_URL, "-F", f"file=@{wav}", "-F", "model=atom"]
    result = subprocess.run(command, text=True, capture_output=True, timeout=120, check=True)
    return json.loads(result.stdout).get("text", "").strip()

def capture_loop():
    RECORDINGS.mkdir(parents=True, exist_ok=True)
    while True:
        with lock:
            if not state["running"]:
                return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        wav = RECORDINGS / f"chunk-{stamp}.wav"
        try:
            subprocess.run(["arecord", "-D", DEVICE, "-f", "S32_LE", "-r", "48000", "-c", "8",
                            "-d", str(CHUNK_SECONDS), "-t", "wav", str(wav)],
                           text=True, capture_output=True, timeout=CHUNK_SECONDS + 15, check=True)
            text = transcribe(wav)
            if text:
                with lock:
                    state["lines"].append({"time": utcnow(), "text": text, "file": wav.name})
        except Exception as exc:
            with lock:
                state["error"] = str(exc)
            time.sleep(2)

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", chunk_seconds=CHUNK_SECONDS)

@app.route("/api/state", methods=["GET"])
def get_state():
    with lock:
        return jsonify(state)

@app.route("/api/start", methods=["POST"])
def start():
    with lock:
        if not state["running"]:
            state["running"], state["error"] = True, None
            threading.Thread(target=capture_loop, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/stop", methods=["POST"])
def stop():
    with lock:
        state["running"] = False
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
