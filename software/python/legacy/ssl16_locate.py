#!/usr/bin/env python3
"""
SSL-16 buzzer localizer — SRP-PHAT beamforming on the 16-mic spiral array.

Live:      python ssl16_locate.py --port COM19
Record:    python ssl16_locate.py --port COM19 --save run1.npy
Replay:    python ssl16_locate.py --replay run1.npy
Self-test: python ssl16_locate.py --simulate 40 30      (no board needed)

Needs:  pip install numpy pyserial matplotlib

Direction convention (array frame = revC1 table):
  azimuth   0 deg = +x axis of the mic table, 90 deg = +y axis (counter-clockwise)
  elevation 90 deg = straight out of the board face (broadside), 0 deg = in the board plane
A flat array cannot tell front from back: a source behind the board gives the same answer.
Check the frame once with --flip-x / --flip-y / --rot (see the test plan).
"""
import argparse, struct, sys, threading, time, collections
import numpy as np

# ---------------- array geometry: TDM slot order 0..15 (revD port-channel table), mm ----------------
MICS = [  # slot: (name, x_mm, y_mm)
    ("M2", -16.122, 10.668), ("M7", -18.989, 42.553), ("M10", -56.913, 13.588), ("M15", -52.491, 54.144),
    ("M1", 9.877, 1.564),    ("M4", 15.325, 28.252),  ("M9", 47.843, 26.590),   ("M12", 9.600, 64.914),
    ("M3", 6.361, -25.483),  ("M6", 38.669, -16.782), ("M11", 34.817, -51.463), ("M14", 72.120, -4.280),
    ("M5", -35.329, -12.187), ("M8", -16.064, -48.167), ("M13", -53.540, -43.504), ("M16", 2.219, -78.459),
]
FS = 12000            # stream rate after decimation on the ESP32
NCH = 16
C_SOUND = 343.0       # m/s at ~20 C (use 347 at 30 C)

# ---------------- serial reader ----------------
MAGIC = b"SSL6"

class Reader(threading.Thread):
    """Reads packets from the ESP32, appends int16 samples (n,16) to a deque."""
    def __init__(self, port, save=None):
        super().__init__(daemon=True)
        import serial
        self.ser = serial.Serial(port, 2000000, timeout=0.5)
        self.q = collections.deque()
        self.lock = threading.Lock()
        self.last_seq = None
        self.drops = 0
        self.packets = 0
        self.save = save
        self.saved = []

    def run(self):
        buf = bytearray()
        while True:
            buf += self.ser.read(8192)
            while True:
                i = buf.find(MAGIC)
                if i < 0:
                    del buf[:-3]
                    break
                if len(buf) < i + 12:
                    break
                seq, ns, nc = struct.unpack_from("<IHH", buf, i + 4)
                n = 12 + ns * nc * 2
                if nc != NCH or ns == 0 or ns > 2000:
                    del buf[:i + 4]
                    continue
                if len(buf) < i + n:
                    break
                data = np.frombuffer(bytes(buf[i + 12:i + n]), dtype="<i2").reshape(ns, nc)
                del buf[:i + n]
                if self.last_seq is not None and seq != (self.last_seq + 1) & 0xFFFFFFFF:
                    self.drops += 1
                    with self.lock:
                        self.q.clear()          # gap in time -> restart the analysis window
                self.last_seq = seq
                self.packets += 1
                with self.lock:
                    self.q.append(data)
                if self.save is not None:
                    self.saved.append(data)

    def take(self, n):
        """Return (n,16) samples once available, else None. Keeps the overlap outside."""
        with self.lock:
            have = sum(d.shape[0] for d in self.q)
            if have < n:
                return None
            out = np.concatenate(list(self.q), axis=0)
            self.q.clear()
        rest = out[n:]
        if len(rest):
            with self.lock:
                self.q.appendleft(rest)
        return out[:n]

# ---------------- SRP-PHAT ----------------
class Locator:
    def __init__(self, nfft=2048, band=(1500, 5000), topk=24, az_step=2, el_step=3,
                 flip_x=False, flip_y=False, rot=0.0):
        self.nfft = nfft
        self.win = np.hanning(nfft).astype(np.float32)
        self.f = np.fft.rfftfreq(nfft, 1 / FS)
        self.band = np.where((self.f >= band[0]) & (self.f <= band[1]))[0]
        self.topk = topk
        p = np.array([[x, y] for _, x, y in MICS], dtype=np.float64) / 1000.0
        if flip_x: p[:, 0] *= -1
        if flip_y: p[:, 1] *= -1
        r = np.radians(rot)
        p = p @ np.array([[np.cos(r), np.sin(r)], [-np.sin(r), np.cos(r)]])
        self.p = np.c_[p, np.zeros(NCH)]                      # mics at z = 0
        self.az = np.arange(-180, 180, az_step, dtype=np.float64)
        self.el = np.arange(0, 90 + 1e-9, el_step, dtype=np.float64)
        A, E = np.meshgrid(np.radians(self.az), np.radians(self.el))   # (nel, naz)
        u = np.stack([np.cos(E) * np.cos(A), np.cos(E) * np.sin(A), np.sin(E)], -1).reshape(-1, 3)
        self.proj = (u @ self.p.T) / C_SOUND                   # (ndir, 16): arrival lead in s

    def process(self, x):
        """x: (nfft,16) int16/float. Returns dict with az, el, snr_db, map, freq."""
        x = x.astype(np.float32)
        x -= x.mean(0)
        X = np.fft.rfft(x * self.win[:, None], axis=0)         # (nbin,16)
        Xb = X[self.band]
        pw = (np.abs(Xb) ** 2).mean(1)                           # band power per bin
        k = np.argsort(pw)[-self.topk:]                          # strongest bins (buzzer + harmonics)
        snr = 10 * np.log10(pw[k].mean() / (np.median(pw) + 1e-12) + 1e-12)
        Xk = Xb[k]                                               # (K,16)
        Xk = Xk / (np.abs(Xk) + 1e-12)                           # PHAT weighting
        fk = self.f[self.band][k]
        P = np.zeros(self.proj.shape[0])
        for i in range(len(k)):                                  # sum over bins of |steered sum|^2
            steer = np.exp(-2j * np.pi * fk[i] * self.proj)      # (ndir,16)
            P += np.abs(steer @ Xk[i]) ** 2
        P = P.reshape(len(self.el), len(self.az))
        ie, ia = np.unravel_index(np.argmax(P), P.shape)
        return dict(az=self.az[ia], el=self.el[ie], snr_db=snr, map=P / P.max(),
                    freq=fk[np.argmax(pw[k])], peak_ratio=P.max() / P.mean())

    def process_transient(self, seg, band=(1000, 5500)):
        """Broadband SRP-PHAT over ALL bins in band, for a short segment (clap / snap)."""
        n = seg.shape[0]
        x = seg.astype(np.float32)
        x -= x.mean(0)
        w = np.ones(n, np.float32)                               # Tukey: flat, short tapers
        t = max(4, n // 16)
        w[:t] = 0.5 - 0.5 * np.cos(np.pi * np.arange(t) / t)
        w[-t:] = w[:t][::-1]
        X = np.fft.rfft(x * w[:, None], axis=0)
        f = np.fft.rfftfreq(n, 1 / FS)
        b = np.where((f >= band[0]) & (f <= band[1]))[0]
        Xb = X[b] / (np.abs(X[b]) + 1e-12)                        # PHAT
        fb = f[b]
        P = np.zeros(self.proj.shape[0])
        for i in range(0, len(b), 16):                           # chunks of bins
            ph = np.exp(-2j * np.pi * fb[i:i + 16, None, None] * self.proj[None])   # (k,ndir,16)
            P += (np.abs(np.einsum("kdm,km->kd", ph, Xb[i:i + 16])) ** 2).sum(0)
        P = P.reshape(len(self.el), len(self.az))
        ie, ia = np.unravel_index(np.argmax(P), P.shape)
        return dict(az=self.az[ia], el=self.el[ie], map=P / P.max(), peak_ratio=P.max() / P.mean())


class ClapDetector:
    """Onset detector: high-passed energy per hop vs a slowly tracked noise floor."""
    def __init__(self, hop=256, thr_db=15.0, seg=256, pre=16, holdoff_s=0.4):
        self.hop, self.thr, self.seg, self.pre = hop, thr_db, seg, pre
        self.holdoff = int(holdoff_s * FS / hop)
        self.L = 4 * hop + seg
        self.buf = np.zeros((self.L, NCH), np.float32)           # recent history
        self.total = 0                                           # samples pushed so far
        self.floor = None
        self.wait = 0
        self.n = 0
        self.pending = None                                      # absolute start of a segment to cut

    def push(self, block):
        """block: (hop,16). Returns (segment or None, energy dB). Segment starts just before an onset."""
        self.buf = np.concatenate([self.buf[block.shape[0]:], block.astype(np.float32)])
        self.total += block.shape[0]
        self.n += 1
        d = np.diff(self.buf[-self.hop - 1:], axis=0)            # first difference = simple high-pass
        e_db = 10 * np.log10((d ** 2).mean() + 1e-9)
        if self.floor is None:
            self.floor = e_db
        out = None
        if self.pending is not None and self.total >= self.pending + self.seg:
            off = self.L - (self.total - self.pending)
            out = self.buf[off:off + self.seg].copy()
            self.pending = None
        if self.wait > 0:
            self.wait -= 1
            return out, e_db
        if e_db > self.floor + self.thr and self.n > 20:
            # onset = first sample in the last two hops where the envelope reaches 30% of its peak
            win = np.abs(np.diff(self.buf[-2 * self.hop - 1:], axis=0)).max(1)
            on = int(np.argmax(win >= 0.3 * win.max()))
            self.pending = self.total - 2 * self.hop + on - self.pre
            self.wait = self.holdoff
            if self.total >= self.pending + self.seg:            # already have enough samples
                off = self.L - (self.total - self.pending)
                out = self.buf[off:off + self.seg].copy()
                self.pending = None
            return out, e_db
        self.floor += 0.05 * (e_db - self.floor)                 # track background only when quiet
        return out, e_db

# ---------------- simulation (checks geometry/sign conventions) ----------------
def simulate(az, el, n, f0=2800.0, snr_db=20, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n) / FS
    a, e = np.radians(az), np.radians(el)
    u = np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])
    p = np.c_[np.array([[x, y] for _, x, y in MICS]) / 1000.0, np.zeros(NCH)]
    lead = p @ u / C_SOUND                                       # mic closer to source hears it earlier
    x = np.zeros((n, NCH))
    for m in range(NCH):
        tt = t + lead[m]
        x[:, m] = np.sin(2 * np.pi * f0 * tt) + 0.4 * np.sin(2 * np.pi * 2 * f0 * tt)
    x += rng.normal(0, 10 ** (-snr_db / 20), x.shape)
    return (x * 8000).astype(np.int16)

def simulate_clap(az, el, n=FS * 2, t0=1.0, refl=(120.0, 10.0, 0.6, 0.006), noise=60, seed=0):
    """Snap = 4 ms decaying noise burst at t0 from (az,el) + one wall reflection
    (az_r, el_r, gain, extra delay s). Fractional delays done in the frequency domain."""
    rng = np.random.default_rng(seed)
    burst = rng.normal(0, 1, int(0.004 * FS)) * np.exp(-np.arange(int(0.004 * FS)) / (0.001 * FS))
    s = np.zeros(n); i0 = int(t0 * FS); s[i0:i0 + burst.size] = burst * 6000
    p = np.c_[np.array([[x, y] for _, x, y in MICS]) / 1000.0, np.zeros(NCH)]
    f = np.fft.rfftfreq(n, 1 / FS); S = np.fft.rfft(s)
    def uvec(a, e):
        a, e = np.radians(a), np.radians(e)
        return np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])
    X = np.zeros((f.size, NCH), complex)
    for (a, e, g, dly) in [(az, el, 1.0, 0.0), refl]:
        lead = p @ uvec(a, e) / C_SOUND - dly
        X += g * S[:, None] * np.exp(2j * np.pi * f[:, None] * lead[None])
    x = np.fft.irfft(X, n, axis=0) + rng.normal(0, noise, (n, NCH))
    return np.clip(x, -32768, 32767).astype(np.int16)

# ---------------- clap / snap mode ----------------
def run_clap(a, loc, hop=256, seg=256):
    det = ClapDetector(hop=hop, thr_db=a.clap_thr, seg=seg)
    band = (1000, 5500)

    if a.simulate:
        x = simulate_clap(a.simulate[0], a.simulate[1])
        for s in range(0, x.shape[0] - hop + 1, hop):
            sg, _ = det.push(x[s:s + hop])
            if sg is not None:
                r = loc.process_transient(sg, band)
                print(f"true az {a.simulate[0]:.0f} el {a.simulate[1]:.0f}  ->  est az {r['az']:.0f} "
                      f"el {r['el']:.0f}  peak/mean {r['peak_ratio']:.1f}")
        return

    if a.replay:
        data = np.load(a.replay)
        src = (data[s:s + hop] for s in range(0, data.shape[0] - hop + 1, hop))
        rd = None
    elif a.port:
        rd = Reader(a.port, save=a.save); rd.start()
        def gen():
            while True:
                b = rd.take(hop)
                if b is None:
                    time.sleep(0.005); continue
                yield b
        src = gen()
    else:
        print("give --port, --replay or --simulate"); return

    plot = not a.no_plot
    if plot:
        import matplotlib.pyplot as plt
        plt.ion()
        fig = plt.figure(figsize=(11, 4.6))
        ax1 = fig.add_subplot(1, 2, 1)
        img = ax1.imshow(np.zeros((len(loc.el), len(loc.az))), origin="lower", aspect="auto",
                         extent=[loc.az[0], loc.az[-1], loc.el[0], loc.el[-1]], vmin=0, vmax=1, cmap="magma")
        mark, = ax1.plot([], [], "c+", ms=18, mew=2)
        ax1.set_xlabel("azimuth (deg)"); ax1.set_ylabel("elevation (deg)")
        ax2 = fig.add_subplot(1, 2, 2, projection="polar")
        ax2.set_rlim(0, 90); ax2.set_rticks([30, 60, 90]); ax2.set_yticklabels(["60", "30", "0 el"])
        dots, = ax2.plot([], [], "o", color="0.7", ms=7)
        dot, = ax2.plot([], [], "ro", ms=14)
        title = fig.suptitle("snap or clap at least 1 m away ...")
        fig.tight_layout()
    hist = collections.deque(maxlen=8)
    print("Listening for claps/snaps (Ctrl+C to stop). First second = learning the background.")
    t_last = 0; nclap = 0
    try:
        for b in src:
            sg, e_db = det.push(b)
            if sg is not None:
                r = loc.process_transient(sg, band)
                nclap += 1
                hist.append((r["az"], r["el"]))
                good = r["peak_ratio"] > 3
                print(f"CLAP #{nclap:3d}  az {r['az']:6.0f}  el {r['el']:4.0f}  peak/mean {r['peak_ratio']:4.1f}"
                      f"  level {e_db - det.floor:4.1f} dB over bg{'' if good else '   (weak / diffuse)'}"
                      + (f"  drops {rd.drops}" if rd else ""), flush=True)
                if plot:
                    img.set_data(r["map"] ** 3)
                    mark.set_data([r["az"]], [r["el"]])
                    dot.set_data([np.radians(r["az"])], [90 - r["el"]])
                    dots.set_data(np.radians([h[0] for h in hist]), [90 - h[1] for h in hist])
                    title.set_text(f"clap #{nclap}:  az {r['az']:.0f} deg   el {r['el']:.0f} deg")
            if plot and time.time() - t_last > 0.1:
                t_last = time.time()
                fig.canvas.draw_idle(); plt.pause(0.001)
                if not plt.fignum_exists(fig.number):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        if rd and a.save and rd.saved:
            np.save(a.save, np.concatenate(rd.saved)); print(f"saved {a.save}")
    if plot and a.replay:
        plt.ioff(); plt.show()

# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port")
    ap.add_argument("--replay")
    ap.add_argument("--save")
    ap.add_argument("--simulate", nargs=2, type=float, metavar=("AZ", "EL"))
    ap.add_argument("--band", nargs=2, type=float, default=[1500, 5000], metavar=("LO", "HI"))
    ap.add_argument("--snr", type=float, default=12.0, help="detection threshold, dB")
    ap.add_argument("--nfft", type=int, default=2048)
    ap.add_argument("--flip-x", action="store_true")
    ap.add_argument("--flip-y", action="store_true")
    ap.add_argument("--rot", type=float, default=0.0, help="rotate array frame, deg")
    ap.add_argument("--no-plot", action="store_true")
    ap.add_argument("--mode", choices=["tone", "clap"], default="tone",
                    help="tone = buzzer / whistle, clap = clap or finger snap")
    ap.add_argument("--clap-thr", type=float, default=15.0, help="clap trigger, dB above background")
    a = ap.parse_args()

    loc = Locator(nfft=a.nfft, band=tuple(a.band), flip_x=a.flip_x, flip_y=a.flip_y, rot=a.rot)
    hop = a.nfft // 2

    if a.mode == "clap":
        return run_clap(a, loc)

    if a.simulate:
        x = simulate(a.simulate[0], a.simulate[1], a.nfft)
        r = loc.process(x)
        print(f"true az {a.simulate[0]:.0f} el {a.simulate[1]:.0f}  ->  est az {r['az']:.0f} el {r['el']:.0f}"
              f"  snr {r['snr_db']:.1f} dB  tone {r['freq']:.0f} Hz")
        return

    # data source
    if a.replay:
        data = np.load(a.replay)
        print(f"replay {a.replay}: {data.shape[0] / FS:.1f} s")
        def blocks():
            for s in range(0, data.shape[0] - a.nfft, hop):
                yield data[s:s + a.nfft]
    elif a.port:
        rd = Reader(a.port, save=a.save)
        rd.start()
        def blocks():
            prev = None
            while True:
                new = rd.take(hop)
                if new is None:
                    time.sleep(0.01); continue
                if prev is None:
                    prev = new; continue
                yield np.concatenate([prev, new]); prev = new
    else:
        ap.error("give --port, --replay or --simulate")

    plot = not a.no_plot
    if plot:
        import matplotlib.pyplot as plt
        plt.ion()
        fig = plt.figure(figsize=(11, 4.6))
        ax1 = fig.add_subplot(1, 2, 1)
        img = ax1.imshow(np.zeros((len(loc.el), len(loc.az))), origin="lower", aspect="auto",
                         extent=[loc.az[0], loc.az[-1], loc.el[0], loc.el[-1]], vmin=0, vmax=1, cmap="magma")
        mark, = ax1.plot([], [], "c+", ms=18, mew=2)
        ax1.set_xlabel("azimuth (deg)"); ax1.set_ylabel("elevation (deg)")
        ax2 = fig.add_subplot(1, 2, 2, projection="polar")
        ax2.set_rlim(0, 90); ax2.set_rticks([30, 60, 90]); ax2.set_yticklabels(["60", "30", "0 el"])
        p = np.array([[x, y] for _, x, y in MICS])
        ax2.plot(np.arctan2(p[:, 1], p[:, 0]), np.hypot(p[:, 0], p[:, 1]) * 90 / 80, "k.", ms=4)
        dot, = ax2.plot([], [], "ro", ms=14)
        title = fig.suptitle("waiting for data ...")
        fig.tight_layout()

    hist = collections.deque(maxlen=5)
    t_last = 0
    try:
        for x in blocks():
            r = loc.process(x)
            det = r["snr_db"] >= a.snr
            if det:
                hist.append((r["az"], r["el"]))
            # circular mean of the last few detections for a steadier readout
            if det and hist:
                az_s = np.degrees(np.angle(np.mean(np.exp(1j * np.radians([h[0] for h in hist])))))
                el_s = np.mean([h[1] for h in hist])
            line = (f"{'BUZZER' if det else 'quiet '}  az {r['az']:6.0f}  el {r['el']:4.0f}  "
                    f"snr {r['snr_db']:5.1f} dB  tone {r['freq']:6.0f} Hz  peak/mean {r['peak_ratio']:4.1f}")
            if a.port:
                line += f"  drops {rd.drops}"
            print(line + (f"   smoothed az {az_s:5.0f} el {el_s:3.0f}" if det else ""), flush=True)
            if plot and time.time() - t_last > 0.15:
                t_last = time.time()
                img.set_data(r["map"] ** 3)
                if det:
                    mark.set_data([r["az"]], [r["el"]])
                    dot.set_data([np.radians(az_s)], [90 - el_s])
                    title.set_text(f"BUZZER  az {az_s:.0f} deg   el {el_s:.0f} deg   ({r['freq']:.0f} Hz, SNR {r['snr_db']:.0f} dB)")
                else:
                    mark.set_data([], []); dot.set_data([], [])
                    title.set_text(f"quiet (SNR {r['snr_db']:.0f} dB < {a.snr:.0f})")
                fig.canvas.draw_idle(); plt.pause(0.001)
                if not plt.fignum_exists(fig.number):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        if a.port and a.save and rd.saved:
            np.save(a.save, np.concatenate(rd.saved))
            print(f"saved {a.save}")

if __name__ == "__main__":
    main()
