#!/usr/bin/env python3
"""LAN dashboard for chunked ReSpeaker capture and local Whisper ASR."""
import json
import math
import os
import queue
import subprocess
import threading
import time
import wave
from array import array
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, render_template
from respeaker_io import ReSpeakerIO

ROOT = Path(__file__).resolve().parent
RECORDINGS = ROOT / "recordings"
ASR_URL = os.environ.get("ASR_URL", "http://172.17.120.11:32184/v1/audio/transcriptions")
CHUNK_SECONDS = int(os.environ.get("CHUNK_SECONDS", "5"))
DEVICE = "hw:CARD=seeed8micvoicec,DEV=0"
SAMPLE_RATE = 48000
CHANNELS = 8
SAMPLE_WIDTH = 4
LIVE_WINDOW_SECONDS = 0.10
PCM_FULL_SCALE = 2 ** 31
DIRECTION_MIN_DBFS = float(os.environ.get("DIRECTION_MIN_DBFS", "-50"))
DIRECTION_MIN_RMS = PCM_FULL_SCALE * (10 ** (DIRECTION_MIN_DBFS / 20))

app = Flask(__name__)
state = {"running": False, "lines": [], "error": None,
         "asr": {"endpoint": ASR_URL, "queue": 0, "in_flight": None,
                 "completed": 0, "failed": 0, "last": None},
         "direction": {"available": False, "label": "WAITING", "degree": 0,
                       "confidence": 0.0, "source": "energy_estimate", "uncertain": True},
         "live": {"updated": None, "levels": [0.0] * 6,
                  "direction": {"available": False, "label": "WAITING", "degree": 0,
                                "confidence": 0.0, "source": "energy_estimate", "uncertain": True}},
         "events": []}
lock = threading.Lock()
io = None
asr_queue = queue.Queue()
prepare_queue = queue.Queue()
capture_process = None
capture_process_lock = threading.Lock()

DIRECTION_LABELS = ("N", "NE", "SE", "S", "SW", "NW")


def estimate_direction(energies):
    """Map six microphone RMS values to a coarse 360-degree sound sector."""
    if len(energies) != 6:
        raise ValueError("expected RMS energy for six microphones")
    peak = max(energies)
    index = energies.index(peak)
    others = (sum(energies) - peak) / 5
    confidence = round(max(0.0, 1.0 - (others / peak)), 3) if peak else 0.0
    return {"available": True, "degree": index * 60, "label": DIRECTION_LABELS[index],
            "confidence": confidence, "uncertain": confidence < 0.10,
            "source": "energy_estimate"}


def direction_with_sound_gate(energies):
    """Mark sub-speech-floor input as directionally unknown, regardless of channel bias."""
    direction = estimate_direction(energies)
    peak = max(energies)
    level_dbfs = 20 * math.log10(peak / PCM_FULL_SCALE) if peak else float("-inf")
    direction["level_dbfs"] = round(level_dbfs, 1) if peak else None
    if peak < DIRECTION_MIN_RMS:
        direction["uncertain"] = True
        direction["reason"] = "silence"
    else:
        direction["reason"] = "ambiguous" if direction["uncertain"] else "directional"
    return direction


def live_audio_snapshot(pcm, channels=8):
    """Calculate six normalized levels and a direction from raw S32_LE PCM."""
    samples = array("i")
    samples.frombytes(pcm)
    energies = []
    for channel in range(6):
        values = samples[channel::channels]
        energies.append(math.sqrt(sum(value * value for value in values) / len(values)) if values else 0.0)
    peak = max(energies)
    direction = direction_with_sound_gate(energies)
    levels = [round(value / peak, 3) if peak else 0.0 for value in energies]
    direction["levels"] = levels
    return {"levels": levels, "direction": direction}


def pulse_capture_sources(source_list):
    """Return PulseAudio source indexes that own the ReSpeaker multichannel input."""
    return [line.split("\t", 1)[0] for line in source_list.splitlines()
            if "platform-soc_sound.multichannel-input" in line]


def release_capture_device():
    """Suspend PulseAudio's ReSpeaker input so ALSA can own the hardware stream."""
    try:
        listing = subprocess.run(["pactl", "list", "short", "sources"], text=True,
                                 capture_output=True, timeout=3, check=True)
        for source in pulse_capture_sources(listing.stdout):
            subprocess.run(["pactl", "suspend-source", source, "1"], text=True,
                           capture_output=True, timeout=3, check=False)
    except (FileNotFoundError, subprocess.SubprocessError):
        pass


def arecord_command():
    """Return the low-latency raw capture command for the ReSpeaker ALSA device."""
    return ["arecord", "-D", DEVICE, "-f", "S32_LE", "-r", str(SAMPLE_RATE),
            "-c", str(CHANNELS), "--period-time=50000", "--buffer-time=250000", "-t", "raw"]


def wav_direction(wav_path):
    """Estimate direction from decimated RMS samples of channels 1–6 in an S32 WAV."""
    with wave.open(str(wav_path), "rb") as input_wav:
        if input_wav.getnchannels() < 6 or input_wav.getsampwidth() != 4:
            raise ValueError("direction estimate requires at least six 32-bit PCM channels")
        channels = input_wav.getnchannels()
        samples = array("i")
        samples.frombytes(input_wav.readframes(input_wav.getnframes()))
    stride = channels * 64
    energies = []
    for channel in range(6):
        values = samples[channel::stride]
        if not values:
            raise ValueError("captured WAV has no audio samples")
        energies.append(math.sqrt(sum(value * value for value in values) / len(values)))
    direction = direction_with_sound_gate(energies)
    direction["levels"] = [round(value / max(energies), 3) if max(energies) else 0 for value in energies]
    return direction


def show_direction(direction):
    """Render every live direction update on the physical LED ring."""
    if io and direction.get("available"):
        io.direction(direction["degree"], direction.get("uncertain", True))


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
        raw_wav, asr_wav, queued_at, pipeline_started, direction = asr_queue.get()
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
                    state["lines"].append({"time": report["finished"], "text": text,
                                           "file": raw_wav.name, "direction": direction})
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


def prepare_worker():
    """Convert complete PCM windows while the capture stream continues uninterrupted."""
    while True:
        raw_wav, pipeline_started, direction = prepare_queue.get()
        clip = raw_wav.name
        try:
            convert_started = time.monotonic()
            event(clip, "audio_prepare", "started", target="mono/16kHz/s16")
            asr_wav = make_asr_audio(raw_wav)
            event(clip, "audio_prepare", "ok", duration_s=round(time.monotonic()-convert_started, 3), bytes=asr_wav.stat().st_size)
            queued_at = time.monotonic()
            asr_queue.put((raw_wav, asr_wav, queued_at, pipeline_started, direction))
            with lock:
                state["asr"]["queue"] = asr_queue.qsize()
            event(clip, "asr_queue", "queued", depth=asr_queue.qsize())
        except Exception as exc:
            with lock:
                state["error"] = str(exc)
            event(clip, "audio_prepare", "failed", error=str(exc))
        finally:
            prepare_queue.task_done()

def make_asr_audio(raw_wav):
    """Create a speech-focused mono file from the six ReSpeaker microphones."""
    output = raw_wav.with_name(raw_wav.stem + "-asr.wav")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(raw_wav),
        "-filter_complex", asr_audio_filter(),
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(output),
    ], text=True, capture_output=True, timeout=30, check=True)
    return output


def asr_audio_filter():
    """Mix the six microphones, retain speech frequencies, and suppress stationary noise."""
    return ("pan=mono|c0=0.1667*c0+0.1667*c1+0.1667*c2+0.1667*c3+0.1667*c4+0.1667*c5,"
            "highpass=f=90,lowpass=f=7600,afftdn=nr=18:nf=-45:tn=1:tr=1,"
            "dynaudnorm=f=150:g=7:p=0.95")

def write_pcm_wav(wav_path, pcm):
    with wave.open(str(wav_path), "wb") as output_wav:
        output_wav.setnchannels(CHANNELS)
        output_wav.setsampwidth(SAMPLE_WIDTH)
        output_wav.setframerate(SAMPLE_RATE)
        output_wav.writeframes(pcm)


def capture_loop():
    """Read one continuous raw PCM stream for live meters and fixed ASR windows."""
    RECORDINGS.mkdir(parents=True, exist_ok=True)
    frame_bytes = CHANNELS * SAMPLE_WIDTH
    chunk_bytes = SAMPLE_RATE * frame_bytes * CHUNK_SECONDS
    live_bytes = int(SAMPLE_RATE * frame_bytes * LIVE_WINDOW_SECONDS)
    read_bytes = int(SAMPLE_RATE * frame_bytes * 0.10)
    pending, live_pcm = bytearray(), bytearray()
    capture_started = time.monotonic()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    clip = f"chunk-{stamp}.wav"
    event(clip, "capture", "started", device=DEVICE, channels=CHANNELS, sample_rate=SAMPLE_RATE)
    global capture_process
    process = None
    try:
        io.recording()
        release_capture_device()
        process = subprocess.Popen(arecord_command(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        with capture_process_lock:
            capture_process = process
        while True:
            with lock:
                running = state["running"]
            if not running:
                break
            pcm = process.stdout.read(read_bytes)
            if not pcm:
                error = process.stderr.read().decode(errors="replace").strip() or "arecord stream ended"
                raise RuntimeError(error)
            pending.extend(pcm)
            live_pcm.extend(pcm)
            if len(live_pcm) >= live_bytes:
                live_pcm = live_pcm[-live_bytes:]
                snapshot = live_audio_snapshot(live_pcm)
                direction = snapshot["direction"]
                with lock:
                    state["live"] = {"updated": utcnow(), **snapshot}
                    state["direction"] = direction
                show_direction(direction)
            while len(pending) >= chunk_bytes:
                chunk = bytes(pending[:chunk_bytes])
                del pending[:chunk_bytes]
                wav = RECORDINGS / clip
                write_pcm_wav(wav, chunk)
                with lock:
                    direction = state["live"]["direction"]
                event(clip, "capture", "ok", duration_s=round(time.monotonic()-capture_started, 3),
                      bytes=wav.stat().st_size, direction=direction)
                prepare_queue.put((wav, capture_started, direction))
                capture_started = time.monotonic()
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                clip = f"chunk-{stamp}.wav"
                event(clip, "capture", "started", device=DEVICE, channels=CHANNELS, sample_rate=SAMPLE_RATE)
    except Exception as exc:
        with lock:
            state["error"] = str(exc)
        io.error()
        event(clip, "pipeline", "failed", error=str(exc))
    finally:
        if process:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        with capture_process_lock:
            if capture_process is process:
                capture_process = None

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
    with capture_process_lock:
        process = capture_process
    if process and process.poll() is None:
        process.terminate()
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
    threading.Thread(target=prepare_worker, daemon=True, name="audio-prepare-worker").start()
    threading.Thread(target=asr_worker, daemon=True, name="asr-worker").start()
    app.run(host="0.0.0.0", port=8080, threaded=True)
