#!/usr/bin/env python3
"""
AKAI MPK Mini Mk II — Trip Hop Instrument

Knobs: auto-learned — turn each knob once in order K1→K8 at startup.
  K1 = master volume    (affects everything)
  K2 = LP filter cutoff (synth only)
  K3 = resonance        (synth only)
  K4 = reverb wet       (synth only)
  K5 = synth release    (synth only)
  K6 = detune           (synth only)
  K7 = soft drive       (synth only)
  K8 = lofi bit crush   (synth only)

Pads (notes 36-51, any channel):
  1=kick  2=snare  3=hh-closed  4=hh-open  5=tambourine  6=rim  7=ghost-snare  8=shaker

Keys: lofi marimba synth (Teardrop / Massive Attack style)
"""

import json
import threading
from pathlib import Path
import numpy as np
import mido
import sounddevice as sd
from scipy import signal as sp

CC_MAP_FILE = Path(__file__).parent / "cc_map.json"

# ── Config ─────────────────────────────────────────────────────────────────────
SR    = 44100
BLOCK = 128   # ~2.9ms buffer latency

# ── Live parameters ────────────────────────────────────────────────────────────
S = {
    "vol":     0.70,    # K1  master volume (global)
    "cutoff": 3500.0,   # K2  synth LP cutoff Hz
    "q":       0.70,    # K3  synth filter resonance (Q)
    "reverb":  0.28,    # K4  synth reverb wet mix
    "release": 1.00,    # K5  synth decay rate (higher = shorter)
    "detune":  0.004,   # K6  synth oscillator detune ratio
    "drive":   0.00,    # K7  synth soft-clip drive 0-1
    "crush":   0,       # K8  synth bit-crush depth 0-8 (0 = off)
}

# ── Drum voice queue (pre-generated buffers) ───────────────────────────────────
_drum_pending = []
_drum_lock    = threading.Lock()
_drum_active  = []

def _add_drum(buf):
    with _drum_lock:
        _drum_pending.append({"buf": buf.astype(np.float32), "pos": 0})

# ── Real-time synth voices ─────────────────────────────────────────────────────
_synth_voices  = []    # owned exclusively by audio callback
_notes_pending = []    # MIDI thread writes, callback reads
_notes_off     = []    # note numbers to release (fast fade, no hard cut)
_notes_lock    = threading.Lock()

_ATK_SAMP  = int(0.006 * SR)   # 6ms attack
_REL_RATE  = 300.0             # fast release on note_off: ~15ms to silence

# Per-voice warm LP (cutoff * 0.65) — rebuilt alongside global filter
_voice_sos = None

def _make_voice(note, vel):
    f     = 440.0 * 2 ** ((note - 69) / 12)
    n_sec = _voice_sos.shape[0] if _voice_sos is not None else 1
    return {
        "note":   note,
        "f":      f,
        "vel":    vel / 127.0,
        "det":    S["detune"],
        "t":      0,
        "rel_t":  None,          # set to sample-time when note_off received
        "phases": [0.0] * 5,
        "zi_L":   np.zeros((n_sec, 2)),
        "zi_R":   np.zeros((n_sec, 2)),
    }

# ── LP filter (stateful across blocks, synth only) ────────────────────────────
_sos = _ziL = _ziR = None

def _biquad_lp(cutoff, q):
    k    = np.tan(np.pi * float(np.clip(cutoff, 20, SR / 2 - 100)) / SR)
    norm = 1.0 / (1.0 + k / q + k * k)
    b0   = k * k * norm
    b1   = 2.0 * b0
    a1   = 2.0 * (k * k - 1.0) * norm
    a2   = (1.0 - k / q + k * k) * norm
    return np.array([[b0, b1, b0, 1.0, a1, a2]])

def _rebuild_filter():
    global _sos, _ziL, _ziR, _voice_sos
    q   = float(np.clip(S["q"], 0.5, 10.0))
    sos = _biquad_lp(S["cutoff"], q)
    zi  = sp.sosfilt_zi(sos)
    _sos = sos
    _ziL = zi.copy()
    _ziR = zi.copy()
    _voice_sos = _biquad_lp(float(np.clip(S["cutoff"] * 0.65, 150, SR / 2 - 200)), 0.707)

# ── Reverb (two-tap feedback delay, synth only) ────────────────────────────────
_RDEL1 = int(SR * 0.191)
_RDEL2 = int(SR * 0.313)
_RLEN  = _RDEL2 + BLOCK * 8
_rbuf  = np.zeros((_RLEN, 2))
_rptr  = 0

def _reverb(blk):
    global _rptr
    n   = len(blk)
    mix = S["reverb"]
    i   = np.arange(n)
    r1  = (_rptr - _RDEL1 + i) % _RLEN
    r2  = (_rptr - _RDEL2 + i) % _RLEN
    w   = (_rptr           + i) % _RLEN
    d1  = _rbuf[r1]
    d2  = _rbuf[r2]
    out = blk + (d1 * 0.6 + d2 * 0.4) * mix
    _rbuf[w] = blk + d1 * 0.40 + d2 * 0.16
    _rptr = (_rptr + n) % _RLEN
    return out

# ── Real-time synth block ──────────────────────────────────────────────────────
_PARTIALS = [1.0, 2.0, 3.0, 4.0, 0.5]
_WEIGHTS  = [0.50, 0.22, 0.10, 0.05, 0.07]

def _synth_block(frames):
    global _synth_voices

    with _notes_lock:
        releasing = set(_notes_off)
        _notes_off.clear()
        # Retrigger: start fast release on old voice, then add fresh one
        retriggered = {n for n, _ in _notes_pending}
        for v in _synth_voices:
            if v["note"] in releasing or v["note"] in retriggered:
                if v["rel_t"] is None:
                    v["rel_t"] = v["t"]
        for note, vel in _notes_pending:
            _synth_voices.append(_make_voice(note, vel))
        _notes_pending.clear()

    buf   = np.zeros((frames, 2))
    alive = []
    k     = np.arange(frames, dtype=np.float64)

    for v in _synth_voices:
        t_samp = v["t"] + k

        # Envelope: linear attack → exponential decay
        decay_rate = 4.0 / max(S["release"], 0.1)
        env = np.where(
            t_samp < _ATK_SAMP,
            t_samp / _ATK_SAMP,
            np.exp(-decay_rate * (t_samp - _ATK_SAMP) / SR)
        )

        # Fast release on note_off — fades to silence in ~15ms
        if v["rel_t"] is not None:
            rel_samp = v["t"] + k - v["rel_t"]
            env = env * np.exp(-_REL_RATE * rel_samp / SR)

        if env[-1] < 0.0005:
            continue   # voice is inaudible, drop it

        # Oscillator via phase accumulators (no pre-generation)
        f   = v["f"]
        det = S["detune"]   # live knob — applies immediately to all voices
        freqs = [f * p for p in _PARTIALS]
        freqs[1] *= (1 + det)
        freqs[3] *= (1 - det / 2)

        osc_L = np.zeros(frames)
        osc_R = np.zeros(frames)
        for i, (fi, wi) in enumerate(zip(freqs, _WEIGHTS)):
            ph   = v["phases"][i]
            arg  = ph + 2 * np.pi * fi * k / SR
            wave = np.sin(arg) * wi
            osc_L += wave
            # Slight phase offset on 2nd harmonic for stereo width
            osc_R += (np.sin(arg + 0.18) * wi) if i == 1 else wave
            v["phases"][i] = (ph + 2 * np.pi * fi * frames / SR) % (2 * np.pi)

        scale = v["vel"] * 0.55
        aL = osc_L * env * scale
        aR = osc_R * env * scale

        # Per-voice warm LP filter
        if _voice_sos is not None and v["zi_L"] is not None:
            aL, v["zi_L"] = sp.sosfilt(_voice_sos, aL, zi=v["zi_L"])
            aR, v["zi_R"] = sp.sosfilt(_voice_sos, aR, zi=v["zi_R"])

        # Bit crush
        if S["crush"] > 0:
            lvl = 2 ** max(4, 16 - int(S["crush"] * 1.5))
            aL  = np.round(aL * lvl) / lvl
            aR  = np.round(aR * lvl) / lvl

        buf[:, 0] += aL
        buf[:, 1] += aR
        v["t"] += frames
        alive.append(v)

    _synth_voices = alive
    return buf

# ── Audio callback ─────────────────────────────────────────────────────────────
def _audio_cb(outdata, frames, _t, _s):
    global _ziL, _ziR

    # Drums
    with _drum_lock:
        _drum_active.extend(_drum_pending)
        _drum_pending.clear()

    drums = np.zeros((frames, 2), dtype=np.float64)
    nxt   = []
    for v in _drum_active:
        take = min(len(v["buf"]) - v["pos"], frames)
        drums[:take] += v["buf"][v["pos"]: v["pos"] + take]
        v["pos"] += take
        if v["pos"] < len(v["buf"]):
            nxt.append(v)
    _drum_active[:] = nxt

    # Synth (computed in real-time, no pre-generated buffers)
    synths = _synth_block(frames)

    if S["drive"] > 0:
        g      = 1.0 + S["drive"] * 5
        synths = np.tanh(synths * g) / g

    if _sos is not None:
        L, _ziL = sp.sosfilt(_sos, synths[:, 0], zi=_ziL)
        R, _ziR = sp.sosfilt(_sos, synths[:, 1], zi=_ziR)
        synths  = np.column_stack([L, R])

    synths = _reverb(synths)

    out = (drums + synths) * S["vol"]
    np.clip(out, -1.0, 1.0, out=out)
    outdata[:] = out.astype(np.float32)

# ── Drum synthesis ─────────────────────────────────────────────────────────────
def _st(mono, pan=0.0):
    l = mono * (1 - max(pan, 0.0))
    r = mono * (1 + min(pan, 0.0))
    return np.column_stack([l, r]).astype(np.float32)

def _t(s):    return np.arange(int(SR * s)) / SR
def _e(t, r): return np.exp(-r * t)

def _kick(v=127):
    t        = _t(0.65)
    f        = 220 * np.exp(-35 * t) + 45
    osc      = np.sin(2 * np.pi * np.cumsum(f) / SR)
    sub      = np.sin(2 * np.pi * 45 * t) * _e(t, 3) * 0.5
    clk      = _e(t, 300) * 0.8
    snap_len = int(SR * 0.003)
    snap     = np.zeros(len(t))
    snap[:snap_len] = np.random.default_rng(9).standard_normal(snap_len) * _e(t[:snap_len], 800)
    raw = np.tanh((osc * _e(t, 5) + sub + clk + snap * 0.4) * 1.4) * 0.85
    return _st(raw * v / 127)

def _snare(v=127):
    t    = _t(0.20)
    ns   = np.random.default_rng(0).standard_normal(len(t))
    ns   = sp.sosfilt(sp.butter(4, [250, 7000], "bandpass", fs=SR, output="sos"), ns)
    tone = np.sin(2 * np.pi * 200 * t) * _e(t, 50)
    return _st((ns * _e(t, 22) * 0.6 + tone * 0.3) * v / 127)

def _hh_cl(v=127):
    t  = _t(0.06)
    ns = np.random.default_rng(1).standard_normal(len(t))
    ns = sp.sosfilt(sp.butter(4, 10000, "high", fs=SR, output="sos"), ns)
    return _st(ns * _e(t, 100) * 0.28 * v / 127)

def _hh_op(v=127):
    t  = _t(0.35)
    ns = np.random.default_rng(2).standard_normal(len(t))
    ns = sp.sosfilt(sp.butter(4, 8000, "high", fs=SR, output="sos"), ns)
    return _st(ns * _e(t, 9) * 0.26 * v / 127)

def _tambourine(v=127):
    t   = _t(0.30)
    ns  = np.random.default_rng(3).standard_normal(len(t))
    ns  = sp.sosfilt(sp.butter(4, [5000, SR // 2 - 100], "bandpass", fs=SR, output="sos"), ns)
    env = _e(t, 18) * (1 + 0.5 * np.sin(2 * np.pi * 22 * t))
    return _st(ns * env * 0.30 * v / 127)

def _rim(v=127):
    t = _t(0.10)
    return _st((np.sin(2 * np.pi * 1100 * t) + np.sin(2 * np.pi * 780 * t))
               * _e(t, 55) * 0.38 * v / 127)

def _ghost_snare(v=127):
    t  = _t(0.15)
    ns = np.random.default_rng(5).standard_normal(len(t))
    ns = sp.sosfilt(sp.butter(4, [300, 6000], "bandpass", fs=SR, output="sos"), ns)
    return _st(ns * _e(t, 28) * 0.30 * v / 127)

def _shaker(v=127):
    t   = _t(0.12)
    ns  = np.random.default_rng(4).standard_normal(len(t))
    ns  = sp.sosfilt(sp.butter(4, [4000, SR // 2 - 100], "bandpass", fs=SR, output="sos"), ns)
    return _st(ns * _e(t, 32) * (1 - np.exp(-110 * t)) * 0.28 * v / 127)

_DFNS   = [_kick, _snare, _hh_cl, _hh_op, _tambourine, _rim, _ghost_snare, _shaker]
_DNAMES = ["kick", "snare", "hh-cl", "hh-op", "tamb", "rim", "ghost", "shaker"]
_PAD_NOTES = list(range(36, 44))   # Pad 1-8 note numbers; Bank B = note + 8
_DMAP: dict = {}

def _rebuild_dmap():
    _DMAP.clear()
    for i, note in enumerate(_PAD_NOTES):
        _DMAP[note]     = i
        _DMAP[note + 8] = i   # Bank B

_rebuild_dmap()
_DCACHE: dict = {}

def _init_drums():
    print("  building drum samples...", end=" ", flush=True)
    for i, fn in enumerate(_DFNS):
        _DCACHE[i] = fn(127)
    print("done")

# ── CC / note mapping (auto-learn + file persistence) ─────────────────────────
# cc_map.json: flat dict  "K1"–"K8" → CC number,  "Pad 1"–"Pad 8" → note number
_CC2K        = {}   # cc → knob index 0-7
_learned_ccs = []
_KNOB_FUNCS  = ["vol", "cutoff", "Q", "reverb", "release", "detune", "drive", "crush"]

def _load_cc_map():
    if not CC_MAP_FILE.exists():
        return
    try:
        data = json.loads(CC_MAP_FILE.read_text())
        for name, val in data.items():
            if val is None:
                continue
            if len(name) == 2 and name[0] == "K" and name[1].isdigit():
                k = int(name[1]) - 1
                if 0 <= k < 8:
                    _CC2K[int(val)] = k
            elif name.startswith("Pad ") and name[4:].isdigit():
                idx = int(name[4:]) - 1
                if 0 <= idx < 8:
                    _PAD_NOTES[idx] = int(val)
        for k in range(8):
            cc = next((c for c, ki in _CC2K.items() if ki == k), None)
            if cc is not None:
                _learned_ccs.append(cc)
        _rebuild_dmap()
        print(f"  loaded {CC_MAP_FILE.name}")
    except Exception as e:
        print(f"  warning: could not load {CC_MAP_FILE.name}: {e}")

def _save_cc_map():
    data = {}
    for k in range(8):
        cc = next((c for c, ki in _CC2K.items() if ki == k), None)
        data[f"K{k + 1}"] = cc
    for i, note in enumerate(_PAD_NOTES):
        data[f"Pad {i + 1}"] = note
    CC_MAP_FILE.write_text(json.dumps(data, indent=2) + "\n")
    print(f"\n  saved {CC_MAP_FILE.name}")

def _on_cc(cc, val):
    v = val / 127.0

    if cc in _CC2K:
        k = _CC2K[cc]
        if k == 0:
            S["vol"]     = v;                       _log(f"K1 vol={v:.2f}")
        elif k == 1:
            S["cutoff"]  = 80 + v**2.5*(SR/2-80);  _rebuild_filter(); _log(f"K2 cutoff={S['cutoff']:.0f}Hz")
        elif k == 2:
            S["q"]       = 0.5 + v * 9.5;          _rebuild_filter(); _log(f"K3 Q={S['q']:.2f}")
        elif k == 3:
            S["reverb"]  = v * 0.85;               _log(f"K4 reverb={S['reverb']:.2f}")
        elif k == 4:
            S["release"] = 0.1 + v * 3.0;          _log(f"K5 release={S['release']:.2f}")
        elif k == 5:
            S["detune"]  = v * 0.025;              _log(f"K6 detune={S['detune']:.4f}")
        elif k == 6:
            S["drive"]   = v;                       _log(f"K7 drive={S['drive']:.2f}")
        elif k == 7:
            S["crush"]   = int(v * 8);             _log(f"K8 crush={S['crush']}b")
        return

    if len(_learned_ccs) < 8:
        _learned_ccs.append(cc)
        _CC2K[cc] = len(_learned_ccs) - 1
        k = _CC2K[cc]
        _log(f"CC {cc} -> K{k + 1} ({_KNOB_FUNCS[k]})  [{len(_learned_ccs)}/8]")
        _save_cc_map()
    else:
        _log(f"CC {cc}={val} (ignored)")

def _log(msg):
    print(f"\r  {msg:<40}", end="", flush=True)

# ── MIDI loop ──────────────────────────────────────────────────────────────────
_NNAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
def _note_name(n): return f"{_NNAMES[n % 12]}{n // 12 - 1}"
def _hz(n):        return 440.0 * 2 ** ((n - 69) / 12)

def _midi_loop():
    port_name = next(
        (p for p in mido.get_input_names() if "mpk" in p.lower()),
        mido.get_input_names()[0]
    )
    print(f"  MIDI: {port_name}")
    with mido.open_input(port_name) as port:
        for msg in port:
            if msg.type == "note_on" and msg.velocity > 0:
                idx = _DMAP.get(msg.note)
                if idx is not None:
                    _add_drum(_DCACHE[idx] * (msg.velocity / 127))
                    _log(f"{_DNAMES[idx]}  [ch{msg.channel + 1} note{msg.note}]")
                else:
                    with _notes_lock:
                        _notes_pending.append((msg.note, msg.velocity))
                    _log(f"{_note_name(msg.note)} {_hz(msg.note):.1f}Hz")
            elif msg.type in ("note_off",) or (msg.type == "note_on" and msg.velocity == 0):
                if _DMAP.get(msg.note) is None:
                    with _notes_lock:
                        _notes_off.append(msg.note)
            elif msg.type == "control_change":
                _on_cc(msg.control, msg.value)

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print("\nAKAI MPK Mini — Trip Hop")
    print("=" * 42)
    _init_drums()
    _rebuild_filter()
    _load_cc_map()

    t = threading.Thread(target=_midi_loop, daemon=True)
    t.start()

    n_knobs = len(_learned_ccs)
    print()
    if n_knobs < 8:
        print(f"  >> Turn each knob once in order to assign K1-K8 ({n_knobs}/8 done) <<")
        print("     K1=vol  K2=cutoff  K3=Q  K4=reverb")
        print("     K5=release  K6=detune  K7=drive  K8=crush")
    else:
        print("  Knobs: all 8 assigned")
    print()
    pad_str = "  ".join(f"Pad{i+1}={_PAD_NOTES[i]}" for i in range(8))
    print(f"  Pads: {pad_str}")
    print("  Keys: lofi marimba synth")
    print()
    print("  Ctrl+C to stop")
    print()

    with sd.OutputStream(
        samplerate=SR, blocksize=BLOCK, channels=2,
        dtype="float32", callback=_audio_cb
    ):
        try:
            t.join()
        except KeyboardInterrupt:
            print("\n\nBye.")

if __name__ == "__main__":
    main()
