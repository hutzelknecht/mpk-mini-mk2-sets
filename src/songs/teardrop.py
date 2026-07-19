"""Teardrop — Massive Attack: trip-hop drum kit + lofi marimba/vibraphone synth."""

import numpy as np
from scipy import signal as sp

from ..utils import SR, _st, _t, _e

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

DFNS   = [_kick, _snare, _hh_cl, _hh_op, _tambourine, _rim, _ghost_snare, _shaker]
DNAMES = ["kick", "snare", "hh-cl", "hh-op", "tamb", "rim", "ghost", "shaker"]

PARTIALS = [1.0, 2.0, 3.0, 4.0, 0.5]
WEIGHTS  = [0.50, 0.22, 0.10, 0.05, 0.07]

DEFAULTS = {
    "cutoff": 3500.0, "q": 0.70, "reverb": 0.28,
    "release": 1.00, "detune": 0.004, "drive": 0.00, "crush": 0,
}

SONG = {
    "name":     "Teardrop — Massive Attack",
    "keys":     "lofi marimba synth",
    "dfns":     DFNS,
    "dnames":   DNAMES,
    "partials": PARTIALS,
    "weights":  WEIGHTS,
    "defaults": DEFAULTS,
}
