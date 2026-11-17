"""
ssl16_core.py — shared geometry, beamformers and file I/O for the SSL-16 GUI and analysis script.
Keep this file next to ssl16_buzzer_gui.py and ssl16_analyze.py.
"""
import json, wave
import numpy as np

VERSION = "2.0"

# TDM stream slot 0..15 -> (name, x_mm, y_mm), revC1 table; order confirmed on the Rev D board
MICS = [
    ("M2", -16.122, 10.668), ("M7", -18.989, 42.553), ("M10", -56.913, 13.588), ("M15", -52.491, 54.144),
    ("M1", 9.877, 1.564),    ("M4", 15.325, 28.252),  ("M9", 47.843, 26.590),   ("M12", 9.600, 64.914),
    ("M3", 6.361, -25.483),  ("M6", 38.669, -16.782), ("M11", 34.817, -51.463), ("M14", 72.120, -4.280),
    ("M5", -35.329, -12.187), ("M8", -16.064, -48.167), ("M13", -53.540, -43.504), ("M16", 2.219, -78.459),
]
NCH = 16
SLOT_ORDER = " ".join(m[0] for m in MICS)


# ---------------------------------------------------------------- geometry helpers
def speed_of_sound(t_c):
    return 331.3 + 0.606 * t_c


def wrap180(a):
    return (np.asarray(a, float) + 180.0) % 360.0 - 180.0


def unit(az, el):
    a, e = np.radians(az), np.radians(el)
    return np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])


def angular_error(az1, el1, az2, el2):
    c = float(unit(az1, el1) @ unit(az2, el2))
    return float(np.degrees(np.arccos(np.clip(c, -1, 1))))


def xyz_to_azel(x, y, z):
    """Array-frame truth. A flat array cannot see front/back, so z is folded to +|z|."""
    d = float(np.sqrt(x * x + y * y + z * z))
    return float(np.degrees(np.arctan2(y, x))), float(np.degrees(np.arcsin(abs(z) / d))), d


def azel_to_camera(az, el):
    """Setup A (board vertical, +x right, +y up, z forward): bearing theta (+ towards +x), vertical phi (+ up)."""
    u = unit(az, el)
    return float(np.degrees(np.arctan2(u[0], u[2]))), float(np.degrees(np.arcsin(np.clip(u[1], -1, 1))))


def position_to_xyz(setup, r, ang, h_src, h_board):
    """Setup A: r = horizontal range, ang = bearing theta.  Setup B: r = radius, ang = azimuth alpha."""
    a = np.radians(ang)
    if setup == "A":
        return r * np.sin(a), h_src - h_board, r * np.cos(a)
    return r * np.cos(a), r * np.sin(a), h_src - h_board


def mic_positions(flip_x=False, flip_y=False, rot=0.0):
    p = np.array([[x, y] for _, x, y in MICS], float) / 1000.0
    if flip_x: p[:, 0] *= -1
    if flip_y: p[:, 1] *= -1
    r = np.radians(rot)
    R = np.array([[np.cos(r), -np.sin(r)], [np.sin(r), np.cos(r)]])
    return np.c_[p @ R.T, np.zeros(NCH)]


# ---------------------------------------------------------------- beamformers
class Locator:
    """Narrow-band steered-response localizer on the strongest bins (tone + harmonics), far field.
    method: 'srp' = SRP-PHAT (default), 'das' = delay-and-sum power (no whitening),
            'music' = MUSIC on the strongest bins (covariance from short sub-frames).
    delays_s / gains: optional per-channel calibration (from estimate_calibration)."""

    def __init__(self, fs, nfft, band=(1500, 5000), topk=24, flip_x=False, flip_y=False, rot=0.0, temp_c=25.0,
                 az_step=2.0, el_step=3.0, method="srp", delays_s=None, gains=None, dyn_db=20.0):
        self.fs, self.nfft, self.topk, self.method, self.dyn_db = fs, nfft, topk, method, dyn_db
        self.c = speed_of_sound(temp_c)
        self.win = np.hanning(nfft).astype(np.float32)
        self.f = np.fft.rfftfreq(nfft, 1 / fs)
        hi = min(band[1], 0.45 * fs)
        self.band = np.where((self.f >= band[0]) & (self.f <= hi))[0]
        self.p = mic_positions(flip_x, flip_y, rot)
        self.az = np.arange(-180, 180, az_step)
        self.el = np.arange(0, 90 + 1e-9, el_step)
        self.proj = self._proj(self.az, self.el)
        self.delays = None if delays_s is None else np.asarray(delays_s, float)
        self.gains = None if gains is None else np.asarray(gains, float)

    def _proj(self, az, el):
        A, E = np.meshgrid(np.radians(az), np.radians(el))
        u = np.stack([np.cos(E) * np.cos(A), np.cos(E) * np.sin(A), np.sin(E)], -1).reshape(-1, 3)
        return (u @ self.p.T) / self.c

    def _correct(self, X, f):
        if self.delays is not None:
            X = X * np.exp(2j * np.pi * f[:, None] * self.delays[None])
        if self.gains is not None:
            X = X / self.gains[None]
        return X

    def _power(self, proj, fk, Xk, R=None):
        P = np.zeros(proj.shape[0])
        for i in range(len(fk)):
            A = np.exp(-2j * np.pi * fk[i] * proj)                    # (ndir,16) steering
            if self.method == "music":
                w, V = np.linalg.eigh(R[i])
                En = V[:, :-1]                                           # noise subspace (1 source)
                P += 1.0 / (np.sum(np.abs(A @ En) ** 2, 1) / NCH + 1e-12)   # A = conj(manifold): a^H En
            else:
                P += np.abs(A @ Xk[i]) ** 2
        return P

    def process(self, x):
        x = x.astype(np.float32)
        x = x - x.mean(0)
        rms = np.sqrt((x ** 2).mean(0))
        X = np.fft.rfft(x * self.win[:, None], axis=0)
        fb = self.f[self.band]
        Xb = self._correct(X[self.band], fb)
        pw = (np.abs(Xb) ** 2).mean(1)
        k = np.argsort(pw)[-self.topk:]
        snr = 10 * np.log10(pw[k].mean() / (np.median(pw) + 1e-12) + 1e-12)
        k = k[pw[k] >= pw[k].max() * 10 ** (-self.dyn_db / 10)]          # only bins that carry the source
        fk = fb[k]
        R = None
        if self.method == "srp":
            Xk = Xb[k] / (np.abs(Xb[k]) + 1e-12)
        elif self.method == "das":
            Xk = Xb[k]
        else:                                                            # MUSIC: covariance per bin from 8 sub-frames
            n = self.nfft // 4
            hop = (x.shape[0] - n) // 7
            wsub = np.hanning(n)
            fs_sub = np.fft.rfftfreq(n, 1 / self.fs)
            S = np.stack([np.fft.rfft(x[i * hop:i * hop + n] * wsub[:, None], axis=0) for i in range(8)])  # (8,nb,16)
            idx = np.unique(np.argmin(np.abs(fs_sub[None] - fk[:, None]), 1))
            fk = fs_sub[idx]
            S = self._correct(S[:, idx].reshape(-1, NCH), np.repeat(fk[None], 8, 0).ravel()).reshape(8, len(idx), NCH)
            R = np.einsum("tkm,tkn->kmn", S, S.conj()) / 8
            Xk = None
        P = self._power(self.proj, fk, Xk, R).reshape(len(self.el), len(self.az))
        ie, ia = np.unravel_index(np.argmax(P), P.shape)
        faz = self.az[ia] + np.arange(-3, 3.01, 0.5)
        fel = np.unique(np.clip(self.el[ie] + np.arange(-4, 4.01, 0.5), 0, 90))
        Pf = self._power(self._proj(faz, fel), fk, Xk, R).reshape(len(fel), len(faz))
        je, ja = np.unravel_index(np.argmax(Pf), Pf.shape)
        return dict(az=float(wrap180(faz[ja])), el=float(fel[je]), snr=float(snr), map=P / P.max(),
                    tone=float(fk[np.argmax(pw[k])]) if self.method != "music" else float(fk[-1]),
                    peak=float(P.max() / P.mean()), level_db=20 * np.log10(rms / 32768.0 + 1e-12))


def estimate_calibration(x, fs, band=(1000, 5000), nfft=4096):
    """From a broadside recording (source at theta = 0, phi = 0, all mics equidistant):
    per-channel delay (s, relative to the array mean) and gain (relative to the median)."""
    x = x.astype(np.float64) - x.mean(0)
    hop = nfft // 2
    f = np.fft.rfftfreq(nfft, 1 / fs)
    b = np.where((f >= band[0]) & (f <= band[1]))[0]
    C = np.zeros((len(b), NCH), complex); Pm = np.zeros((len(b), NCH))
    w = np.hanning(nfft)
    for s in range(0, x.shape[0] - nfft, hop):
        X = np.fft.rfft(x[s:s + nfft] * w[:, None], axis=0)[b]
        ref = X.mean(1, keepdims=True)
        C += X * ref.conj(); Pm += np.abs(X) ** 2
    wgt = np.abs(C).sum(1)
    use = wgt > np.percentile(wgt, 70)                                   # bins with real signal (tones)
    delays = np.zeros(NCH)
    for m in range(NCH):
        ph = np.angle(C[use, m])
        fw = f[b][use]
        delays[m] = -np.sum(wgt[use] * ph * fw) / (2 * np.pi * np.sum(wgt[use] * fw * fw))   # LS slope through 0
    delays -= delays.mean()
    g = np.sqrt(Pm[use].sum(0))
    gains = g / np.median(g)
    return delays, gains


# ---------------------------------------------------------------- files
def write_wav(path, data, fs):
    data = np.asarray(data, np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(data.shape[1]); w.setsampwidth(2); w.setframerate(int(fs))
        w.writeframes(data.tobytes())


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        fs, nch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        x = np.frombuffer(w.readframes(n), "<i2").reshape(-1, nch)
    return x, fs


def save_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, default=float)
