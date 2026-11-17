"""Baseline tests for software/python/ssl16_core.py (synthetic data only, no board needed).
Run from the repo root:   python -m pytest tests -q
These reproduce the checks made when the code was written (Nov 2026). Keep them passing."""
import os, sys
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "software", "python"))
import ssl16_core as C  # noqa: E402

FS = 12000


def synth(az, el, n, f0=2800.0, noise=300.0, seed=0, delays=None):
    """Far-field plane wave (tone + 2nd harmonic) from (az, el) in the array frame, int16 (n,16)."""
    rng = np.random.default_rng(seed)
    p = C.mic_positions()
    t = np.arange(n)[:, None] / FS + (p @ C.unit(az, el) / C.speed_of_sound(25.0))[None]
    if delays is not None:
        t = t - delays[None]
    x = 3000 * np.sin(2 * np.pi * f0 * t) + 1000 * np.sin(2 * np.pi * 2 * f0 * t)
    return (x + rng.normal(0, noise, x.shape)).astype(np.int16)


def test_geometry_table():
    assert len(C.MICS) == 16
    r = np.hypot([m[1] for m in C.MICS], [m[2] for m in C.MICS])
    assert r.max() < 80.0                     # R80 aperture
    assert C.SLOT_ORDER.split()[:4] == ["M2", "M7", "M10", "M15"]


@pytest.mark.parametrize("method,limit", [("srp", 2.0), ("das", 2.0), ("music", 2.0)])
def test_locator_accuracy(method, limit):
    L = C.Locator(FS, 2048, method=method)
    errs = []
    for az in range(-170, 180, 40):
        for el in (20, 45, 70):
            r = L.process(synth(az, el, 2048, seed=az + el + 500))
            errs.append(C.angular_error(az, el, r["az"], r["el"]))
    assert np.median(errs) < limit


def test_calibration_recovers_channel_delays():
    rng = np.random.default_rng(3)
    d = rng.uniform(-20e-6, 20e-6, 16); d -= d.mean()
    x = np.concatenate([synth(0, 90, FS, f0=f, noise=50, delays=d) for f in np.arange(1000, 5001, 500)])
    est, gains = C.estimate_calibration(x, FS)
    assert np.abs(est - d).max() < 2e-6        # within 2 us (measured 0.4 us when written)


def test_camera_frame_conversion():
    x, y, z = C.position_to_xyz("A", 2.0, 30.0, 1.2, 1.2)
    az, el, d = C.xyz_to_azel(x, y, z)
    th, ph = C.azel_to_camera(az, el)
    assert abs(th - 30.0) < 1e-6 and abs(ph) < 1e-6 and abs(d - 2.0) < 1e-9


def test_wav_roundtrip(tmp_path):
    x = synth(10, 30, 4800)
    p = tmp_path / "t.wav"
    C.write_wav(p, x, FS)
    y, fs = C.read_wav(p)
    assert fs == FS and np.array_equal(x, y)
