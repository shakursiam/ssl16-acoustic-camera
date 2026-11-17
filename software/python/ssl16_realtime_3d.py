#!/usr/bin/env python3
"""
SSL-16 real-time buzzer localiser with a live 3-D view
======================================================
Reads the 16-channel stream from the board (firmware SSL16_Stream.ino: 'SSL6' packets,
16 x int16 per frame, 12 kHz after the on-board 48 kHz -> 12 kHz decimation), finds the buzzer
on the ground, and shows its position in 3-D in real time.

Hardware setup
  * array centre HEIGHT m above the ground, board vertical, its face (normal) parallel to the ground
  * board frame (GitHub docs/microphone_array.md): +x right, +y up, +z out of the sound-hole face
  * buzzers on the ground, one at a time, in x = X_RANGE, z = Z_RANGE

Pipeline (best parts of beamforming.py and the SSL-16 GUI)
  1. Welch-averaged cross-spectral matrix over the last WINDOW_S seconds         (beamforming.py)
  2. only the strongest bins in FBAND (tone + harmonics, within BIN_DB of the peak) (GUI)
  3. SNR gate: no estimate unless the tone stands SNR_DB above the band median   (GUI)
  4. PHAT weighting C/|C| + diagonal removal                                     (GUI + beamforming.py)
  5. near-field (spherical) steering searched directly on the ground plane,      (beamforming.py)
     so the output is the buzzer's x, z coordinates, not just a direction
  6. speed of sound from air temperature                                        (GUI)
  7. coarse grid, then fine grid + parabolic refinement around the peak         (GUI)
  8. median of the last few detections for a steady display; packet-gap check    (GUI)

Install once:  pip install numpy matplotlib pyserial
Run:
  python ssl16_realtime_3d.py --port COM5                 board on COM5 (Linux: /dev/ttyACM0)
  python ssl16_realtime_3d.py --port COM5 --true 0.3 1.2  also show the measured true position + error
  python ssl16_realtime_3d.py --port COM5 --log run.csv   log every detection to a CSV file
  python ssl16_realtime_3d.py --file capture.bin          replay a saved stream (SSL6 packets or raw int16)
  python ssl16_realtime_3d.py --demo                      no board: synthetic buzzer that moves around
Close the Arduino Serial Monitor first: only one program can open the port.
"""
import argparse, collections, csv, struct, threading, time
import numpy as np

# ================================================================== configuration
FS = 12000                      # Hz, stream rate (48 kHz decimated by 4 on the ESP32)
HEIGHT = 1.0                    # m, array centre above the ground
X_RANGE = (-0.8, 0.8)           # m, buzzer area across the board (board +x)
Z_RANGE = (0.6, 2.0)            # m, buzzer area in front of the board (along its normal)
MARGIN = 0.3                    # m, search this far beyond the area (an edge hit = suspicious)
COARSE = 0.04                   # m, coarse grid spacing
FINE = 0.005                    # m, fine grid spacing around the coarse peak
FBAND = (1500.0, 4500.0)        # Hz, array band (1.5 kHz) to the firmware filter's flat edge
NFFT = 1024                     # 85 ms snapshots, 11.7 Hz bins at 12 kHz
WINDOW_S = 0.5                  # s of audio per estimate (~11 snapshots, 50 % overlap)
UPDATE_S = 0.2                  # s between estimates / screen updates
TOPK = 12                       # strongest bins used (tone + harmonics) ...
BIN_DB = 20.0                   # ... but only those within this many dB of the strongest bin
SNR_DB = 10.0                   # detection threshold
SMOOTH = 5                      # median over this many detections for the displayed point
TEMP_C = 30.0                   # air temperature, deg C

# TDM slot 0..15 -> (name, x_mm, y_mm); GitHub docs/adc_configuration.md, microphone_array.md
MICS = [
    ("MK2", -16.122, 10.668), ("MK7", -18.989, 42.553), ("MK10", -56.913, 13.588), ("MK15", -52.491, 54.144),
    ("MK1", 9.877, 1.564),    ("MK4", 15.325, 28.252),  ("MK9", 47.843, 26.590),   ("MK12", 9.600, 64.914),
    ("MK3", 6.361, -25.483),  ("MK6", 38.669, -16.782), ("MK11", 34.817, -51.463), ("MK14", 72.120, -4.280),
    ("MK5", -35.329, -12.187), ("MK8", -16.064, -48.167), ("MK13", -53.540, -43.504), ("MK16", 2.219, -78.459),
]
NCH = 16
MIC_POS = np.array([[x / 1000, y / 1000, 0.0] for _, x, y in MICS])   # board frame, metres


def speed_of_sound(t_c):
    return 331.3 * np.sqrt(1 + t_c / 273.15)


# ================================================================== localiser
class Locator:
    def __init__(self, fs=FS, temp_c=TEMP_C, height=HEIGHT):
        self.fs, self.c, self.h = fs, speed_of_sound(temp_c), height
        self.win = np.hanning(NFFT)
        f = np.fft.rfftfreq(NFFT, 1 / fs)
        self.band = np.where((f >= FBAND[0]) & (f <= min(FBAND[1], 0.45 * fs)))[0]
        self.f = f
        self.xs = np.arange(X_RANGE[0] - MARGIN, X_RANGE[1] + MARGIN + 1e-9, COARSE)
        self.zs = np.arange(max(0.1, Z_RANGE[0] - MARGIN), Z_RANGE[1] + MARGIN + 1e-9, COARSE)
        X, Z = np.meshgrid(self.xs, self.zs)
        self.r_coarse = self._dist(X.ravel(), Z.ravel())               # (G, 16) metres

    def _dist(self, x, z):
        pts = np.column_stack([x, np.full(len(x), -self.h), z])        # ground: y = -HEIGHT
        return np.linalg.norm(pts[:, None, :] - MIC_POS[None], axis=-1)

    def _srp(self, r, fk, C):
        """sum over bins of u^H C u with phase-only near-field steering u_m = exp(-j k r_m)."""
        B = np.zeros(r.shape[0])
        for f, Ck in zip(fk, C):
            U = np.exp(-2j * np.pi * f * r / self.c)                    # (G, 16)
            B += np.real(np.einsum("gm,mn,gn->g", U.conj(), Ck, U))
        return B

    def process(self, x):
        """x: (N, 16) int16 frames -> dict with the estimate, quality and the coarse map."""
        x = x.astype(float)
        x -= x.mean(0)
        level_db = 20 * np.log10(np.sqrt((x ** 2).mean(0)) / 32768 + 1e-12)
        hop = NFFT // 2
        nsnap = 1 + (len(x) - NFFT) // hop
        if nsnap < 2:
            return None
        idx = np.arange(NFFT)[None] + hop * np.arange(nsnap)[:, None]
        X = np.fft.rfft(x[idx] * self.win[None, :, None], axis=1)[:, self.band, :]   # (T, F, 16)

        pw = np.mean(np.abs(X) ** 2, axis=(0, 2))
        k = np.argsort(pw)[-TOPK:]
        snr = float(10 * np.log10(pw[k].mean() / (np.median(pw) + 1e-30) + 1e-30))
        # PHAT gives every bin equal weight, so drop bins far below the tone (noise-only bins)
        k = k[pw[k] >= pw.max() * 10 ** (-BIN_DB / 10)]
        fk = self.f[self.band][k]
        Xk = X[:, k, :]
        C = np.einsum("tfm,tfn->fmn", Xk, Xk.conj()) / nsnap                # Welch CSM
        C = C / np.maximum(np.abs(C), 1e-30)                               # PHAT
        d = np.arange(NCH)
        C[:, d, d] = 0                                                     # diagonal removal

        Bc = self._srp(self.r_coarse, fk, C)
        ig = np.argmax(Bc)
        iz, ix = np.unravel_index(ig, (len(self.zs), len(self.xs)))
        fx = self.xs[ix] + np.arange(-2 * COARSE, 2 * COARSE + 1e-9, FINE)
        fz = self.zs[iz] + np.arange(-2 * COARSE, 2 * COARSE + 1e-9, FINE)
        FX, FZ = np.meshgrid(fx, fz)
        Bf = self._srp(self._dist(FX.ravel(), FZ.ravel()), fk, C).reshape(FZ.shape)
        jz, jx = np.unravel_index(np.argmax(Bf), Bf.shape)

        def parab(a, b, c):
            den = a - 2 * b + c
            return 0.0 if den == 0 else float(np.clip(0.5 * (a - c) / den, -1, 1))

        dx = parab(*Bf[jz, jx - 1:jx + 2]) if 0 < jx < len(fx) - 1 else 0.0
        dz = parab(*Bf[jz - 1:jz + 2, jx]) if 0 < jz < len(fz) - 1 else 0.0
        xe, ze = fx[jx] + dx * FINE, fz[jz] + dz * FINE
        coherence = float(Bf.max() / (len(fk) * NCH * (NCH - 1)))         # 1 = perfect single source
        edge = ix in (0, len(self.xs) - 1) or iz in (0, len(self.zs) - 1)
        return dict(x=float(xe), z=float(ze), snr=snr, coherence=coherence, edge=edge,
                    tone=float(fk[np.argmax(pw[k])]), level_db=level_db,
                    map=Bc.reshape(len(self.zs), len(self.xs)))


# ================================================================== data sources
class Ring:
    """Thread-safe buffer of the most recent frames."""
    def __init__(self, n):
        self.buf = np.zeros((n, NCH), np.int16)
        self.n, self.filled, self.lock = n, 0, threading.Lock()

    def push(self, d):
        with self.lock:
            m = len(d)
            if m >= self.n:
                self.buf[:] = d[-self.n:]
            else:
                self.buf = np.roll(self.buf, -m, axis=0)
                self.buf[-m:] = d
            self.filled = min(self.n, self.filled + m)

    def clear(self):
        with self.lock:
            self.filled = 0

    def get(self):
        with self.lock:
            return self.buf.copy() if self.filled >= self.n else None


def parse_ssl6(buf):
    """Yield (seq, frames) from a bytearray, consuming what was parsed."""
    while True:
        i = buf.find(b"SSL6")
        if i < 0:
            del buf[:-3]
            return
        del buf[:i]
        if len(buf) < 12:
            return
        seq, ns, nc = struct.unpack_from("<IHH", buf, 4)
        if nc != NCH or not 0 < ns <= 4096:
            del buf[:4]
            continue
        n = 12 + ns * nc * 2
        if len(buf) < n:
            return
        data = np.frombuffer(bytes(buf[12:n]), "<i2").reshape(ns, nc)
        del buf[:n]
        yield seq, data


class SerialSource(threading.Thread):
    def __init__(self, port, ring):
        super().__init__(daemon=True)
        import serial
        self.ser = serial.Serial(port, 2000000, timeout=0.2)
        self.ring, self.running = ring, True
        self.packets = self.gaps = 0
        self.error, self.last_seq = None, None

    def run(self):
        buf = bytearray()
        try:
            while self.running:
                buf += self.ser.read(16384)
                for seq, data in parse_ssl6(buf):
                    if self.last_seq is not None and seq != (self.last_seq + 1) & 0xFFFFFFFF:
                        self.gaps += 1
                        self.ring.clear()                  # never beamform across a gap
                    self.last_seq = seq
                    self.packets += 1
                    self.ring.push(data)
        except Exception as e:
            self.error = str(e)

    def stop(self):
        self.running = False
        try:
            self.ser.close()
        except Exception:
            pass


class FileSource(threading.Thread):
    """Replays a saved stream in real time: SSL6 packets, or plain interleaved int16 frames."""
    def __init__(self, path, ring, fs=FS):
        super().__init__(daemon=True)
        raw = bytearray(open(path, "rb").read())
        if raw.find(b"SSL6") >= 0:
            self.data = np.concatenate([d for _, d in parse_ssl6(raw)])
        else:
            self.data = np.frombuffer(bytes(raw[:len(raw) // 32 * 32]), "<i2").reshape(-1, NCH)
        self.ring, self.fs, self.running = ring, fs, True
        self.packets = self.gaps = 0
        self.error = None

    def run(self):
        n = self.fs // 100
        for i in range(0, len(self.data), n):
            if not self.running:
                break
            self.ring.push(self.data[i:i + n])
            self.packets += 1
            time.sleep(n / self.fs)
        self.error = "end of file"

    def stop(self):
        self.running = False


class DemoSource(threading.Thread):
    """Synthetic buzzer on the ground: 1.5 s on, 0.7 s off, then jumps to a new random spot."""
    def __init__(self, ring, fs=FS, temp_c=TEMP_C, height=HEIGHT, seed=1):
        super().__init__(daemon=True)
        self.ring, self.fs, self.c, self.h = ring, fs, speed_of_sound(temp_c), height
        self.rng = np.random.default_rng(seed)
        self.running, self.packets, self.gaps, self.error = True, 0, 0, None
        self.t = 0.0
        self._new_spot()

    def _new_spot(self):
        self.pos = np.array([self.rng.uniform(*X_RANGE), -self.h, self.rng.uniform(*Z_RANGE)])
        self.f0 = self.rng.uniform(2300, 3400)
        self.t_start = self.t

    def frames(self, n):
        t = self.t + np.arange(n)[:, None] / self.fs
        r = np.linalg.norm(MIC_POS - self.pos, axis=1)[None]
        ph = 2 * np.pi * self.f0 * (t - r / self.c)
        on = ((t - self.t_start) % 2.2) < 1.5
        x = self.rng.normal(0, 40, (n, NCH)) + on * 3000 * (np.sin(ph) + 0.3 * np.sin(2 * ph + 0.7) * (2 * self.f0 < 4500)) / r
        self.t += n / self.fs
        if self.t - self.t_start > 2.2 * 2:
            self._new_spot()
        return np.clip(x, -32768, 32767).astype(np.int16)

    def run(self):
        n = self.fs // 100
        while self.running:
            self.ring.push(self.frames(n))
            self.packets += 1
            time.sleep(n / self.fs)

    def stop(self):
        self.running = False


# ================================================================== 3-D live view
def run_view(src, ring, loc, true_xz=None, log_path=None):
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    # plot frame: X = across (board x), Y = forward (board z), Z = height above ground (board y + HEIGHT)
    fig = plt.figure(figsize=(13, 6.5))
    ax = fig.add_subplot(1, 2, 1, projection="3d")
    axm = fig.add_subplot(1, 2, 2)

    xa, za = (X_RANGE[0] - MARGIN, X_RANGE[1] + MARGIN), (0.0, Z_RANGE[1] + MARGIN)
    ax.set_xlim(*xa); ax.set_ylim(*za); ax.set_zlim(0, HEIGHT + 0.3)
    ax.set_box_aspect((xa[1] - xa[0], za[1] - za[0], HEIGHT + 0.3))
    ax.set_xlabel("x [m]  (across)"); ax.set_ylabel("z [m]  (forward)"); ax.set_zlabel("height [m]")
    gx = [X_RANGE[0], X_RANGE[1], X_RANGE[1], X_RANGE[0], X_RANGE[0]]
    gz = [Z_RANGE[0], Z_RANGE[0], Z_RANGE[1], Z_RANGE[1], Z_RANGE[0]]
    ax.plot(gx, gz, [0] * 5, color="0.5", lw=1, ls="--")                       # buzzer area
    bx = np.array([-0.115, 0.115, 0.115, -0.115, -0.115])                     # 230 x 170 mm board
    by = np.array([-0.085, -0.085, 0.085, 0.085, -0.085])
    ax.plot(bx, [0] * 5, HEIGHT + by, color="0.3", lw=1.5)
    ax.plot(MIC_POS[:, 0], np.zeros(NCH), HEIGHT + MIC_POS[:, 1], "k.", ms=4)
    ax.plot([0, 0], [0, 0], [0, HEIGHT], color="0.6", lw=1)                    # mounting pole
    trail, = ax.plot([], [], [], "o", color="0.7", ms=4)
    beam, = ax.plot([], [], [], color="tab:red", lw=1, alpha=0.6)
    drop, = ax.plot([], [], [], color="tab:red", lw=0.8, ls=":")
    est, = ax.plot([], [], [], "o", color="tab:red", ms=11)
    if true_xz:
        ax.plot([true_xz[0]], [true_xz[1]], [0], "*", color="tab:green", ms=16, label="true")
    title = ax.set_title("waiting for data...", fontsize=11)

    img = axm.imshow(np.zeros((len(loc.zs), len(loc.xs))), origin="lower", cmap="inferno", vmin=-12, vmax=0,
                     extent=(loc.xs[0], loc.xs[-1], loc.zs[0], loc.zs[-1]), aspect="equal")
    axm.plot(gx, gz, "w--", lw=0.8)
    m_est, = axm.plot([], [], "o", mfc="none", mec="cyan", ms=12, mew=2)
    if true_xz:
        axm.plot(*true_xz, "*", color="lime", ms=14)
    axm.set_xlabel("x [m]  (across)"); axm.set_ylabel("z [m]  (forward)")
    axm.set_title("ground beam map (SRP-PHAT, dB)", fontsize=10)
    fig.colorbar(img, ax=axm, fraction=0.04)
    info = fig.text(0.01, 0.01, "", fontsize=9, family="monospace")

    hist = collections.deque(maxlen=SMOOTH)
    trail_pts = collections.deque(maxlen=40)
    logf = open(log_path, "a", newline="") if log_path else None
    logw = csv.writer(logf) if logf else None
    if logw and logf.tell() == 0:
        logw.writerow(["time", "x", "z", "x_smooth", "z_smooth", "snr_db", "coherence", "tone_hz"])

    def update(_):
        x = ring.get()
        status = f"packets {src.packets}  gaps {src.gaps}" + (f"  [{src.error}]" if src.error else "")
        if x is None:
            info.set_text(status + "  | filling buffer"); return
        r = loc.process(x)
        if r is None:
            return
        img.set_data(10 * np.log10(np.maximum(r["map"] / max(r["map"].max(), 1e-30), 10 ** -1.2)))
        det = r["snr"] >= SNR_DB
        if det:
            hist.append((r["x"], r["z"]))
            trail_pts.append((r["x"], r["z"]))
            xs_, zs_ = np.median(np.array(hist), axis=0)
            est.set_data_3d([xs_], [zs_], [0])
            drop.set_data_3d([xs_, xs_], [zs_, zs_], [0, 0.15])
            beam.set_data_3d([0, xs_], [0, zs_], [HEIGHT, 0])
            m_est.set_data([xs_], [zs_])
            tp = np.array(trail_pts)
            trail.set_data_3d(tp[:, 0], tp[:, 1], np.zeros(len(tp)))
            txt = f"BUZZER  x = {xs_:+.3f} m   z = {zs_:.3f} m"
            if true_xz:
                txt += f"   error {np.hypot(xs_ - true_xz[0], zs_ - true_xz[1]) * 100:.1f} cm"
            if r["edge"]:
                txt += "   (at search edge!)"
            title.set_text(txt); title.set_color("tab:red")
            if logw:
                logw.writerow([time.strftime("%H:%M:%S"), f"{r['x']:.4f}", f"{r['z']:.4f}", f"{xs_:.4f}",
                               f"{zs_:.4f}", f"{r['snr']:.1f}", f"{r['coherence']:.3f}", f"{r['tone']:.0f}"])
                logf.flush()
        else:
            hist.clear()
            est.set_data_3d([], [], []); beam.set_data_3d([], [], []); drop.set_data_3d([], [], [])
            m_est.set_data([], [])
            title.set_text("no buzzer detected"); title.set_color("0.4")
        lv = r["level_db"]
        info.set_text(f"{status} | tone {r['tone']:.0f} Hz  SNR {r['snr']:.1f} dB  coherence {r['coherence']:.2f}"
                      f" | mic level {lv.min():.0f}..{lv.max():.0f} dBFS | c = {loc.c:.1f} m/s")

    anim = FuncAnimation(fig, update, interval=int(UPDATE_S * 1000), cache_frame_data=False)
    fig.tight_layout()
    try:
        plt.show()
    finally:
        src.stop()
        if logf:
            logf.close()
    return anim


# ================================================================== main
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="SSL-16 real-time 3-D buzzer localiser")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--port", help="serial port of the board, e.g. COM5 or /dev/ttyACM0")
    g.add_argument("--file", help="replay a saved stream")
    g.add_argument("--demo", action="store_true", help="synthetic buzzer, no board needed")
    ap.add_argument("--temp", type=float, default=TEMP_C, help="air temperature, deg C")
    ap.add_argument("--height", type=float, default=HEIGHT, help="array centre above ground, m")
    ap.add_argument("--true", type=float, nargs=2, metavar=("X", "Z"), help="measured buzzer position, m")
    ap.add_argument("--log", help="append detections to this CSV file")
    a = ap.parse_args()

    HEIGHT = a.height
    ring = Ring(int(WINDOW_S * FS))
    loc = Locator(FS, a.temp, a.height)
    if a.port:
        src = SerialSource(a.port, ring)
    elif a.file:
        src = FileSource(a.file, ring)
    else:
        src = DemoSource(ring, temp_c=a.temp, height=a.height)
    src.start()
    run_view(src, ring, loc, true_xz=a.true, log_path=a.log)
