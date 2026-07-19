# Looper Plan: Teardrop by Massive Attack on MPK Mini

## Context

The existing `trip_hop.py` is a real-time synthesizer with a marimba/vibraphone synth and 8 drum sounds already tuned for Massive Attack's "Teardrop" (trip-hop style). It has no looping capability — everything is live-only. This plan adds a **4-layer MIDI looper** controlled entirely from the MPK Mini's Bank B pads, enabling a full Teardrop performance without touching the computer.

---

## Song Analysis: Teardrop (93 BPM, D minor, 4/4)

Four layers to build live, one per loop pass:

| Layer | Part | Instrument | MPK Control |
|-------|------|-----------|-------------|
| L1 | Drum pattern (kick/snare/hi-hat) | Bank A pads | Record via B1 |
| L2 | Bass line (low D, F, A root notes) | Keys left hand | Record via B2 |
| L3 | Iconic marimba melody | Keys right hand | Record via B3 |
| L4 | Chord stabs / atmosphere | Keys both | Record via B4 |

**Loop grid**: 4 bars × 4 beats × 93 BPM = 10.322s per loop. All layers quantize to this shared grid.

---

## MPK Mini Control Scheme

### Bank A pads (notes 36–43) — unchanged, drums
```
Pad 1: Kick     Pad 2: Snare    Pad 3: Hi-hat cl  Pad 4: Hi-hat op
Pad 5: Tamb     Pad 6: Rim      Pad 7: Ghost snare Pad 8: Shaker
```

### Bank B pads (notes 44–51) — looper control (currently mapped to drums, will be freed)
```
Pad B1 (44): Layer 1 — tap to arm/overdub, hold 1s to clear
Pad B2 (45): Layer 2 — tap to arm/overdub, hold 1s to clear
Pad B3 (46): Layer 3 — tap to arm/overdub, hold 1s to clear
Pad B4 (47): Layer 4 — tap to arm/overdub, hold 1s to clear
Pad B5–B7:   (reserved for future use)
Pad B8 (51): Toggle metronome click on/off
```

### Knobs (unchanged)
K1=vol, K2=LP cutoff, K3=Q, K4=reverb, K5=release, K6=detune, K7=drive, K8=bit-crush

---

## UX Flow (Teardrop performance)

```
1. Run:  python trip_hop.py
         → metronome click starts at 93 BPM immediately
         → terminal shows: Bar1[●···]  L1:[ ]  L2:[ ]  L3:[ ]  L4:[ ]

2. Press B1  → 1-bar count-in, then 4 bars auto-record drums
              (software auto-stops recording after exactly 4 bars)
              → loop starts playing automatically

3. Press B2  → 1-bar count-in, then 4 bars auto-record bass
              → bass loops in sync with drums

4. Press B3  → record Teardrop marimba melody for 4 bars
              → all 3 layers play together = Teardrop!

5. Press B4  → add chord layer

6. Tap same pad again  → overdub (add notes to existing layer)
   Tap again           → stop overdub, keep playing

7. Hold any Bn ≥ 1s   → clear that layer (sends all-notes-off first)

8. Pad B8              → toggle metronome click off when performing
```

---

## Architecture

### Timing (drift-free)
- `_t_epoch = time.perf_counter()` set once at startup, never changes
- All positions computed as `(now - _t_epoch) % _LOOP_LEN`
- No accumulated deltas → no drift over long sessions
- 1ms poll jitter (~0.12ms avg) is 0.47% of a beat — acceptable for live performance

### Thread model
```
main thread      → sd.OutputStream (owns audio callback _audio_cb)
MIDI thread      → for msg in port:
                   → musical events → process_midi_message() → _drum_pending / _notes_pending
                   →               → _looper.on_midi_event() → layer.events
                   → Bank B pads   → _looper.on_pad_press/release()
looper-pb thread → _process() every 1ms:
                   → fires due events → process_midi_message()
                   → fires metronome → _add_drum()
                   → updates terminal display
```

**Lock ordering** (never inverted): `_looper._lock` → release → acquire `_drum_lock` or `_notes_lock`

### Layer state machine
```
EMPTY ---(tap pad)--→ COUNTING (waits for next bar boundary)
                           ↓ auto (rec_start reached)
                       RECORDING (exactly 4 bars, abs timer)
                           ↓ auto (rec_end reached)
         ←------------ PLAYING ←→ OVERDUBBING (tap pad toggles)
         |              (any state + hold ≥1s on release → EMPTY + all-notes-off)
```

---

## Implementation

### Step 1 — Imports and constants (after line 27)
Add `import time` to existing imports.

After the `S = {...}` block (~line 46), add:
```python
_BPM           = 93
_BEAT_DUR      = 60.0 / _BPM       # 0.64516…s
_BAR_DUR       = 4 * _BEAT_DUR     # 2.58065…s
_LOOP_BARS     = 4
_LOOP_LEN      = _LOOP_BARS * _BAR_DUR  # 10.32258…s
_COUNT_IN_BARS = 1
_LONG_PRESS    = 1.0               # s hold to clear layer
_BANK_B_BASE   = 44               # Bank B pads start at note 44
_LOOPER_PADS   = 4                # pads 44-47 → layers 0-3
_METRO_PAD     = 51               # pad B8 → toggle metronome
```

### Step 2 — New classes after `_shaker()` (~line 311, before `_DFNS`)
Insert `LayerState` (Enum), `LoopEvent` (dataclass), `MidiLayer`, and `MidiLooper` classes.

**Key MidiLooper methods:**
- `on_pad_press(layer_idx, now)` — EMPTY→COUNTING, PLAYING↔OVERDUBBING
- `on_pad_release(layer_idx, now)` — long-press (≥1s) → clear + notes-off
- `on_midi_event(msg_type, note, vel, now)` — records into all RECORDING/OVERDUBBING layers
- `toggle_metronome()` — flips `_metro_on` flag
- `_run()` — 1ms poll thread: fires events, manages COUNTING→RECORDING→PLAYING transitions, drives metronome and terminal display

**`_arm_layer` logic** (called on pad press when EMPTY):
```python
bars_done = int((now - _t_epoch) / _BAR_DUR)
layer.rec_start = _t_epoch + (bars_done + 1 + _COUNT_IN_BARS) * _BAR_DUR
layer.rec_end   = layer.rec_start + _LOOP_LEN
layer.state     = LayerState.COUNTING
```
This snaps rec_start to the next bar boundary + 1 count-in bar, so all layers share the same 4-bar grid regardless of when their pad was pressed.

**Event windowed playback** (inside `_process`):
```python
pos0 = e0 % _LOOP_LEN  # cursor before this tick
pos1 = e1 % _LOOP_LEN  # cursor after this tick
wrapped = pos1 < pos0  # loop boundary crossed?

for ev in layer.events:
    if wrapped:
        due = ev.offset > pos0 or ev.offset <= pos1
    else:
        due = pos0 < ev.offset <= pos1
    if due:
        events_to_fire.append(ev)
```

### Step 3 — Metronome click synthesis (after new classes)
```python
def _make_click_buf(freq, amp):
    t   = np.arange(int(SR * 0.015)) / SR   # 15ms
    return _st(np.sin(2 * np.pi * freq * t) * np.exp(-t * 250) * amp)

_CLICK_BUF   = None   # off-beat, initialized in main()
_ACCENT_BUF  = None   # beat 1 accent, initialized in main()
_looper      = None
```

### Step 4 — `process_midi_message()` (central dispatcher, after click declarations)
Both live MIDI thread and looper playback thread call this:
```python
def process_midi_message(msg_type, note, velocity):
    if msg_type == "note_on" and velocity > 0:
        idx = _DMAP.get(note)
        if idx is not None:
            _add_drum(_DCACHE[idx] * (velocity / 127.0))
        else:
            with _notes_lock:
                _notes_pending.append((note, velocity))
    else:
        if _DMAP.get(note) is None:
            with _notes_lock:
                _notes_off.append(note)
```

### Step 5 — Modify `_rebuild_dmap()` (line 317)
Remove the Bank B line so notes 44–51 become looper controls:
```python
# Remove this line:
_DMAP[note + 8] = i   # Bank B
```

### Step 6 — Rewrite `_midi_loop()` (line 413)
Route Bank B pads (notes 44–51) to looper; route all musical events through `process_midi_message()` + `_looper.on_midi_event()`. Capture timestamp with `time.perf_counter()` immediately on each message.

Key routing:
```python
if _BANK_B_BASE <= msg.note < _BANK_B_BASE + 8:
    pad = msg.note - _BANK_B_BASE
    if pad < _LOOPER_PADS:
        _looper.on_pad_press(pad, now)   # on note_on
        _looper.on_pad_release(pad, now)  # on note_off
    elif msg.note == _METRO_PAD and msg.type == "note_on":
        _looper.toggle_metronome()
else:
    process_midi_message(...)
    _looper.on_midi_event(...)
```

### Step 7 — Modify `main()` (line 438)
Initialize click buffers and looper before starting MIDI thread, add startup UI text:
```python
global _CLICK_BUF, _ACCENT_BUF, _looper
_CLICK_BUF  = _make_click_buf(1000, 0.28)
_ACCENT_BUF = _make_click_buf(1500, 0.48)
_looper = MidiLooper()                    # starts playback thread + metronome

t = threading.Thread(target=_midi_loop, daemon=True)
t.start()
```

---

## Edge Cases

| Case | Handling |
|------|---------|
| Note sustaining when layer cleared | `MidiLayer.active_notes()` scans events for unpaired note_on; injects all into `_notes_off` before clearing |
| Drum note_off not needed | `on_midi_event` skips note_off for drum notes (one-shot buffers) |
| Note held across loop boundary | Stored at offset ~9.9s, note_off at ~0.3s; `wrapped=True` branch fires correctly |
| Two layers recording simultaneously | Both capture same events (user avoids by pressing one pad at a time) |
| `_looper` not initialized when MIDI starts | Created in `main()` before `t.start()` — no race |
| Long-press during COUNTING | `clear()` resets to EMPTY, aborting the pending recording |
| Shutdown / Ctrl+C | `_looper.stop()` → `_running=False` → all-notes-off for every active layer |

---

## Files to Modify

- **`/home/micha/dev/midi/trip_hop.py`** — all changes here, ~280 new lines, ~30 modified lines
- **`/home/micha/dev/midi/PLAN_LOOPER.md`** — this file

No new Python files needed. `requirements.txt` unchanged (all libraries already present).

---

## Verification

1. **Start**: `cd /home/micha/dev/midi && source .venv/bin/activate && python trip_hop.py`
   - Hear metronome click at 93 BPM immediately
   - Terminal shows `Bar1[●···]  L1:[ ]  L2:[ ]  L3:[ ]  L4:[ ]`

2. **Drum loop**: Press B1 → hear 1-bar count-in → play kick/snare/hi-hat → after 4 bars, drums loop automatically

3. **Bass layer**: Press B2 → play low D/F/A notes on keys → bass loops in sync with drums

4. **Melody layer**: Press B3 → play Teardrop marimba melody → all 3 layers sound together

5. **Overdub**: Tap B1 again → add more drum hits → tap again → overdub stops

6. **Clear**: Hold B1 for >1 second → drum layer stops, no stuck notes

7. **Metronome off**: Tap B8 → click stops (for clean recording/performance)
