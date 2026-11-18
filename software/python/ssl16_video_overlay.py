"""
ssl16_video_overlay.py — draw the SSL-16 SRP-PHAT heatmap on a phone video recorded at the same time.

No live link is needed: the speaker plays ssl16_test_sequence.wav, which starts and ends with the same
3-chirp sync block (500 Hz -> 5 kHz, 50 ms, 1 s apart). The script finds both sync blocks in the phone's
audio track and in the SSL-16 recording, fits t_ssl = a + b * t_phone (offset + clock drift), runs the
SSL-16 locator on the array recording, and paints each video frame with the map of the matching moment.

Usage (one run):
    python ssl16_video_overlay.py P01.mp4 P01.wav --hfov 68 --range 2.0 --lens-offset 0 0.10 0 --out P01_overlay.mp4
        P01.mp4   phone video (landscape, stabilisation off)
        P01.wav   SSL-16 recording: SD file (48 kHz, slot order) or recorder-GUI file (<run>_pc.wav, 12 kHz, mic order).
                  The channel order is read from the .txt / .json next to it (or give --order slot|mic).
    Camera:  --calib camera.json (from ssl16_cam_calib.py)  or  --hfov <deg> (pinhole, no distortion).
    Geometry: --lens-offset dx dy dz = phone lens position in the ARRAY frame (m): +x = your right when you
              face the board, +y up, +z towards the scene.  --range = distance of the source (m).
              --flip-x / --flip-y / --rot = the E0.5 settings (must match the campaign GUI).
    Sync only:  add --sync-only  (prints offset, drift and checks; writes <out>_sync.json).

Outputs: <out>.mp4 (overlay + original phone audio), <out>_results.csv (one row per locator result),
         <out>_sync.json (sync points, clock fit, checks, per-segment summary).
Needs: numpy, scipy, matplotlib (colour map), Pillow, av (PyAV). Keep next to ssl16_core.py.
"""
import argparse
import csv
import json
import math
import os
import sys
import wave
from fractions import Fraction

import numpy as np
from scipy.signal import butter, chirp, fftconvolve, sosfiltfilt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ssl16_core as core  # noqa: E402

VERSION = "1.0"

# ---------------------------------------------------------------- sync template (identical to make_test_wav.py)
CHIRP_S, CHIRP_F0, CHIRP_F1, CHIRP_FADE_MS, CHIRP_GAP_S, N_CHIRPS = 0.05, 500.0, 5000.0, 5, 1.0, 3
SEQ_SYNC_START_S, SEQ_SYNC_END_S = 2.0, 72.05          # from ssl16_test_sequence_markers.csv


def sync_template(fs):
    """The 3-chirp sync block at sample rate fs, exactly as make_test_wav.sync_block() builds it."""
    t = np.arange(int(CHIRP_S * fs)) / fs
    c = chirp(t, CHIRP_F0, t[-1], CHIRP_F1)
    n = int(fs * CHIRP_FADE_MS / 1000)
    w = np.ones(len(c)); r = np.linspace(0, 1, n); w[:n] = r; w[-n:] = r[::-1]
    c = c * w * 0.7
    gap = np.zeros(int(fs * (CHIRP_GAP_S - CHIRP_S)))
    parts = []
    for i in range(N_CHIRPS):
        parts += [c, gap] if i < N_CHIRPS - 1 else [c]
    return np.concatenate(parts)


def _band(x, fs, lo=400.0, hi=5500.0, axis=-1):
    hi = min(hi, 0.45 * fs)
    return sosfiltfilt(butter(4, [lo, hi], btype="band", fs=fs, output="sos"), x, axis=axis)


def _single_chirp(fs):
    return sync_template(fs)[: int(CHIRP_S * fs)]


def find_sync_pair(x, fs, expected_interval_s, min_sep_s=20.0, tol_s=0.005):
    """Find the start and the end sync block (3 chirps, 1 s apart).

    Each chirp is matched on its own (normalised cross-correlation with one 50 ms chirp), because a long
    3-chirp template decorrelates at 5 kHz when the clocks differ by tens of ppm. A block scores
        (ncc(k) + max ncc near k+1 s + max ncc near k+2 s) / 3     (tolerance +-tol_s)
    Returns dict(t=[t_start, t_end] (first chirp of each block, s), chirps=[[3 times], [3 times]],
                 score, ratio (block score / best score elsewhere), interval)."""
    from scipy.ndimage import maximum_filter1d
    c1 = _band(_single_chirp(fs), fs)
    y = _band(np.asarray(x, float), fs)
    num = fftconvolve(y, c1[::-1], mode="valid")                      # num[k] = sum y[k+i] c1[i]
    e = np.concatenate([[0.0], np.cumsum(y * y)])
    en = e[len(c1):] - e[:-len(c1)]
    loc = np.sqrt(np.maximum(en, 1e-3 * en.max() + 1e-20))          # floor: silence must not blow the ratio up
    ncc = num / (loc * np.linalg.norm(c1))
    env = maximum_filter1d(ncc, 2 * int(tol_s * fs) + 1)
    step = int(round(CHIRP_GAP_S * fs))
    n = len(ncc) - (N_CHIRPS - 1) * step
    if n <= 0:
        raise RuntimeError("recording too short")
    score = ncc[:n].copy()
    for j in range(1, N_CHIRPS):
        score += env[j * step: j * step + n]
    score /= N_CHIRPS
    k1 = int(np.argmax(score))
    sep = int(min_sep_s * fs)
    mask = np.ones(n, bool); mask[max(0, k1 - sep):k1 + sep] = False
    if not mask.any():
        raise RuntimeError("recording too short to hold both sync blocks")
    k2 = int(np.flatnonzero(mask)[np.argmax(score[mask])])
    ks = sorted([k1, k2])

    def refine(k):                                                    # parabolic sub-sample peak of one chirp
        if 0 < k < len(ncc) - 1:
            a, b, c = ncc[k - 1], ncc[k], ncc[k + 1]
            d = a - 2 * b + c
            return k + (0.5 * (a - c) / d if d != 0 else 0.0)
        return float(k)

    chirps = []
    w = int(tol_s * fs)
    for k in ks:
        ts = []
        for j in range(N_CHIRPS):
            c = k + j * step
            lo, hi = max(0, c - w), min(len(ncc), c + w + 1)
            kk = lo + int(np.argmax(ncc[lo:hi]))
            ts.append(refine(kk) / fs)
        chirps.append(ts)
    bg = np.ones(n, bool)
    wb = int(((N_CHIRPS - 1) * CHIRP_GAP_S + 0.2) * fs)            # skip the block's own side peaks (+-1 s, +-2 s)
    for k in ks:
        bg[max(0, k - wb):k + wb] = False
    side = float(np.max(score[bg])) if bg.any() else 1e-9
    t = [chirps[0][0], chirps[1][0]]
    return dict(t=t, chirps=chirps, score=[float(score[k]) for k in ks],
                ratio=[float(score[k]) / max(side, 1e-9) for k in ks], interval=t[1] - t[0],
                expected_interval=expected_interval_s)


def fit_clock(phone_t, ssl_t):
    """Least-squares t_ssl = a + b * t_phone over matching chirp times (2 or more pairs)."""
    p, s = np.asarray(phone_t, float).ravel(), np.asarray(ssl_t, float).ravel()
    b, a = np.polyfit(p, s, 1)
    resid = s - (a + b * p)
    return float(a), float(b), float(np.max(np.abs(resid)))


# ---------------------------------------------------------------- inputs
SLOT_NAMES = [m[0] for m in core.MICS]                                 # M2 M7 M10 ... (TDM slot order)


def _order_from_sidecar(wav_path):
    base = os.path.splitext(wav_path)[0]
    for p in (base + ".txt", base + ".json"):
        if not os.path.exists(p):
            continue
        if p.endswith(".txt"):
            for line in open(p, encoding="utf-8", errors="replace"):
                if line.startswith("wav_channel_order="):
                    return line.split("=", 1)[1].split()
        else:
            m = json.load(open(p, encoding="utf-8"))
            if m.get("slot_order"):
                return m["slot_order"].split()
    return None


def load_ssl(path, order=None):
    """16-channel SSL-16 WAV -> float array (n, 16) in TDM slot order (the order ssl16_core.MICS uses)."""
    with wave.open(path, "rb") as w:
        fs, nch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        if nch != 16 or sw != 2:
            raise ValueError(f"{path}: expected 16 channels x 16 bit, got {nch} x {8*sw}")
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, 16).astype(np.float32)
    if order in (None, "auto"):
        names = _order_from_sidecar(path)
        if names is None:
            raise ValueError(f"no channel order found next to {path}: give --order slot or --order mic")
    elif order == "slot":
        names = SLOT_NAMES
    elif order == "mic":
        names = [f"M{i}" for i in range(1, 17)]
    else:
        names = order.split()
    if sorted(names, key=lambda s: int(s[1:])) != [f"M{i}" for i in range(1, 17)]:
        raise ValueError(f"bad channel list {names}")
    idx = [names.index(n) for n in SLOT_NAMES]
    return x[:, idx], fs, names


def load_phone_audio(video_path):
    """Mono float audio of the phone video and the container time (s) of every sample's start."""
    import av
    with av.open(video_path) as c:
        st = c.streams.audio[0]
        chunks, t0, fs = [], None, None
        for fr in c.decode(st):
            a = fr.to_ndarray()
            if a.ndim == 2 and fr.format.is_planar:
                a = a.mean(0)
            elif a.ndim == 2:
                a = a.reshape(-1, len(fr.layout.channels)).mean(1)
            if t0 is None:
                t0 = float(fr.pts * fr.time_base) if fr.pts is not None else 0.0
                fs = fr.sample_rate
            chunks.append(a.astype(np.float64))
    return np.concatenate(chunks), fs, t0                 # scale does not matter: the sync uses normalised correlation


def video_frame_times(video_path):
    import av
    with av.open(video_path) as c:
        st = c.streams.video[0]
        return np.array([float(p.pts * p.time_base) for p in c.demux(st) if p.pts is not None])


# ---------------------------------------------------------------- camera model
class Camera:
    """Pinhole + Brown-Conrady distortion. Camera frame (OpenCV): X right in the image, Y down, Z forward.
    Array frame: x = your right when facing the board, y up, z out of the sound-hole face (towards the scene).
    The phone looks the same way as the board, so nominally x_arr = -X, y_arr = -Y, z_arr = Z."""

    N = np.diag([-1.0, -1.0, 1.0])

    def __init__(self, w, h, fx, fy, cx, cy, dist=None, lens_offset=(0, 0, 0), ypr_deg=(0, 0, 0)):
        self.w, self.h, self.fx, self.fy, self.cx, self.cy = w, h, fx, fy, cx, cy
        self.dist = np.zeros(5) if dist is None else np.r_[np.asarray(dist, float), np.zeros(5)][:5]
        self.t = np.asarray(lens_offset, float)
        yaw, pitch, roll = np.radians(ypr_deg)
        Ry = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]])
        Rx = np.array([[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]])
        Rz = np.array([[math.cos(roll), -math.sin(roll), 0], [math.sin(roll), math.cos(roll), 0], [0, 0, 1]])
        self.R_ac = self.N @ (Rz @ Rx @ Ry)                             # camera -> array
        self.R_ca = self.R_ac.T

    @classmethod
    def from_hfov(cls, w, h, hfov_deg, **kw):
        f = (w / 2) / math.tan(math.radians(hfov_deg) / 2)
        return cls(w, h, f, f, (w - 1) / 2, (h - 1) / 2, **kw)

    @classmethod
    def from_json(cls, path, w, h, **kw):
        c = json.load(open(path, encoding="utf-8"))
        sx, sy = w / c["width"], h / c["height"]
        if abs(sx - sy) > 0.01:
            raise ValueError("video aspect ratio differs from the calibration video")
        return cls(w, h, c["fx"] * sx, c["fy"] * sy, c["cx"] * sx, c["cy"] * sy, dist=c.get("dist"), **kw)

    def _distort(self, x, y):
        k1, k2, p1, p2, k3 = self.dist
        x, y = np.nan_to_num(x), np.nan_to_num(y)
        r2 = x * x + y * y
        rad = 1 + k1 * r2 + k2 * r2 ** 2 + k3 * r2 ** 3
        return x * rad + 2 * p1 * x * y + p2 * (r2 + 2 * x * x), y * rad + p1 * (r2 + 2 * y * y) + 2 * p2 * x * y

    def _undistort(self, xd, yd, it=8):
        x, y = xd.copy(), yd.copy()
        for _ in range(it):
            ex, ey = self._distort(x, y)
            x, y = x - (ex - xd), y - (ey - yd)
        return x, y

    def project_array_points(self, P):
        """P (n,3) in the array frame (m) -> pixels (n,2); NaN when behind the camera."""
        Pc = (np.asarray(P, float) - self.t) @ self.R_ca.T
        Z = Pc[:, 2]
        with np.errstate(divide="ignore", invalid="ignore"):
            x, y = Pc[:, 0] / Z, Pc[:, 1] / Z
        xd, yd = self._distort(x, y)
        uv = np.c_[self.cx + self.fx * xd, self.cy + self.fy * yd]
        uv[Z <= 0] = np.nan
        return uv

    def pixel_directions(self, u, v, rng):
        """Pixels -> az, el (deg, array frame) of the point at distance rng (m) along each pixel's ray."""
        x, y = self._undistort((u - self.cx) / self.fx, (v - self.cy) / self.fy)
        d = np.stack([x, y, np.ones_like(x)], -1)
        d /= np.linalg.norm(d, axis=-1, keepdims=True)
        P = rng * d @ self.R_ac.T + self.t
        P /= np.linalg.norm(P, axis=-1, keepdims=True)
        az = np.degrees(np.arctan2(P[..., 1], P[..., 0]))
        el = np.degrees(np.arcsin(np.clip(P[..., 2], -1, 1)))
        return az, el


def azel_to_array_point(az, el, rng):
    return rng * core.unit(az, el)


# ---------------------------------------------------------------- localisation over time
def run_locator(x, fs, loc_kw, win_s=0.17, hop_frac=0.5, floor_pct=10.0):
    """Locator on 170 ms blocks (50 % overlap). Adds two detection measures per block:
    snr      = the locator's own tonal SNR (strongest bins / median bin) — right for buzzers and tones;
    level_db = in-band level of the array (mean of all channels, band-pass) above the recording's own
               noise floor (the floor_pct percentile of all blocks) — right for noise, speech and horns."""
    nfft = int(2 ** round(math.log2(win_s * fs)))
    hop = int(nfft * hop_frac)
    L = core.Locator(fs, nfft, **loc_kw)
    lo, hi = loc_kw.get("band", (1500, 5000))
    yb = _band(x.astype(np.float64) - x.mean(0), fs, lo, hi, axis=0)
    out = []
    for i in range(0, len(x) - nfft + 1, hop):
        r = L.process(x[i:i + nfft])
        r["t_ssl"] = (i + nfft / 2) / fs
        r["band_db"] = 10 * math.log10(float(np.mean(yb[i:i + nfft] ** 2)) + 1e-12)
        out.append(r)
    floor = float(np.percentile([r["band_db"] for r in out], floor_pct))
    for r in out:
        r["level_db"] = r["band_db"] - floor
    return out, L


def detected(r, args):
    return (r["level_db"] >= args.min_level_db) if args.gate == "level" else (r["snr"] >= args.snr)


def load_markers(path):
    if not path or not os.path.exists(path):
        return []
    return [(r["segment"], float(r["start_s"]), float(r["end_s"])) for r in csv.DictReader(open(path, encoding="utf-8"))]


def segment_at(markers, t_seq):
    for name, a, b in markers:
        if a <= t_seq < b:
            return name
    return ""


# ---------------------------------------------------------------- rendering
def _colormap(name="inferno"):
    from matplotlib import colormaps
    return (colormaps[name](np.linspace(0, 1, 256))[:, :3] * 255).astype(np.float32)


def render(video_in, video_out, results, a, b, cam, L, args, markers, seq_map):
    import av
    from PIL import Image, ImageDraw, ImageFont

    lut = _colormap(args.cmap)
    # low-resolution pixel grid -> (az, el) lookup, computed once (the camera does not move)
    ds = args.heat_step
    gu, gv = np.meshgrid(np.arange(ds / 2, cam.w, ds), np.arange(ds / 2, cam.h, ds))
    az, el = cam.pixel_directions(gu, gv, args.range)
    az_step = float(L.az[1] - L.az[0]); el_step = float(L.el[1] - L.el[0])
    fa = (wrap360(az - L.az[0])) / az_step
    fe = np.clip(el / el_step, 0, len(L.el) - 1)
    valid = el >= 0
    ia0 = np.floor(fa).astype(int) % len(L.az); ia1 = (ia0 + 1) % len(L.az); wa = fa - np.floor(fa)
    ie0 = np.clip(np.floor(fe).astype(int), 0, len(L.el) - 1); ie1 = np.clip(ie0 + 1, 0, len(L.el) - 1); we = fe - np.floor(fe)

    def sample(M):
        m = ((1 - we) * ((1 - wa) * M[ie0, ia0] + wa * M[ie0, ia1]) + we * ((1 - wa) * M[ie1, ia0] + wa * M[ie1, ia1]))
        return np.where(valid, m, 0.0)

    t_res = np.array([r["t_ssl"] for r in results])
    try:
        font = ImageFont.truetype("arial.ttf", max(14, cam.h // 40))
    except OSError:
        font = ImageFont.load_default()

    cin = av.open(video_in)
    vin = cin.streams.video[0]
    vin.thread_type = "AUTO"
    ain = cin.streams.audio[0] if (cin.streams.audio and not args.no_audio) else None
    cout = av.open(video_out, "w")
    rate = vin.average_rate or Fraction(30, 1)
    vout = cout.add_stream("libx264", rate=rate)
    vout.width, vout.height, vout.pix_fmt = cam.w, cam.h, "yuv420p"
    vout.codec_context.time_base = vin.time_base
    vout.options = {"crf": str(args.crf), "preset": "medium"}
    aout = cout.add_stream_from_template(ain) if ain is not None else None
    apk = []
    if ain is not None:                                   # audio packets are copied unchanged (original timing)
        with av.open(video_in) as c2:
            apk = [p for p in c2.demux(c2.streams.audio[0]) if p.dts is not None]
    ai = 0
    heat = None
    last_t = None
    tau = args.smooth_s
    for fr in cin.decode(vin):
        t_ph = float(fr.pts * fr.time_base)
        t_ssl = a + b * t_ph
        img = fr.to_ndarray(format="rgb24").astype(np.float32)
        k = int(np.searchsorted(t_res, t_ssl))
        k = min(max(k, 0), len(t_res) - 1)
        if k > 0 and abs(t_res[k - 1] - t_ssl) < abs(t_res[k] - t_ssl):
            k -= 1
        r = results[k]
        inside = abs(t_res[k] - t_ssl) <= 0.6 * (t_res[1] - t_res[0] if len(t_res) > 1 else 1)
        on = inside and detected(r, args)
        if on:                                            # map in dB below its peak; show the top --dyn-db dB
            M = sample(r["map"])
            h = np.clip(1 + 10 * np.log10(np.maximum(M, 1e-6)) / args.dyn_db, 0, 1)
        else:
            h = np.zeros_like(gu)
        if heat is None or last_t is None:
            heat = h
        else:
            g = math.exp(-max(t_ph - last_t, 0) / tau) if tau > 0 else 0.0
            heat = g * heat + (1 - g) * h
        last_t = t_ph
        hi = np.asarray(Image.fromarray((heat * 255).astype(np.uint8)).resize((cam.w, cam.h), Image.BILINEAR),
                        np.float32) / 255.0
        col = lut[(hi * 255).astype(np.uint8)]
        alpha = (args.alpha * np.sqrt(hi))[..., None]
        img = img * (1 - alpha) + col * alpha
        pil = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
        dr = ImageDraw.Draw(pil)
        seg = ""
        if seq_map is not None:
            seg = segment_at(markers, seq_map(t_ssl))
        if on:
            uv = cam.project_array_points(azel_to_array_point(r["az"], r["el"], args.range)[None])[0]
            th, ph = core.azel_to_camera(r["az"], r["el"])
            if np.all(np.isfinite(uv)):
                u, v = uv; s = max(10, cam.h // 40)
                dr.line([(u - s, v), (u + s, v)], fill=(0, 255, 255), width=2)
                dr.line([(u, v - s), (u, v + s)], fill=(0, 255, 255), width=2)
            txt = f"theta {th:+.1f}  phi {ph:+.1f}  level +{r['level_db']:.0f} dB"
        else:
            txt = "no detection"
        dr.text((10, 8), f"t_video {t_ph:6.2f} s   t_ssl {t_ssl:6.2f} s   {seg}", fill=(255, 255, 255), font=font)
        dr.text((10, 14 + int(font.getbbox("Ag")[3])), txt, fill=(255, 255, 255), font=font)
        of = av.VideoFrame.from_ndarray(np.asarray(pil), format="rgb24")
        of.pts, of.time_base = fr.pts, vin.time_base
        while ai < len(apk) and float(apk[ai].pts * apk[ai].time_base) <= t_ph:
            apk[ai].stream = aout; cout.mux(apk[ai]); ai += 1
        for p in vout.encode(of):
            cout.mux(p)
    for p in vout.encode():
        cout.mux(p)
    while ai < len(apk):
        apk[ai].stream = aout; cout.mux(apk[ai]); ai += 1
    cout.close(); cin.close()


def wrap360(a):
    return np.mod(a, 360.0)


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video"); ap.add_argument("ssl_wav")
    ap.add_argument("--out", default=None, help="output .mp4 (default <video>_overlay.mp4)")
    ap.add_argument("--order", default="auto", help="channel order of ssl_wav: auto (from .txt/.json), slot, mic")
    ap.add_argument("--markers", default=None, help="ssl16_test_sequence_markers.csv (segment labels)")
    ap.add_argument("--sync-interval", type=float, default=SEQ_SYNC_END_S - SEQ_SYNC_START_S,
                    help="start of end-sync minus start of start-sync in the played file (s)")
    ap.add_argument("--calib", default=None, help="camera.json from ssl16_cam_calib.py")
    ap.add_argument("--hfov", type=float, default=None, help="horizontal field of view (deg) if no --calib")
    ap.add_argument("--lens-offset", type=float, nargs=3, default=[0.0, 0.0, 0.0], metavar=("DX", "DY", "DZ"))
    ap.add_argument("--cam-ypr", type=float, nargs=3, default=[0.0, 0.0, 0.0], metavar=("YAW", "PITCH", "ROLL"),
                    help="small camera rotation corrections (deg)")
    ap.add_argument("--range", type=float, default=2.0, help="source distance used for the parallax (m)")
    ap.add_argument("--flip-x", action="store_true"); ap.add_argument("--flip-y", action="store_true")
    ap.add_argument("--rot", type=float, default=0.0)
    ap.add_argument("--temp", type=float, default=25.0, help="air temperature (C)")
    ap.add_argument("--band", type=float, nargs=2, default=[1500.0, 5000.0])
    ap.add_argument("--method", default="srp", choices=["srp", "das", "music"])
    ap.add_argument("--gate", default="level", choices=["level", "tonal"],
                    help="detection: level = in-band level above the noise floor (noise, speech, horns); "
                         "tonal = the locator's tonal SNR (buzzers, tones)")
    ap.add_argument("--min-level-db", type=float, default=10.0, help="level gate: dB above the noise floor")
    ap.add_argument("--snr", type=float, default=12.0, help="tonal gate: locator SNR (dB)")
    ap.add_argument("--topk", type=int, default=64, help="frequency bins used per block")
    ap.add_argument("--dyn-db", type=float, default=3.0, help="heatmap shows the top N dB of the SRP map")
    ap.add_argument("--alpha", type=float, default=0.65); ap.add_argument("--cmap", default="turbo")
    ap.add_argument("--smooth-s", type=float, default=0.12, help="time smoothing of the heatmap (s)")
    ap.add_argument("--heat-step", type=int, default=8, help="heatmap is computed every N pixels, then upsampled")
    ap.add_argument("--crf", type=int, default=20); ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--truth-theta", type=float, default=None); ap.add_argument("--truth-phi", type=float, default=None)
    ap.add_argument("--sync-only", action="store_true")
    ap.add_argument("--max-drift-ppm", type=float, default=200.0)
    args = ap.parse_args(argv)
    out = args.out or os.path.splitext(args.video)[0] + "_overlay.mp4"
    stem = os.path.splitext(out)[0]

    # 1) sync
    xs, fs, names = load_ssl(args.ssl_wav, args.order)
    xp, fsp, t0p = load_phone_audio(args.video)
    ref = xs[:, SLOT_NAMES.index("M1")]                              # M1 sits 10 mm from the array centre
    s_ssl = find_sync_pair(ref, fs, args.sync_interval, min_sep_s=0.5 * args.sync_interval)
    s_ph = find_sync_pair(xp, fsp, args.sync_interval, min_sep_s=0.5 * args.sync_interval)
    ph_t = [t0p + t for t in s_ph["t"]]
    a, b, resid = fit_clock(np.array(s_ph["chirps"]) + t0p, s_ssl["chirps"])
    ppm = (b - 1) * 1e6
    checks = {
        "chirp_fit_residual_lt_2ms": resid < 0.002,
        "ssl_peak_ratio_ge_3": min(s_ssl["ratio"]) >= 3, "phone_peak_ratio_ge_3": min(s_ph["ratio"]) >= 3,
        "ssl_interval_ok": abs(s_ssl["interval"] - args.sync_interval) < 0.002 * args.sync_interval,
        "phone_interval_ok": abs(s_ph["interval"] - args.sync_interval) < 0.002 * args.sync_interval,
        "drift_ok": abs(ppm) <= args.max_drift_ppm,
    }
    rep = dict(version=VERSION, video=os.path.basename(args.video), ssl_wav=os.path.basename(args.ssl_wav),
               ssl_fs=fs, ssl_channel_order_in_file=" ".join(names), phone_fs=fsp, phone_audio_t0=t0p,
               sync_ssl=s_ssl, sync_phone=dict(s_ph, t=ph_t), a_s=a, b=b, drift_ppm=ppm,
               chirp_fit_residual_ms=resid * 1e3, checks=checks)
    print(f"sync  SSL  t = {s_ssl['t'][0]:.4f} / {s_ssl['t'][1]:.4f} s  (ratio {min(s_ssl['ratio']):.1f})")
    print(f"sync  phone t = {ph_t[0]:.4f} / {ph_t[1]:.4f} s  (ratio {min(s_ph['ratio']):.1f})")
    print(f"clock t_ssl = {a:+.4f} + {b:.7f} * t_phone   (drift {ppm:+.1f} ppm, worst chirp residual {resid*1e3:.2f} ms)")
    for k, v in checks.items():
        print(f"  {'OK  ' if v else 'FAIL'} {k}")
    markers = load_markers(args.markers)
    k_seq = args.sync_interval / s_ssl["interval"]
    seq_map = (lambda t: SEQ_SYNC_START_S + (t - s_ssl["t"][0]) * k_seq) if markers else None
    if args.sync_only:
        json.dump(rep, open(stem + "_sync.json", "w"), indent=1)
        return 0 if all(checks.values()) else 2
    if not all(checks.values()):
        print("WARNING: sync checks failed; the overlay timing may be wrong (see README / plan).")

    # 2) locator
    loc_kw = dict(band=tuple(args.band), flip_x=args.flip_x, flip_y=args.flip_y, rot=args.rot, temp_c=args.temp,
                  method=args.method, topk=args.topk)
    results, L = run_locator(xs, fs, loc_kw)
    print(f"locator: {len(results)} results, {sum(detected(r, args) for r in results)} detected (gate {args.gate})")

    # 3) camera
    import av
    with av.open(args.video) as c:
        vs = c.streams.video[0]; W, H = vs.codec_context.width, vs.codec_context.height
    kw = dict(lens_offset=args.lens_offset, ypr_deg=args.cam_ypr)
    if args.calib:
        cam = Camera.from_json(args.calib, W, H, **kw)
    elif args.hfov:
        cam = Camera.from_hfov(W, H, args.hfov, **kw)
    else:
        ap.error("give --calib camera.json or --hfov DEG")

    # 4) results table (+ per-segment summary)
    rows = []
    for r in results:
        th, ph = core.azel_to_camera(r["az"], r["el"])
        uv = cam.project_array_points(azel_to_array_point(r["az"], r["el"], args.range)[None])[0]
        t_seq = seq_map(r["t_ssl"]) if seq_map else ""
        rows.append(dict(t_ssl=round(r["t_ssl"], 4), t_phone=round((r["t_ssl"] - a) / b, 4),
                         t_seq=round(t_seq, 4) if seq_map else "", segment=segment_at(markers, t_seq) if seq_map else "",
                         az=round(r["az"], 2), el=round(r["el"], 2), theta=round(th, 2), phi=round(ph, 2),
                         snr_db=round(r["snr"], 2), level_db=round(r["level_db"], 2), peak=round(r["peak"], 3),
                         detected=int(detected(r, args)),
                         u=round(float(uv[0]), 1) if np.isfinite(uv[0]) else "", v=round(float(uv[1]), 1) if np.isfinite(uv[1]) else ""))
    with open(stem + "_results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    summ = {}
    for seg in sorted({r["segment"] for r in rows if r["segment"]}):
        d = [r for r in rows if r["segment"] == seg]
        det = [r for r in d if r["detected"]]
        s = dict(n=len(d), detect_rate=round(len(det) / len(d), 3))
        if det:
            s.update(theta_median=round(float(np.median([r["theta"] for r in det])), 2),
                     phi_median=round(float(np.median([r["phi"] for r in det])), 2))
            if args.truth_theta is not None:
                s["theta_mae"] = round(float(np.mean([abs(r["theta"] - args.truth_theta) for r in det])), 2)
            if args.truth_phi is not None:
                s["phi_mae"] = round(float(np.mean([abs(r["phi"] - args.truth_phi) for r in det])), 2)
        summ[seg] = s
    rep.update(segments=summ, camera=dict(w=W, h=H, fx=cam.fx, fy=cam.fy, cx=cam.cx, cy=cam.cy, dist=list(cam.dist),
                                          lens_offset=list(cam.t), ypr_deg=args.cam_ypr), range_m=args.range,
               locator=dict(loc_kw, band=list(args.band), gate=args.gate, min_level_db=args.min_level_db, snr_thr=args.snr))
    json.dump(rep, open(stem + "_sync.json", "w"), indent=1, default=float)
    for seg, s in summ.items():
        print(f"  {seg:15s} {s}")

    # 5) video
    render(args.video, out, results, a, b, cam, L, args, markers, seq_map)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
