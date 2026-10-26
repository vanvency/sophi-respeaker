# Dashboard Direction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Place live monitoring and transcription in separate columns and expose an approximate ReSpeaker sound direction for every captured clip.

**Architecture:** `app.py` will calculate an RMS-energy direction from the six microphone channels after each capture. It will store the result in trace events and transcript records. `templates/index.html` will render a responsive two-column dashboard, a compass for current direction, and direction metadata beside each transcript line.

**Tech Stack:** Python 3 standard library (`wave`, `audioop`), Flask, HTML/CSS/JavaScript.

---

### Task 1: Direction estimator

**Files:**
- Create: `tests/test_direction.py`
- Modify: `app.py`

- [ ] **Step 1: Write the failing tests**

```python
from app import estimate_direction

def test_estimate_direction_identifies_dominant_channel():
    result = estimate_direction([1, 1, 1, 1, 100, 1])
    assert result["degree"] == 240
    assert result["confidence"] > 0.9

def test_estimate_direction_marks_even_energy_uncertain():
    result = estimate_direction([10, 10, 10, 10, 10, 10])
    assert result["uncertain"] is True
```

- [ ] **Step 2: Run the tests to verify failure**

Run: `python3 -m unittest tests.test_direction -v`

Expected: import failure because `estimate_direction` does not exist.

- [ ] **Step 3: Implement the estimator**

```python
def estimate_direction(energies):
    peak = max(energies)
    baseline = sum(energies) / len(energies)
    confidence = round(max(0.0, 1 - baseline / peak), 3) if peak else 0.0
    index = energies.index(peak)
    return {"degree": index * 60, "confidence": confidence,
            "uncertain": confidence < 0.10, "source": "energy_estimate"}
```

- [ ] **Step 4: Run tests to verify success**

Run: `python3 -m unittest tests.test_direction -v`

Expected: 2 tests pass.

### Task 2: Capture metadata and responsive dashboard

**Files:**
- Modify: `app.py`
- Modify: `templates/index.html`

- [ ] **Step 1: Add direction metadata after capture**

Read six-channel WAV data with `wave` and `audioop.rms`, call `estimate_direction`, and include the returned fields in the `capture / ok` trace event and each ASR transcript record.

- [ ] **Step 2: Render the two-column dashboard**

Create `#monitoring` and `#transcript` sections in a CSS grid. Use a circular compass whose arrow rotates to `direction.degree`; display cardinal/clock-face label, degree, confidence, estimate source, and an uncertain state.

- [ ] **Step 3: Verify syntax and browser output**

Run: `python3 -m py_compile app.py respeaker_io.py`

Run: `curl --fail --silent http://127.0.0.1:8080/ | grep -o 'SOUND DIRECTION'`

Expected: Python compiles and the dashboard contains the direction panel.

### Task 3: Integration verification and commit

**Files:**
- Modify: `app.py`
- Modify: `templates/index.html`
- Create: `tests/test_direction.py`

- [ ] **Step 1: Run all direction tests**

Run: `python3 -m unittest discover -v`

Expected: all tests pass.

- [ ] **Step 2: Capture one live chunk and inspect state**

Run start API, wait 8 seconds, then fetch `/api/state`. Confirm a `capture / ok` event contains `direction` and a transcript line contains the same metadata.

- [ ] **Step 3: Commit and push**

```bash
git add app.py templates/index.html tests docs
git commit -m "Add dashboard sound direction display"
git push -u origin feature/dashboard-direction
```
