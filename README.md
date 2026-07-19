# AKAI MPK Mini Mk II — Trip Hop Instrument

A real-time software instrument for the AKAI MPK Mini Mk II.  
On startup you're prompted to pick a **song**, each with its own pad drum kit and keys synth voice:

| Song | Pads | Keys |
|------|------|------|
| Teardrop — Massive Attack | trip hop drum kit | lofi marimba/vibraphone synth |
| Via con me — Paolo Conte | brushed/latin lounge percussion (soft kick, brush snare, ride, castanets, claves, conga, maracas) | musette accordion synth |

Press Enter at the prompt to load the first song. Knobs shape the synth sound (with song-specific starting values); drums are unaffected except by master volume.

## Requirements

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
source .venv/bin/activate
python run.py
```

---

## Pads (notes 36–51, any channel)

Sound assignment depends on the song picked at startup:

| Pad | Note | Teardrop        | Via con me       |
|-----|------|-----------------|------------------|
| 1   | 36   | Kick            | Soft kick        |
| 2   | 37   | Snare           | Brush snare      |
| 3   | 38   | Hi-hat closed   | Hat tick         |
| 4   | 39   | Hi-hat open     | Ride             |
| 5   | 40   | Tambourine      | Castanets        |
| 6   | 41   | Rimshot         | Claves           |
| 7   | 42   | Ghost snare     | Conga            |
| 8   | 43   | Shaker          | Maracas          |

Bank B (notes 44–51) repeats the same pattern. Only master volume (K1) affects drums.

---

## Keys (any channel, notes outside 36–51)

Both songs use the same voice architecture — sine fundamental + upper harmonics, shaped by a fast 6 ms attack and exponential decay, run through a per-voice warm LP filter, optional bit crush, and a subtle stereo spread before entering the global synth chain — but with different harmonic content and default knob values:

- **Teardrop**: lofi marimba/vibraphone hybrid, with a sub-octave partial for a plucked, struck character.
- **Via con me**: musette accordion voice — whole-harmonic reed stack, longer sustain, and a stronger detune for the classic double-reed "wet" warble.

The hardware arpeggiator works cleanly — each step replaces the previous voice with a short 15 ms fade, avoiding clicks and voice accumulation.

---

## cc_map.json

`cc_map.json` is a flat mapping of hardware control labels to their MIDI signal numbers. Edit it directly if your MPK Mini sends different values.

```json
{
  "K1": 16,  "K2": 20,  "K3": 17,  "K4": 21,
  "K5": 18,  "K6": 22,  "K7": 19,  "K8": 23,
  "Pad 1": 36, "Pad 2": 37, "Pad 3": 38, "Pad 4": 39,
  "Pad 5": 40, "Pad 6": 41, "Pad 7": 42, "Pad 8": 43
}
```

**Pads** use note numbers. Bank B (the second pad bank on the hardware) is assumed to be `note + 8` — this matches the MPK Mini default and requires no separate entry.

**Knobs** use CC numbers and are auto-learned at startup: turn each knob once in order K1 → K8. The learned values are written back to `cc_map.json` automatically.

> Delete `cc_map.json` and re-learn if you switch the MPK Mini to a different preset/bank.

### Knob functions (fixed by position)

| Knob | Function      | Range           | Applies to   |
|------|---------------|-----------------|--------------|
| K1   | Master volume | 0 → 1           | Everything   |
| K2   | LP cutoff     | 80 Hz → ~22 kHz | Synth only   |
| K3   | Resonance (Q) | 0.5 → 10        | Synth only   |
| K4   | Reverb wet    | 0 → 0.85        | Synth only   |
| K5   | Release       | 0.1 s → 3.1 s   | Synth only   |
| K6   | Detune        | 0 → 0.025       | Synth only   |
| K7   | Soft drive    | 0 → 1           | Synth only   |
| K8   | Lofi crush    | off → 4-bit     | Synth only   |

K2 uses an exponential curve so the lower half covers the musically useful range.  
K7 and K8 default to 0 (off) — turn them up to hear their effect.

### Synth signal chain

```
oscillator → per-voice LP → bit crush → stereo spread
    → global LP (K2/K3) → soft drive (K7) → reverb (K4) → master vol (K1)
```

### Reverb

Two-tap feedback delay at 191 ms and 313 ms. K4 fully left is dry; fully right gives a long washy tail.

---

## Troubleshooting

**Knobs have no effect** — check the terminal output when you turn a knob. You should see `K1 vol=0.xx` etc. If you see `CC XX=YY (ignored)`, the MPK Mini is sending different CC numbers than stored — delete `cc_map.json` and re-learn with the device in the correct preset.

**No audio output** — `sounddevice` uses the system default output device. Pass `device=` to `sd.OutputStream` in `main()` to select a different one.
