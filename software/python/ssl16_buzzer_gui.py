#!/usr/bin/env python3
"""
SSL-16 Buzzer Localizer GUI v2 — live localization + test-campaign logger
=========================================================================
Needs ssl16_core.py in the same folder.   pip install numpy pyserial matplotlib
Run:  python ssl16_buzzer_gui.py          ("Demo" = synthetic buzzer, no board)

Board firmware: SSL16_Stream.ino ('SSL6', 12 kHz) or SSL16_HDOA.ino ('HDOA', 24/12 kHz).
Close the Arduino Serial Monitor first.

Every "Measure" saves, inside the session folder:
  <exp>/<exp>_<point>_r<rep>_<hhmmss>.wav   raw 16-ch int16 (stream slot order)
  <exp>/<...>.json                          all metadata for that run
  runs.csv  (one row per run)   blocks.csv  (one row per processing block)   session.json
Frames: see the test plan, Section 2.  Setup A = board vertical (camera), Setup B = board flat, face up.
"""
import collections, csv, json, os, queue, random, struct, threading, time
import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from ssl16_core import (MICS, NCH, SLOT_ORDER, VERSION, Locator, wrap180, angular_error, xyz_to_azel,
                        azel_to_camera, position_to_xyz, write_wav, save_json, speed_of_sound, unit)


# ------------------------------------------------------------------ data sources
class SerialSource(threading.Thread):
    """Reads 'SSL6' (12 kHz) or 'HDOA' packets; samples (n,16) go to a deque and, while recording, to rec."""

    def __init__(self, port):
        super().__init__(daemon=True)
        import serial
        self.ser = serial.Serial(port, 2000000, timeout=0.2)
        self.q = collections.deque(); self.lock = threading.Lock()
        self.fs = None; self.kind = None
        self.packets = self.drops = 0
        self.next_frame = self.last_seq = None
        self.running = True; self.error = None
        self.rec = None
        self.status = {}                      # last "#SSL16 T key=value ..." line from the recorder firmware
        try:
            self.ser.reset_input_buffer()
            self.ser.write(b"STOP\nSTATUS\n"); time.sleep(0.2); self.ser.write(b"START\n")
        except Exception:
            pass

    def stop(self):
        self.running = False
        try:
            self.ser.write(b"STOP\n"); time.sleep(0.05); self.ser.close()
        except Exception:
            pass

    def send(self, line):
        """Send one command line to the firmware (e.g. 'START E1_P07_r1_142233', 'STOP')."""
        try:
            self.ser.write((line + "\n").encode("ascii"))
        except Exception:
            pass

    def _scan_text(self, chunk):
        """Text between packets: keep the newest '#SSL16 T ...' status line as a dict."""
        i = chunk.rfind(b"#SSL16 T ")
        if i < 0: return
        j = chunk.find(b"\n", i)
        if j < 0: return
        try:
            st = dict(kv.split("=", 1) for kv in chunk[i + 9:j].decode("ascii", "ignore").split() if "=" in kv)
            st["_t"] = time.time()
            self.status = st
        except Exception:
            pass

    def _push(self, data):
        with self.lock:
            self.q.append(data)
            while sum(d.shape[0] for d in self.q) > 10 * (self.fs or 12000):
                self.q.popleft()
            if self.rec is not None:
                self.rec.append(data.copy())

    def _gap(self):
        self.drops += 1
        with self.lock:
            self.q.clear()

    def run(self):
        buf = bytearray()
        try:
            while self.running:
                buf += self.ser.read(16384)
                while True:
                    hits = [i for i in (buf.find(b"SSL6"), buf.find(b"HDOA"), buf.find(b"HDST")) if i >= 0]
                    if not hits:
                        if b"#SSL16" in buf: self._scan_text(bytes(buf))
                        del buf[:-3]; break
                    if min(hits) > 8: self._scan_text(bytes(buf[:min(hits)]))
                    del buf[:min(hits)]
                    tag = bytes(buf[:4])
                    if tag == b"HDST":
                        if len(buf) < 6: break
                        n = struct.unpack_from("<H", buf, 4)[0]
                        if len(buf) < 6 + n: break
                        try:
                            st = json.loads(bytes(buf[6:6 + n]).decode())
                            if "fs" in st: self.fs = int(st["fs"])
                        except Exception:
                            pass
                        del buf[:6 + n]; continue
                    if tag == b"SSL6":
                        if len(buf) < 12: break
                        seq, ns, nc = struct.unpack_from("<IHH", buf, 4)
                        n = 12 + ns * nc * 2
                        if nc != NCH or not 0 < ns <= 4096:
                            del buf[:4]; continue
                        if len(buf) < n: break
                        data = np.frombuffer(bytes(buf[12:n]), "<i2").reshape(ns, nc)
                        del buf[:n]
                        self.kind, self.fs = "SSL6", 12000
                        if self.last_seq is not None and seq != (self.last_seq + 1) & 0xFFFFFFFF:
                            self._gap()
                        self.last_seq = seq
                    else:
                        if len(buf) < 24: break
                        _, seq, first, nfr, nch, flags, _ = struct.unpack_from("<4sIQHHHH", buf, 0)
                        n = 24 + nfr * nch * 2
                        if nch != NCH or not 0 < nfr <= 4096:
                            del buf[:4]; continue
                        if len(buf) < n: break
                        data = np.frombuffer(bytes(buf[24:n]), "<i2").reshape(nfr, nch)
                        del buf[:n]
                        self.kind = "HDOA"
                        if self.fs is None: self.fs = 24000
                        if self.next_frame is not None and first != self.next_frame:
                            self._gap()
                        self.next_frame = first + nfr
                    self.packets += 1
                    self._push(data)
        except Exception as e:
            self.error = str(e)

    def take(self, n):
        with self.lock:
            have = sum(d.shape[0] for d in self.q)
            if have < n: return None
            out = np.concatenate(list(self.q), axis=0); self.q.clear()
            if out.shape[0] > n: self.q.appendleft(out[n:])
        return out[:n]


class DemoSource(threading.Thread):
    """Synthetic 2.8 kHz buzzer from the direction the GUI sets, plus room noise; real-time paced."""

    def __init__(self, fs=12000):
        super().__init__(daemon=True)
        self.fs, self.kind = fs, "DEMO"
        self.q = collections.deque(); self.lock = threading.Lock()
        self.packets = self.drops = 0
        self.running = True; self.error = None; self.rec = None
        self.az, self.el = 30.0, 20.0
        self.t = 0.0; self.rng = np.random.default_rng(1)

    def stop(self):
        self.running = False

    def run(self):
        from ssl16_core import mic_positions
        p = mic_positions(); n = 120
        while self.running:
            lead = p @ unit(self.az, self.el) / speed_of_sound(25.0)
            t = self.t + np.arange(n)[:, None] / self.fs + lead[None]
            x = self.rng.normal(0, 30, (n, NCH)) + 3000 * np.sin(2 * np.pi * 2800 * t) + 1000 * np.sin(2 * np.pi * 5600 * t + 0.7)
            self.t += n / self.fs
            SerialSource._push(self, x.astype(np.int16))
            self.packets += 1
            time.sleep(n / self.fs)

    take = SerialSource.take


# ------------------------------------------------------------------ processing thread
class Processor(threading.Thread):
    def __init__(self, src, out_q, cfg):
        super().__init__(daemon=True)
        self.src, self.out_q, self.cfg = src, out_q, cfg
        self.running = True; self.loc = None; self.rebuild = True

    def run(self):
        prev = None
        while self.running:
            fs = self.src.fs
            if fs is None:
                time.sleep(0.05); continue
            nfft = 2048 if fs <= 16000 else 4096
            if self.rebuild or self.loc is None or self.loc.fs != fs:
                c = self.cfg
                self.loc = Locator(fs, nfft, band=(c["lo"], c["hi"]), flip_x=c["flip_x"], flip_y=c["flip_y"],
                                   rot=c["rot"], temp_c=c["temp"])
                self.rebuild = False; prev = None
            hop = nfft // 2
            new = self.src.take(hop)
            if new is None:
                time.sleep(0.01); continue
            if prev is None or prev.shape[0] != hop:
                prev = new; continue
            x = np.concatenate([prev, new]); prev = new
            try:
                r = self.loc.process(x); r["t"] = time.time(); r["fs"] = fs
                self.out_q.put(r)
            except Exception as e:
                self.out_q.put(dict(error=str(e)))


# ------------------------------------------------------------------ GUI
RUN_FIELDS = ["run_id", "time", "experiment", "point", "rep", "setup", "r_m", "angle_deg", "h_src_m", "h_board_m",
              "x_m", "y_m", "z_m", "true_az", "true_el", "true_theta", "true_phi", "est_az", "est_el", "est_theta",
              "est_phi", "az_err", "theta_err", "phi_err", "ang_err", "std_az", "std_el", "n_detect", "n_blocks",
              "detect_rate", "snr_db", "tone_hz", "source", "band_lo", "band_hi", "snr_thr", "flip_x", "flip_y",
              "rot_deg", "temp_c", "fs", "n_samples", "gaps", "wav", "flag", "flag_reason", "notes",
              # added in logger rev 2.1 (raw 48 kHz copy on the board's SD card, firmware SSL16_Rec48)
              "sd_wav", "sd_seen", "sd_ring_drop", "sd_err", "i2s_ovf", "board_temp_c"]
LOGGER_REV = "2.1"


class App:
    def __init__(self, root):
        self.root = root
        root.title(f"SSL-16 Localizer v{VERSION}")
        self.src = self.proc = None
        self.out_q = queue.Queue()
        self.cfg = dict(lo=1500.0, hi=5000.0, flip_x=False, flip_y=False, rot=0.0, temp=25.0, snr=12.0)
        self.hist = collections.deque(maxlen=6); self.trail = collections.deque(maxlen=30)
        self.meas = None; self.runs = []; self.last = None
        self.truth = None
        self.session_dir = None
        self.sess = dict(base=os.path.abspath("ssl16_campaign"), room="lab", board="board1", operator="",
                         humidity="", background_dba="", firmware="SSL16_Rec48", notes="")
        self._build()
        self._set_truth()
        self.root.after(100, self._tick)
        root.protocol("WM_DELETE_WINDOW", self._quit)

    # ---------- layout
    def _build(self):
        left = ttk.Frame(self.root, padding=6); left.pack(side=tk.LEFT, fill=tk.Y)
        right = ttk.Frame(self.root); right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        g = ttk.LabelFrame(left, text="1. Connection & session", padding=5); g.pack(fill=tk.X, pady=2)
        self.port = tk.StringVar()
        self.port_cb = ttk.Combobox(g, textvariable=self.port, width=12); self.port_cb.grid(row=0, column=0)
        ttk.Button(g, text="Refresh", width=8, command=self._ports).grid(row=0, column=1, padx=2)
        self.btn_conn = ttk.Button(g, text="Connect", width=10, command=self._connect); self.btn_conn.grid(row=0, column=2)
        self.demo = tk.BooleanVar(value=False)
        ttk.Checkbutton(g, text="Demo", variable=self.demo).grid(row=1, column=0, sticky="w")
        ttk.Button(g, text="Session...", width=8, command=self._session_dialog).grid(row=1, column=1, padx=2)
        ttk.Button(g, text="Settings...", width=10, command=self._settings_dialog).grid(row=1, column=2)
        self.lbl_link = ttk.Label(g, text="not connected", foreground="gray"); self.lbl_link.grid(row=2, column=0, columnspan=3, sticky="w")
        self.lbl_sess = ttk.Label(g, text="session: not started", foreground="gray"); self.lbl_sess.grid(row=3, column=0, columnspan=3, sticky="w")
        self._ports()

        g = ttk.LabelFrame(left, text="2. Known source position", padding=5); g.pack(fill=tk.X, pady=2)
        self.setup = tk.StringVar(value="A")
        for i, (t, v) in enumerate((("A camera", "A"), ("B table", "B"), ("x y z", "X"))):
            ttk.Radiobutton(g, text=t, value=v, variable=self.setup, command=self._setup_changed).grid(row=0, column=i, sticky="w")
        self.v1, self.v2, self.v3, self.v4 = (tk.StringVar(value=s) for s in ("2.0", "0", "1.20", "1.20"))
        grid = ttk.Frame(g); grid.grid(row=1, column=0, columnspan=3, sticky="w")
        self.l1, self.l2, self.l3, self.l4 = (ttk.Label(grid, width=13) for _ in range(4))
        for i, (l, v) in enumerate(((self.l1, self.v1), (self.l2, self.v2), (self.l3, self.v3), (self.l4, self.v4))):
            l.grid(row=i // 2, column=(i % 2) * 2, sticky="w")
            ttk.Entry(grid, textvariable=v, width=7).grid(row=i // 2, column=(i % 2) * 2 + 1, padx=3, pady=1)
        ttk.Button(g, text="Set position", command=self._set_truth).grid(row=2, column=0, columnspan=3, sticky="ew", pady=2)
        self.lbl_truth = ttk.Label(g, text="", foreground="green", wraplength=330); self.lbl_truth.grid(row=3, column=0, columnspan=3, sticky="w")
        self._setup_changed(init=True)

        g = ttk.LabelFrame(left, text="3. Run labels", padding=5); g.pack(fill=tk.X, pady=2)
        self.exp = tk.StringVar(value="E1"); self.point = tk.StringVar(value="P01")
        self.source = tk.StringVar(value="buzzer_2k8"); self.notes = tk.StringVar()
        ttk.Label(g, text="exp").grid(row=0, column=0, sticky="w")
        ttk.Combobox(g, textvariable=self.exp, width=5, values=[f"E{i}" for i in range(10)]).grid(row=0, column=1, sticky="w")
        ttk.Label(g, text="point").grid(row=0, column=2, sticky="w")
        ttk.Entry(g, textvariable=self.point, width=7).grid(row=0, column=3, sticky="w")
        ttk.Label(g, text="source").grid(row=1, column=0, sticky="w")
        ttk.Combobox(g, textvariable=self.source, width=14, values=["buzzer_2k3", "buzzer_2k8", "buzzer_4k", "tone_1k", "tone_1k5",
                     "tone_2k", "tone_3k", "tone_4k", "tone_5k", "horn_rec", "white_noise", "pink_noise_only"]).grid(row=1, column=1, columnspan=3, sticky="w")
        ttk.Label(g, text="notes").grid(row=2, column=0, sticky="w")
        ttk.Entry(g, textvariable=self.notes, width=30).grid(row=2, column=1, columnspan=3, sticky="w")

        g = ttk.LabelFrame(left, text="Live", padding=5); g.pack(fill=tk.X, pady=2)
        self.lbl_est = ttk.Label(g, text="-", font=("Segoe UI", 12, "bold")); self.lbl_est.pack(anchor="w")
        self.lbl_err = ttk.Label(g, text="-", font=("Segoe UI", 10)); self.lbl_err.pack(anchor="w")
        self.lbl_info = ttk.Label(g, text="-", foreground="gray"); self.lbl_info.pack(anchor="w")

        g = ttk.LabelFrame(left, text="4. Measure (saves raw audio + metadata)", padding=5); g.pack(fill=tk.BOTH, expand=True, pady=2)
        self.dur = tk.StringVar(value="5")
        ttk.Label(g, text="s").grid(row=0, column=0)
        ttk.Entry(g, textvariable=self.dur, width=4).grid(row=0, column=1, sticky="w")
        self.btn_meas = ttk.Button(g, text="Measure", command=self._measure); self.btn_meas.grid(row=0, column=2, padx=3)
        ttk.Button(g, text="Flag last bad", command=self._flag).grid(row=0, column=3)
        ttk.Button(g, text="Shuffle order", command=self._shuffle).grid(row=0, column=4, padx=3)
        self.pb = ttk.Progressbar(g, length=320); self.pb.grid(row=1, column=0, columnspan=5, pady=2, sticky="ew")
        cols = ("exp", "pt", "rep", "true", "est", "err", "ang", "std", "det%")
        self.tree = ttk.Treeview(g, columns=cols, show="headings", height=9)
        for c, w in zip(cols, (34, 36, 30, 44, 44, 40, 36, 34, 38)):
            self.tree.heading(c, text=c); self.tree.column(c, width=w, anchor="center")
        self.tree.grid(row=2, column=0, columnspan=5, sticky="nsew")
        ttk.Label(g, text="true/est/err = bearing θ in Setup A, azimuth otherwise; ang = 3-D error",
                  foreground="gray", font=("Segoe UI", 8)).grid(row=3, column=0, columnspan=5, sticky="w")

        # plots
        self.fig = Figure(figsize=(8.6, 6.8), dpi=90)
        gs = self.fig.add_gridspec(2, 2, height_ratios=[1.25, 1])
        self.ax_map = self.fig.add_subplot(gs[0, 0]); self.ax_pol = self.fig.add_subplot(gs[0, 1], projection="polar")
        self.ax_lev = self.fig.add_subplot(gs[1, :])
        self.img = self.ax_map.imshow(np.zeros((31, 180)), origin="lower", aspect="auto", extent=[-180, 180, 0, 90],
                                      vmin=0, vmax=1, cmap="magma")
        self.m_true, = self.ax_map.plot([], [], "gx", ms=14, mew=3, label="true")
        self.m_est, = self.ax_map.plot([], [], "c+", ms=16, mew=2, label="estimate")
        self.ax_map.set_xlabel("array azimuth (deg)"); self.ax_map.set_ylabel("array elevation (deg)")
        self.ax_map.set_title("beam power (SRP-PHAT)", fontsize=10); self.ax_map.legend(loc="upper right", fontsize=8)
        ax = self.ax_pol
        ax.set_rlim(0, 90); ax.set_rticks([30, 60, 90]); ax.set_yticklabels(["el 60", "el 30", "el 0"], fontsize=7)
        ax.set_title("array top view (0 deg = +x)", fontsize=10)
        p = np.array([[x, y] for _, x, y in MICS])
        ax.plot(np.arctan2(p[:, 1], p[:, 0]), np.hypot(p[:, 0], p[:, 1]) * 30 / 80, "k.", ms=4)
        self.p_trail, = ax.plot([], [], "o", color="0.75", ms=5)
        self.p_true, = ax.plot([], [], "g*", ms=18)
        self.p_est, = ax.plot([], [], "ro", ms=12)
        self.bars = self.ax_lev.bar(range(NCH), np.full(NCH, 0.0), bottom=-100, color="tab:blue")
        self.ax_lev.set_ylim(-100, 0); self.ax_lev.set_ylabel("level (dBFS)")
        self.ax_lev.set_xticks(range(NCH)); self.ax_lev.set_xticklabels([m[0] for m in MICS], fontsize=8)
        self.ax_lev.set_title("channel levels (stream order)", fontsize=10)
        self.fig.tight_layout()
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _setup_changed(self, init=False):
        s = self.setup.get()
        names = {"A": ("range r (m)", "bearing θ (°)", "src h (m)", "board h (m)"),
                 "B": ("radius r (m)", "azimuth α (°)", "src h (m)", "board h (m)"),
                 "X": ("x (m)", "y (m)", "z (m)", "(unused)")}[s]
        for l, t in zip((self.l1, self.l2, self.l3, self.l4), names):
            l.config(text=t)
        if not init:
            if s == "A": self.v1.set("2.0"); self.v2.set("0"); self.v3.set("1.20"); self.v4.set("1.20")
            elif s == "B": self.v1.set("1.5"); self.v2.set("0"); self.v3.set("1.40"); self.v4.set("1.00")
            else: self.v1.set("1.0"); self.v2.set("0.5"); self.v3.set("0.4"); self.v4.set("0")

    # ---------- dialogs
    def _session_dialog(self):
        d = tk.Toplevel(self.root); d.title("Session"); d.transient(self.root)
        vs = {}
        for i, k in enumerate(("base", "room", "board", "operator", "humidity", "background_dba", "firmware", "notes")):
            ttk.Label(d, text=k).grid(row=i, column=0, sticky="w", padx=4, pady=2)
            vs[k] = tk.StringVar(value=self.sess[k]); ttk.Entry(d, textvariable=vs[k], width=40).grid(row=i, column=1, padx=4)
        ttk.Button(d, text="Browse base folder", command=lambda: vs["base"].set(filedialog.askdirectory() or vs["base"].get())).grid(row=8, column=0, pady=4)

        def ok():
            for k in vs: self.sess[k] = vs[k].get()
            self._start_session(); d.destroy()
        ttk.Button(d, text="Start new session", command=ok).grid(row=8, column=1, sticky="e", pady=4, padx=4)

    def _settings_dialog(self):
        d = tk.Toplevel(self.root); d.title("Settings"); d.transient(self.root)
        fx, fy = tk.BooleanVar(value=self.cfg["flip_x"]), tk.BooleanVar(value=self.cfg["flip_y"])
        ttk.Checkbutton(d, text="flip x", variable=fx).grid(row=0, column=0, sticky="w", padx=4)
        ttk.Checkbutton(d, text="flip y", variable=fy).grid(row=0, column=1, sticky="w")
        vs = {}
        for i, (k, lab) in enumerate((("rot", "rotate (deg)"), ("temp", "air temp (C)"), ("lo", "band low (Hz)"),
                                      ("hi", "band high (Hz)"), ("snr", "detect SNR (dB)"))):
            ttk.Label(d, text=lab).grid(row=i + 1, column=0, sticky="w", padx=4)
            vs[k] = tk.StringVar(value=str(self.cfg[k])); ttk.Entry(d, textvariable=vs[k], width=9).grid(row=i + 1, column=1, pady=1)

        def ok():
            try:
                self.cfg.update({k: float(v.get()) for k, v in vs.items()}); self.cfg.update(flip_x=fx.get(), flip_y=fy.get())
            except ValueError:
                messagebox.showerror("Settings", "numbers only"); return
            if self.proc: self.proc.rebuild = True
            self.hist.clear(); self.trail.clear(); self._save_session_json(); d.destroy()
        ttk.Button(d, text="Apply", command=ok).grid(row=7, column=0, columnspan=2, sticky="ew", padx=4, pady=4)

    def _start_session(self):
        name = f"{time.strftime('%Y-%m-%d_%H%M')}_{self.sess['room']}_{self.sess['board']}".replace(" ", "-")
        self.session_dir = os.path.join(self.sess["base"], name)
        os.makedirs(os.path.join(self.session_dir, "photos"), exist_ok=True)
        self.runs = []
        for i in self.tree.get_children(): self.tree.delete(i)
        self._save_session_json()
        self.lbl_sess.config(text="session: " + name, foreground="green")

    def _save_session_json(self):
        if not self.session_dir: return
        info = dict(self.sess, settings=self.cfg, gui_version=VERSION, slot_order=SLOT_ORDER,
                    fs=getattr(self.src, "fs", None), stream=getattr(self.src, "kind", None),
                    saved=time.strftime("%Y-%m-%d %H:%M:%S"))
        save_json(os.path.join(self.session_dir, "session.json"), info)

    # ---------- actions
    def _ports(self):
        try:
            from serial.tools import list_ports
            ps = [p.device for p in list_ports.comports()]
        except Exception:
            ps = []
        self.port_cb["values"] = ps
        if ps and not self.port.get(): self.port.set(ps[-1])

    def _connect(self):
        if self.src:
            self._disconnect(); return
        try:
            self.src = DemoSource() if self.demo.get() else SerialSource(self.port.get())
        except Exception as e:
            messagebox.showerror("Connect", f"Cannot open {self.port.get()}:\n{e}\n\nClose the Arduino Serial Monitor.")
            self.src = None; return
        if isinstance(self.src, DemoSource) and self.truth:
            self.src.az, self.src.el = self.truth["true_az"], self.truth["true_el"]
        self.src.start()
        self.proc = Processor(self.src, self.out_q, self.cfg); self.proc.start()
        self.btn_conn.config(text="Disconnect")

    def _disconnect(self):
        if self.proc: self.proc.running = False
        if self.src: self.src.stop()
        self.src = self.proc = None
        self.btn_conn.config(text="Connect"); self.lbl_link.config(text="not connected", foreground="gray")

    def _set_truth(self):
        s = self.setup.get()
        try:
            a, b, c, d = (float(v.get()) if v.get().strip() not in ("", "(unused)") else 0.0 for v in (self.v1, self.v2, self.v3, self.v4))
        except ValueError:
            messagebox.showerror("Position", "numbers only"); return
        if s == "X":
            x, y, z = a, b, c; r = ang = hs = hb = ""
        else:
            x, y, z = position_to_xyz(s, a, b, c, d); r, ang, hs, hb = a, b, c, d
        az, el, dist = xyz_to_azel(x, y, z)
        th, ph = azel_to_camera(az, el)
        self.truth = dict(setup=s, r_m=r, angle_deg=ang, h_src_m=hs, h_board_m=hb, x_m=round(x, 4), y_m=round(y, 4),
                          z_m=round(z, 4), true_az=round(az, 3), true_el=round(el, 3), true_theta=round(th, 3),
                          true_phi=round(ph, 3), dist=dist)
        txt = f"array az {az:.1f}°, el {el:.1f}°, {dist:.2f} m"
        if s == "A": txt = f"bearing θ {th:.1f}°, vertical φ {ph:.1f}°  |  " + txt
        if z < 0: txt += "  (z<0: behind the face, shown mirrored)"
        if dist < 1.0: txt += "  < 1 m: near field"
        self.lbl_truth.config(text=txt)
        self.m_true.set_data([az], [el]); self.p_true.set_data([np.radians(az)], [90 - el])
        if isinstance(self.src, DemoSource):
            self.src.az, self.src.el = az, el
        self.hist.clear(); self.canvas.draw_idle()

    def _measure(self):
        if not self.src:
            messagebox.showinfo("Measure", "Connect first."); return
        if not self.session_dir:
            self._start_session()
        try:
            dur = float(self.dur.get())
        except ValueError:
            return
        self._set_truth()
        # The run name is fixed at the start, so the board can save its raw 48 kHz copy under the same name.
        exp, pt = self.exp.get().strip(), self.point.get().strip()
        rep = 1 + sum(1 for r in self.runs if r["experiment"] == exp and r["point"] == pt)
        run_id = f"{exp}_{pt}_r{rep}_{time.strftime('%H%M%S')}"
        st0 = dict(getattr(self.src, "status", {}) or {})
        self.meas = dict(t0=time.time(), dur=dur, res=[], gaps0=self.src.drops, exp=exp, pt=pt, rep=rep,
                         run_id=run_id, ovf0=st0.get("i2s_ovf"), sd_seen=False)
        if hasattr(self.src, "send"):
            self.src.send("START " + run_id)          # SSL16_Rec48: raw 48 kHz WAV on the SD card (/ssl16/<run_id>.wav)
        with self.src.lock:
            self.src.rec = []
        self.btn_meas.config(state="disabled")

    def _finish_measure(self):
        m = self.meas; self.meas = None
        with self.src.lock:
            chunks, self.src.rec = self.src.rec, None
        st = dict(getattr(self.src, "status", {}) or {})
        if hasattr(self.src, "send"):
            self.src.send("STOP")
        self.btn_meas.config(state="normal"); self.pb["value"] = 0
        T = self.truth; exp, pt, rep, run_id = m["exp"], m["pt"], m["rep"], m["run_id"]
        os.makedirs(os.path.join(self.session_dir, exp), exist_ok=True)
        wav_rel = os.path.join(exp, run_id + ".wav")
        fs = self.src.fs or 12000
        data = np.concatenate(chunks) if chunks else np.zeros((0, NCH), np.int16)
        data = data[:int(m["dur"] * fs)]
        write_wav(os.path.join(self.session_dir, wav_rel), data, fs)
        det = [r for r in m["res"] if r["det"]]
        row = {k: "" for k in RUN_FIELDS}
        row.update(T); row.pop("dist", None)
        row.update(run_id=run_id, time=time.strftime("%Y-%m-%d %H:%M:%S"), experiment=exp, point=pt, rep=rep,
                   n_blocks=len(m["res"]), n_detect=len(det), detect_rate=round(len(det) / max(1, len(m["res"])), 3),
                   source=self.source.get(), band_lo=self.cfg["lo"], band_hi=self.cfg["hi"], snr_thr=self.cfg["snr"],
                   flip_x=self.cfg["flip_x"], flip_y=self.cfg["flip_y"], rot_deg=self.cfg["rot"], temp_c=self.cfg["temp"],
                   fs=fs, n_samples=data.shape[0], gaps=self.src.drops - m["gaps0"], wav=wav_rel.replace("\\", "/"),
                   flag="", notes=self.notes.get())
        sd_seen = bool(m["sd_seen"] or st.get("rec") == run_id)
        ovf = ""
        try:
            if st.get("i2s_ovf") is not None and m["ovf0"] is not None: ovf = int(st["i2s_ovf"]) - int(m["ovf0"])
        except ValueError:
            pass
        row.update(sd_wav=(run_id + ".wav") if sd_seen else "", sd_seen=int(sd_seen),
                   sd_ring_drop=st.get("ring_drop", "") if sd_seen else "", sd_err=st.get("sd_err", ""),
                   i2s_ovf=ovf, board_temp_c=st.get("temp", ""))
        if det:
            az = np.array([r["az"] for r in det]); el = np.array([r["el"] for r in det])
            mv = np.mean(np.exp(1j * np.radians(az)))
            maz = float(np.degrees(np.angle(mv))); mel = float(el.mean())
            th, ph = azel_to_camera(maz, mel)
            row.update(est_az=round(maz, 2), est_el=round(mel, 2), est_theta=round(th, 2), est_phi=round(ph, 2),
                       az_err=round(float(wrap180(maz - T["true_az"])), 2),
                       theta_err=round(float(wrap180(th - T["true_theta"])), 2), phi_err=round(ph - T["true_phi"], 2),
                       ang_err=round(angular_error(T["true_az"], T["true_el"], maz, mel), 2),
                       std_az=round(float(np.degrees(np.sqrt(max(0.0, -2 * np.log(min(abs(mv), 1.0) + 1e-12))))), 2),
                       std_el=round(float(el.std()), 2), snr_db=round(float(np.mean([r["snr"] for r in det])), 1),
                       tone_hz=round(float(np.median([r["tone"] for r in det])), 0))
        self.runs.append(row)
        save_json(os.path.join(self.session_dir, exp, run_id + ".json"), dict(row, session=self.sess, gui_version=VERSION,
                  logger_rev=LOGGER_REV, slot_order=SLOT_ORDER, stream=self.src.kind,
                  sd_fs=48000 if sd_seen else None, sd_slot_order=SLOT_ORDER if sd_seen else None))
        self._write_runs()
        with open(os.path.join(self.session_dir, "blocks.csv"), "a", newline="") as f:
            w = csv.writer(f)
            if f.tell() == 0: w.writerow(["run_id", "t", "az", "el", "snr_db", "tone_hz", "peak", "detected"])
            for r in m["res"]:
                w.writerow([run_id, round(r["t"], 3), round(r["az"], 2), round(r["el"], 2), round(r["snr"], 2),
                            round(r["tone"], 1), round(r["peak"], 2), int(r["det"])])
        A = T["setup"] == "A"
        if det:
            vals = (exp, pt, rep, f"{T['true_theta'] if A else T['true_az']:.1f}", f"{row['est_theta'] if A else row['est_az']:.1f}",
                    f"{row['theta_err'] if A else row['az_err']:+.1f}", f"{row['ang_err']:.1f}", f"{row['std_az']:.1f}",
                    f"{100 * row['detect_rate']:.0f}")
        else:
            vals = (exp, pt, rep, f"{T['true_theta'] if A else T['true_az']:.1f}", "-", "-", "-", "-", "0")
        self.tree.insert("", "end", iid=run_id, values=vals); self.tree.see(run_id)
        warn = []
        if row["detect_rate"] < 0.7: warn.append(f"detections only {100 * row['detect_rate']:.0f}% of blocks")
        if det and row["std_az"] > 5: warn.append(f"spread {row['std_az']:.1f}°")
        if row["gaps"]: warn.append(f"{row['gaps']} USB gaps")
        if hasattr(self.src, "send") and st:          # recorder firmware is talking: check the SD copy
            if not sd_seen: warn.append("board did NOT confirm the SD recording (card in? sd=ok?)")
            if str(row["sd_ring_drop"]) not in ("", "0"): warn.append(f"SD too slow: {row['sd_ring_drop']} blocks dropped from the 48 kHz file")
            if str(row["sd_err"]) not in ("", "0"): warn.append(f"SD write errors: {row['sd_err']}")
            if row["i2s_ovf"] not in ("", 0): warn.append(f"I2S overflow ({row['i2s_ovf']}): samples lost")
        if warn:
            messagebox.showwarning("Check this run", "Redo this point once (protocol step 6):\n- " + "\n- ".join(warn))

    def _write_runs(self):
        with open(os.path.join(self.session_dir, "runs.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=RUN_FIELDS, extrasaction="ignore"); w.writeheader(); w.writerows(self.runs)

    def _flag(self):
        if not self.runs: return
        r = self.runs[-1]
        reason = simpledialog.askstring("Flag run", f"Reason for flagging {r['run_id']} as bad:", parent=self.root)
        if reason is None: return
        r["flag"], r["flag_reason"] = "bad", reason
        self._write_runs()
        self.tree.item(r["run_id"], tags=("bad",)); self.tree.tag_configure("bad", foreground="red")

    def _shuffle(self):
        s = simpledialog.askstring("Shuffle order", "Point IDs, comma separated, or a count (e.g. 19 -> P01..P19):", parent=self.root)
        if not s: return
        pts = [f"P{i:02d}" for i in range(1, int(s) + 1)] if s.strip().isdigit() else [p.strip() for p in s.split(",") if p.strip()]
        random.shuffle(pts)
        out = "  ".join(pts)
        if self.session_dir:
            with open(os.path.join(self.session_dir, f"order_{self.exp.get()}.txt"), "a") as f:
                f.write(time.strftime("%H:%M ") + out + "\n")
        messagebox.showinfo("Measurement order", out)

    # ---------- periodic update
    def _tick(self):
        while True:
            try:
                r = self.out_q.get_nowait()
            except queue.Empty:
                break
            if "error" in r:
                self.lbl_info.config(text="processing error: " + r["error"]); continue
            r["det"] = r["snr"] >= self.cfg["snr"]
            if r["det"]:
                self.hist.append((r["az"], r["el"])); self.trail.append((r["az"], r["el"]))
            if self.meas: self.meas["res"].append(r)
            self.last = r
        if self.meas and self.src and getattr(self.src, "status", {}).get("rec") == self.meas["run_id"]:
            self.meas["sd_seen"] = True
        if self.src:
            if self.src.error:
                self.lbl_link.config(text="serial error: " + self.src.error, foreground="red")
            elif self.src.packets == 0:
                self.lbl_link.config(text="connected, no data yet (firmware? port?)", foreground="orange")
            else:
                self.lbl_link.config(text=f"{self.src.kind} {self.src.fs} Hz | packets {self.src.packets} | gaps {self.src.drops}",
                                     foreground="green" if self.src.drops == 0 else "orange")
        if self.meas and self.src:
            # stop on the number of recorded samples, so every WAV has exactly the requested length
            with self.src.lock:
                got = sum(c.shape[0] for c in self.src.rec) if self.src.rec is not None else 0
            need = self.meas["dur"] * (self.src.fs or 12000)
            self.pb["value"] = min(100, 100 * got / need)
            if got >= need or time.time() - self.meas["t0"] > self.meas["dur"] + 5:
                self._finish_measure()
        if self.last is not None:
            self._draw(); self.last = None
        self.root.after(100, self._tick)

    def _draw(self):
        r = self.last
        self.img.set_data(r["map"] ** 3)
        for b, v in zip(self.bars, r["level_db"]):
            b.set_height(max(0.0, v + 100)); b.set_color("tab:red" if v > -3 else "tab:blue")
        self.lbl_info.config(text=f"tone {r['tone']:.0f} Hz | SNR {r['snr']:.1f} dB | peak/mean {r['peak']:.1f}")
        T = self.truth
        if r["det"] and self.hist:
            az = float(np.degrees(np.angle(np.mean(np.exp(1j * np.radians([h[0] for h in self.hist]))))))
            el = float(np.mean([h[1] for h in self.hist]))
            self.m_est.set_data([az], [el]); self.p_est.set_data([np.radians(az)], [90 - el])
            self.p_trail.set_data(np.radians([t[0] for t in self.trail]), [90 - t[1] for t in self.trail])
            if T and T["setup"] == "A":
                th, ph = azel_to_camera(az, el)
                self.lbl_est.config(text=f"SOURCE  θ {th:6.1f}°   φ {ph:5.1f}°", foreground="red")
                self.lbl_err.config(text=f"error: θ {float(wrap180(th - T['true_theta'])):+.1f}°, φ {ph - T['true_phi']:+.1f}°, "
                                         f"3-D {angular_error(T['true_az'], T['true_el'], az, el):.1f}°")
            else:
                self.lbl_est.config(text=f"SOURCE  az {az:6.1f}°   el {el:4.1f}°", foreground="red")
                if T:
                    self.lbl_err.config(text=f"error: az {float(wrap180(az - T['true_az'])):+.1f}°, "
                                             f"3-D {angular_error(T['true_az'], T['true_el'], az, el):.1f}°")
        else:
            self.m_est.set_data([], []); self.p_est.set_data([], [])
            self.lbl_est.config(text="no source detected", foreground="gray"); self.lbl_err.config(text="-")
        self.canvas.draw_idle()

    def _quit(self):
        self._disconnect(); self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
