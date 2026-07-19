"""Via con me — Paolo Conte: brushed/latin lounge percussion + musette accordion synth."""

import numpy as np
from scipy import signal as sp

from ..utils import SR, _st, _t, _e

def _soft_kick(v=127):
    t   = _t(0.30)
    f   = 150 * np.exp(-30 * t) + 55
    osc = np.sin(2 * np.pi * np.cumsum(f) / SR)
    return _st(np.tanh(osc * _e(t, 9) * 1.2) * 0.75 * v / 127)

def _brush_snare(v=127):
    t    = _t(0.32)
    ns   = np.random.default_rng(10).standard_normal(len(t))
    ns   = sp.sosfilt(sp.butter(4, [400, 9000], "bandpass", fs=SR, output="sos"), ns)
    tone = np.sin(2 * np.pi * 190 * t) * _e(t, 70)
    return _st((ns * _e(t, 10) * 0.42 + tone * 0.12) * v / 127)

def _hat_tick(v=127):
    t  = _t(0.045)
    ns = np.random.default_rng(11).standard_normal(len(t))
    ns = sp.sosfilt(sp.butter(4, 9000, "high", fs=SR, output="sos"), ns)
    return _st(ns * _e(t, 140) * 0.26 * v / 127)

def _ride(v=127):
    t     = _t(0.9)
    ns    = np.random.default_rng(12).standard_normal(len(t))
    ns    = sp.sosfilt(sp.butter(4, 6000, "high", fs=SR, output="sos"), ns)
    shine = (np.sin(2 * np.pi * 5200 * t) + np.sin(2 * np.pi * 8300 * t)) * 0.15
    return _st((ns * _e(t, 3.5) * 0.22 + shine * _e(t, 4.5)) * v / 127)

def _castanets(v=127):
    t   = _t(0.05)
    ns  = np.random.default_rng(13).standard_normal(len(t))
    ns  = sp.sosfilt(sp.butter(4, 3000, "high", fs=SR, output="sos"), ns)
    env = _e(t, 220) + 0.6 * _e(np.clip(t - 0.014, 0, None), 220)
    return _st(ns * env * 0.20 * v / 127)

def _claves(v=127):
    t = _t(0.09)
    return _st((np.sin(2 * np.pi * 2500 * t) + np.sin(2 * np.pi * 1800 * t))
               * _e(t, 90) * 0.36 * v / 127)

def _conga(v=127):
    t    = _t(0.28)
    f    = 320 * np.exp(-18 * t) + 150
    osc  = np.sin(2 * np.pi * np.cumsum(f) / SR)
    slap = np.random.default_rng(14).standard_normal(len(t)) * _e(t, 400) * 0.25
    return _st((osc * _e(t, 11) * 0.6 + slap) * v / 127)

def _maracas(v=127):
    t   = _t(0.11)
    ns  = np.random.default_rng(15).standard_normal(len(t))
    ns  = sp.sosfilt(sp.butter(4, [4500, SR // 2 - 100], "bandpass", fs=SR, output="sos"), ns)
    return _st(ns * _e(t, 55) * (1 - np.exp(-160 * t)) * 0.30 * v / 127)

DFNS   = [_soft_kick, _brush_snare, _hat_tick, _ride, _castanets, _claves, _conga, _maracas]
DNAMES = ["soft-kick", "brush-snr", "hat-tick", "ride", "castanets", "claves", "conga", "maracas"]

PARTIALS = [1.0, 2.0, 3.0, 4.0, 5.0]
WEIGHTS  = [0.42, 0.24, 0.16, 0.08, 0.10]

DEFAULTS = {
    "cutoff": 4200.0, "q": 0.60, "reverb": 0.22,
    "release": 0.45, "detune": 0.011, "drive": 0.00, "crush": 0,
}

SONG = {
    "name":     "Via con me — Paolo Conte",
    "keys":     "musette accordion synth",
    "dfns":     DFNS,
    "dnames":   DNAMES,
    "partials": PARTIALS,
    "weights":  WEIGHTS,
    "defaults": DEFAULTS,
}
