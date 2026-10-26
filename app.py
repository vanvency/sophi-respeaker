#!/usr/bin/env python3
"""LAN dashboard for chunked ReSpeaker capture and local Whisper ASR."""
import json
import os
import queue
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, render_template
from respeaker_io import ReSpeakerIO

ROOT = Path(__file__).resolve().parent
RECORDINGS = ROOT / "recordings"
ASR_URL = os.environ.get("ASR_URL", "http://172.17.120.11:32184/v1/audio/transcriptions")
CHUNK_SECONDS = int(os.environ.get("CHUNK_SECONDS", "5"))
DEVICE = "hw:CARD=seeed8micvoicec,DEV=0"

app = Flask(__name__)
state = {"running": False, "lines": [], "error": None,
         "asr": {"endpoint": ASR_URL, "queue": 0, "in_flight": None,
                 "completed": 0, "failed": 0, "last": None},
         "events": []}
lock = threading.Lock()
io = None
asr_queue = queue.Queue()

def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def event(clip, stage, status="ok", **details):
    """Append a bounded, browser-visible trace event for one audio clip."""
    entry = {"time": utcnow(), "clip": clip, "stage": stage, "status": status, **details}
    with lock:
        state["events"].append(entry)
        state["events"] = state["events"][-100:]
    return entry

def transcribe(wav):
    command = ["curl", "--noproxy", "*", "--fail", "--silent", "--show-error",
               ASR_URL, "-F", f"file=@{wav}", "-F", "model=atom"]
    result = subprocess.run(command, text=True, capture_output=True, timeout=120, check=True)
    return json.loads(result.stdout).get("text", "").strip()

def asr_worker():
    """Consume prepared clips without ever blocking the microphone loop."""
    while True:
        raw_wav, asr_wav, queued_at, pipeline_started = asr_queue.get()
        clip = raw_wav.name
        started = time.monotonic()
        with lock:
            state["asr"]["queue"] = asr_queue.qsize()
            state["asr"]["in_flight"] = {"file": clip, "started": utcnow()}
        event(clip, "asr_request", "started", queue_wait_s=round(started-queued_at, 3), endpoint=ASR_URL)
        try:
            io.transcribing()
            text = transcribe(asr_wav)
            elapsed = round(time.monotonic() - started, 3)
            report = {"file": raw_wav.name, "status": "ok", "finished": utcnow(),
                      "latency_s": elapsed, "audio_s": CHUNK_SECONDS,
                      "rtf": round(elapsed / CHUNK_SECONDS, 3),
                      "end_to_end_s": round(time.monotonic() - pipeline_started, 3), "text": text}
            with lock:
                state["asr"]["completed"] += 1
                state["asr"]["last"] = report
                if text:
                    state["lines"].append({"time": report["finished"], "text": text, "file": raw_wav.name})
            event(clip, "asr_request", "ok", latency_s=elapsed, rtf=report["rtf"],
                  end_to_end_s=report["end_to_end_s"], chars=len(text))
        except Exception as exc:
            with lock:
                state["asr"]["failed"] += 1
                state["error"] = str(exc)
                state["asr"]["last"] = {"file": raw_wav.name, "status": "failed", "finished": utcnow(), "error": str(exc)}
            io.error()
            event(clip, "asr_request", "failed", end_to_end_s=round(time.monotonic() - pipeline_started, 3), error=str(exc))
        finally:
            with lock:
                state["asr"]["in_flight"] = None
                state["asr"]["queue"] = asr_queue.qsize()
            asr_queue.task_done()

def make_asr_audio(raw_wav):
    """Create a Whisper-friendly mono file from microphone channels 1–6 only."""
    output = raw_wav.with_name(raw_wav.stem + "-asr.wav")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(raw_wav),
        "-filter_complex", "pan=mono|c0=0.1667*c0+0.1667*c1+0.1667*c2+0.1667*c3+0.1667*c4+0.1667*c5",
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(output),
    ], text=True, capture_output=True, timeout=30, check=True)
    return output

def capture_loop():
    RECORDINGS.mkdir(parents=True, exist_ok=True)
    while True:
        with lock:
            if not state["running"]:
                return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        wav = RECORDINGS / f"chunk-{stamp}.wav"
        clip = wav.name
        try:
            io.recording()
            capture_started = time.monotonic()
            event(clip, "capture", "started", device=DEVICE, channels=8, sample_rate=48000)
            subprocess.run(["arecord", "-D", DEVICE, "-f", "S32_LE", "-r", "48000", "-c", "8",
                            "-d", str(CHUNK_SECONDS), "-t", "wav", str(wav)],
                           text=True, capture_output=True, timeout=CHUNK_SECONDS + 15, check=True)
            event(clip, "capture", "ok", duration_s=round(time.monotonic()-capture_started, 3), bytes=wav.stat().st_size)
            convert_started = time.monotonic()
            event(clip, "audio_prepare", "started", target="mono/16kHz/s16")
            asr_wav = make_asr_audio(wav)
            event(clip, "audio_prepare", "ok", duration_s=round(time.monotonic()-convert_started, 3), bytes=asr_wav.stat().st_size)
            queued_at = time.monotonic()
            asr_queue.put((wav, asr_wav, queued_at, capture_started))
            with lock:
                state["asr"]["queue"] = asr_queue.qsize()
            event(clip, "asr_queue", "queued", depth=asr_queue.qsize())
        except Exception as exc:
            with lock:
                state["error"] = str(exc)
            io.error()
            event(clip, "pipeline", "failed", error=str(exc))
            time.sleep(2)
        else:
            io.recording()

def start_listening():
    with lock:
        if state["running"]:
            return False
        state["running"], state["error"] = True, None
        threading.Thread(target=capture_loop, daemon=True).start()
    io.recording()
    return True

def stop_listening():
    with lock:
        state["running"] = False
    io.standby()

def toggle_from_button():
    with lock:
        running = state["running"]
    stop_listening() if running else start_listening()

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", chunk_seconds=CHUNK_SECONDS)

@app.route("/api/state", methods=["GET"])
def get_state():
    with lock:
        return jsonify(state)

@app.route("/api/start", methods=["POST"])
def start():
    start_listening()
    return jsonify({"ok": True})

@app.route("/api/stop", methods=["POST"])
def stop():
    stop_listening()
    return jsonify({"ok": True})

if __name__ == "__main__":
    io = ReSpeakerIO(toggle_from_button)
    io.standby()
    threading.Thread(target=asr_worker, daemon=True, name="asr-worker").start()
    app.run(host="0.0.0.0", port=8080, threaded=True)
