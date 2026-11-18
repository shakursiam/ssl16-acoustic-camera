"""End-to-end check of ssl16_video_overlay.py on synthetic data (no hardware, no real phone).

A source at a known array-frame position plays a short test sequence (sync block, pink-noise bursts,
sync block). We simulate (1) the 16 SSL-16 channels with the exact mic delays, decimated to 12 kHz, on a
clock that starts later and runs 50 ppm fast, and (2) a phone video whose audio track hears the same
sequence and whose frames show a dot where the camera sees the source. The pipeline must recover the
clock offset/drift and put the localisation marker on the dot.
"""
import json
import os
import sys
import wave

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "software", "python"))
av = pytest.importorskip("av")
from scipy.signal import resample_poly  # noqa: E402

import ssl16_core as core  # noqa: E402
import ssl16_video_overlay as vo  # noqa: E402

FS = 48000
P_SRC = np.array([0.6, 0.3, 1.9])          # array frame (m): right, up, forward
LENS = np.array([0.0, 0.10, 0.0])          # phone lens 10 cm above the array centre
HFOV, W, H, FPS = 70.0, 640, 360, 30
A_TRUE, B_TRUE = -1.5, 1 + 50e-6           # t_ssl = a + b * t_phone
T0 = 2.0                                   # sequence starts 2 s into the phone video


def make_sequence(rng):
    def pink(n):
        f = np.fft.rfftfreq(n, 1 / FS); f[0] = f[1]
        X = np.fft.rfft(rng.standard_normal(n)) / np.sqrt(f); X[(f < 300) | (f > 5000)] *= 0.1
        return np.fft.irfft(X, n)
    sync = vo.sync_template(FS)
    bursts = np.concatenate([np.r_[pink(FS // 2), np.zeros(FS // 2)] for _ in range(6)])
    bursts *= 0.18 / np.sqrt(np.mean(bursts[np.abs(bursts) > 1e-4] ** 2))
    z = np.zeros(FS)
    seq = np.concatenate([z, sync, z, bursts, z, sync, z])
    interval = (len(sync) + len(z) + len(bursts) + len(z)) / FS          # start of sync 1 -> start of sync 2
    return seq / np.abs(seq).max() * 0.89, interval


def render_inputs(tmp, rng):
    seq, interval = make_sequence(rng)
    up = resample_poly(seq, 4, 1); fs_up = 4 * FS
    c = core.speed_of_sound(25.0)
    mics = core.mic_positions()                                   # slot order, array frame
    dur_ph = T0 + len(seq) / FS + 1.5
    # --- SSL-16: starts 1.5 s after the phone, 50 ppm fast clock, 48 kHz -> 12 kHz
    n_ssl = int((A_TRUE + B_TRUE * dur_ph) * FS)
    t_ssl = np.arange(n_ssl) / FS
    t_ph = (t_ssl - A_TRUE) / B_TRUE
    x = np.zeros((n_ssl, 16))
    for i, m in enumerate(mics):
        tau = np.linalg.norm(P_SRC - m) / c
        x[:, i] = np.interp((t_ph - T0 - tau) * fs_up, np.arange(len(up)), up, left=0, right=0)
    x = resample_poly(x, 1, 4, axis=0) * 0.3 + rng.normal(0, 2e-4, (n_ssl // 4 + 1, 16))[: len(x[::4])]
    ssl_path = os.path.join(tmp, "run_pc.wav")
    with wave.open(ssl_path, "wb") as w:
        w.setnchannels(16); w.setsampwidth(2); w.setframerate(FS // 4)
        w.writeframes(np.clip(x * 32767, -32768, 32767).astype("<i2").tobytes())
    # --- phone: audio at the lens position, video with a dot at the source pixel
    cam = vo.Camera.from_hfov(W, H, HFOV, lens_offset=LENS)
    u, v = cam.project_array_points(P_SRC[None])[0]
    tau_p = np.linalg.norm(P_SRC - LENS) / c
    n_ph = int(dur_ph * FS)
    pa = np.interp((np.arange(n_ph) / FS - T0 - tau_p) * fs_up, np.arange(len(up)), up, left=0, right=0) * 0.5
    pa += rng.normal(0, 1e-3, n_ph)
    vid = os.path.join(tmp, "run.mp4")
    out = av.open(vid, "w")
    vs = out.add_stream("libx264", rate=FPS); vs.width, vs.height, vs.pix_fmt = W, H, "yuv420p"
    as_ = out.add_stream("aac", rate=FS); as_.layout = "mono"
    yy, xx = np.mgrid[0:H, 0:W]
    base = np.full((H, W, 3), 60, np.uint8)
    base[(xx - u) ** 2 + (yy - v) ** 2 <= 36] = 255
    for i in range(int(dur_ph * FPS)):
        f = av.VideoFrame.from_ndarray(base, format="rgb24"); f.pts = i
        for p in vs.encode(f): out.mux(p)
    for p in vs.encode(): out.mux(p)
    for k in range(0, n_ph - 1024, 1024):
        f = av.AudioFrame.from_ndarray(pa[None, k:k + 1024].astype(np.float32), format="fltp", layout="mono")
        f.sample_rate, f.pts = FS, k
        for p in as_.encode(f): out.mux(p)
    for p in as_.encode(): out.mux(p)
    out.close()
    return vid, ssl_path, interval, (u, v)


def test_sync_template_matches_the_played_file():
    p = os.path.join(HERE, "camera_test", "ssl16_test_sequence.wav")
    if not os.path.exists(p):
        pytest.skip("ssl16_test_sequence.wav not present")
    with wave.open(p, "rb") as w:
        fs = w.getframerate(); x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(float)
    tpl = vo.sync_template(fs)
    for t0 in (vo.SEQ_SYNC_START_S, vo.SEQ_SYNC_END_S):           # markers are rounded to 1 ms: allow +-2 samples
        k = int(round(t0 * fs))
        best = max(np.corrcoef(x[k + d: k + d + len(tpl)], tpl)[0, 1] for d in range(-2, 3))
        assert best > 0.999
    s = vo.find_sync_pair(x, fs, vo.SEQ_SYNC_END_S - vo.SEQ_SYNC_START_S)
    assert abs(s["t"][0] - vo.SEQ_SYNC_START_S) < 1e-3 and abs(s["t"][1] - vo.SEQ_SYNC_END_S) < 1e-3
    assert min(s["ratio"]) > 3


def test_overlay_end_to_end(tmp_path):
    rng = np.random.default_rng(3)
    vid, ssl_path, interval, (u0, v0) = render_inputs(str(tmp_path), rng)
    out = os.path.join(str(tmp_path), "run_overlay.mp4")
    rc = vo.main([vid, ssl_path, "--order", "slot", "--hfov", str(HFOV), "--lens-offset", *map(str, LENS),
                  "--range", str(np.linalg.norm(P_SRC)), "--sync-interval", str(interval), "--out", out])
    assert rc == 0
    rep = json.load(open(out[:-4] + "_sync.json"))
    assert all(rep["checks"].values()), rep["checks"]
    assert abs(rep["drift_ppm"] - 50) < 15                         # clock drift recovered
    assert abs(rep["a_s"] - A_TRUE) < 0.003                        # offset within 3 ms (acoustic paths differ by < 0.1 ms)
    import csv
    rows = [r for r in csv.DictReader(open(out[:-4] + "_results.csv")) if r["detected"] == "1" and r["u"]]
    assert len(rows) > 20
    u = np.median([float(r["u"]) for r in rows]); v = np.median([float(r["v"]) for r in rows])
    px_per_deg = (W / 2) / np.tan(np.radians(HFOV / 2)) * np.pi / 180
    assert np.hypot(u - u0, v - v0) < 2.5 * px_per_deg, (u, v, u0, v0)  # marker within 2.5 deg of the dot
    with av.open(out) as c:
        assert c.streams.video[0].frames > 0 or c.duration
