"""Shared DSP helpers used by the engine and by each song's instrument set."""

import numpy as np

SR = 44100

def _st(mono, pan=0.0):
    l = mono * (1 - max(pan, 0.0))
    r = mono * (1 + min(pan, 0.0))
    return np.column_stack([l, r]).astype(np.float32)

def _t(s):    return np.arange(int(SR * s)) / SR
def _e(t, r): return np.exp(-r * t)
