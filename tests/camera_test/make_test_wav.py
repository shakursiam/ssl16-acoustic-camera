#!/usr/bin/env python3
"""Build one SSL-16 test-sequence WAV:
sync chirps -> pink-noise bursts -> speech -> vehicle horns -> sync chirps.
Writes ssl16_test_sequence.wav (48 kHz, 16-bit, mono) and ssl16_test_sequence_markers.csv."""
import csv, subprocess, tempfile, os
import numpy as np
from scipy.io import wavfile
from scipy.signal import chirp, resample_poly

FS = 48000
rng = np.random.default_rng(16)
TARGET_RMS = 0.18            # every test segment gets the same loudness


def fade(x, ms=5):
    n = int(FS * ms / 1000)
    w = np.ones(len(x)); r = np.linspace(0, 1, n)
    w[:n] = r; w[-n:] = r[::-1]
    return x * w


def silence(s):
    return np.zeros(int(FS * s))


def set_rms(x, rms=TARGET_RMS):
    active = x[np.abs(x) > 1e-4]
    return x * (rms / np.sqrt(np.mean(active ** 2)))


def sync_block():
    """3 linear chirps 500 Hz -> 5 kHz, 50 ms each, 1 s apart (start to start)."""
    t = np.arange(int(0.05 * FS)) / FS
    c = fade(chirp(t, 500, t[-1], 5000)) * 0.7
    out = []
    for i in range(3):
        out += [c, silence(1.0 - 0.05) if i < 2 else np.zeros(0)]
    return np.concatenate(out)


def pink(n):
    w = rng.standard_normal(n)
    f = np.fft.rfftfreq(n, 1 / FS); f[0] = f[1]
    X = np.fft.rfft(w) / np.sqrt(f)
    X[(f < 300) | (f > 5000)] *= 0.1              # keep energy inside the board's band
    return np.fft.irfft(X, n)


def noise_bursts(total=20.0):
    burst = int(0.5 * FS)
    out = []
    for _ in range(int(total)):
        out += [fade(pink(burst)), silence(0.5)]
    return set_rms(np.concatenate(out))


def speech(total=20.0):
    text = ("This is the S S L sixteen test. One, two, three, four, five. "
            "The quick brown fox jumps over the lazy dog. "
            "Sound source localization with sixteen microphones. "
            "Testing direction, distance, and timing. "
            "Six, seven, eight, nine, ten. Speech test complete.")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.wav")
        subprocess.run(["espeak-ng", "-v", "en-us", "-s", "150", "-a", "180", "-w", p, text], check=True)
        sr, s = wavfile.read(p)
    s = s.astype(np.float64) / 32768
    s = resample_poly(s, FS, sr)
    s = s[: int(total * FS)]
    s = np.concatenate([s, silence(max(0, total - len(s) / FS))])
    return set_rms(fade(s, 20))


def honk(dur, f1, f2, harm=12):
    """Two-tone electric horn: square-ish waveform (odd+even harmonics), small vibrato."""
    t = np.arange(int(dur * FS)) / FS
    x = np.zeros_like(t)
    for f in (f1, f2):
        ph = 2 * np.pi * f * t + 0.3 * np.sin(2 * np.pi * 30 * t)
        for k in range(1, harm + 1):
            if k * f > 5500:
                break
            x += np.sin(k * ph) / k ** 0.9
    return fade(np.tanh(1.5 * x / np.max(np.abs(x))), 15)


def horns(total=20.0):
    car = (420, 510)          # typical car two-tone horn
    bus = (300, 375)          # deeper bus / truck horn
    pattern = [  # (gap before, duration, horn)
        (0.0, 0.3, car), (0.3, 0.3, car), (1.0, 1.2, car), (1.5, 0.2, car), (0.2, 0.2, car),
        (0.2, 0.2, car), (1.5, 1.5, bus), (1.5, 0.5, bus), (0.4, 0.5, bus), (1.5, 2.0, car),
        (1.5, 0.3, bus), (0.3, 1.0, bus),
    ]
    out = []
    for gap, d, (f1, f2) in pattern:
        out += [silence(gap), honk(d, f1, f2)]
    x = np.concatenate(out)
    x = np.concatenate([x, silence(max(0, total - len(x) / FS))])[: int(total * FS)]
    return set_rms(x)


segments = [
    ("lead_in_silence", silence(2.0)),
    ("sync_start", sync_block()),
    ("gap", silence(2.0)),
    ("noise_bursts", noise_bursts()),
    ("gap", silence(2.0)),
    ("speech", speech()),
    ("gap", silence(2.0)),
    ("vehicle_horns", horns()),
    ("gap", silence(2.0)),
    ("sync_end", sync_block()),
    ("lead_out_silence", silence(2.0)),
]

rows, pos, parts = [], 0, []
for name, x in segments:
    rows.append((name, round(pos / FS, 3), round((pos + len(x)) / FS, 3)))
    parts.append(x); pos += len(x)
y = np.concatenate(parts)
y *= 0.89 / np.max(np.abs(y))                     # peak at -1 dBFS
wavfile.write("ssl16_test_sequence.wav", FS, (y * 32767).astype(np.int16))
with open("ssl16_test_sequence_markers.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["segment", "start_s", "end_s"])
    w.writerows(r for r in rows if r[0] != "gap")
print("total %.2f s" % (len(y) / FS))
for r in rows:
    print(r)
