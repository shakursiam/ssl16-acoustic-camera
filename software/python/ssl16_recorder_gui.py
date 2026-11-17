#!/usr/bin/env python3
"""
SSL-16 WAV Recorder - control panel for firmware SSL16_WavRecorder_v4.1

What it does
  * connects to the board over USB (native CDC port)
  * START / STOP a recording
      - on the board's microSD card  (/ssl16/<name>.wav)          and / or
      - on this PC, from the USB stream (<folder>/<name>_pc.wav)
    Both files: 16 channels, 12 kHz, 16-bit, channel 1 = M1 ... channel 16 = M16
  * optional fixed-length recording (stops by itself after N seconds)
  * shows board status once per second: recording name, length, size, temperature,
    SD card state, dropped blocks, errors
  * live level meters for the 16 microphones (M1 ... M16), from the USB stream

The PC file and the SD file do not start on the same sample. <name>_pc.txt and the
SD card's <name>.txt both contain first_seq; the offset between the two files is
(first_seq_sd - first_seq_pc) * 120 samples.
If USB packets are lost, the PC file gets zeros in their place (timing is kept) and the
count is written to <name>_pc.txt. The SD file does not depend on USB.

Install:  pip install pyserial numpy
Run:      python ssl16_recorder_gui.py

Close the Arduino Serial Monitor and ssl16_realtime_3d.py first: only one program
can hold the serial port.
"""

import os
import re
import struct
import threading
import time
import queue
import wave
from datetime import datetime

import numpy as np
import serial
from serial.tools import list_ports
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

FS_OUT = 12000
NCH = 16
BYTES_PER_SEC = FS_OUT * NCH * 2
# Mic number in each USB channel (TDM slot order), same table as the firmware
SLOT_MIC = [2, 7, 10, 15, 1, 4, 9, 12, 3, 6, 11, 14, 5, 8, 13, 16]
MIC_ORDER = np.argsort(SLOT_MIC)       # USB channel index that holds M1, M2, ... M16
ESPRESSIF_VID = 0x303A
METER_FLOOR_DB = -90.0

PKT_MAGIC = b"SSL6"
TXT_MAGIC = b"#SSL16 "
MAX_LINE = 300


class PcWav:
    """WAV file on the PC, fed with USB packets. Channel order M1 ... M16."""

    def __init__(self, path):
        self.path = path
        self.w = wave.open(path, "wb")
        self.w.setnchannels(NCH)
        self.w.setsampwidth(2)
        self.w.setframerate(FS_OUT)
        self.first_seq = None
        self.last_seq = None
        self.packets = 0
        self.lost = 0                  # packets missing on USB, replaced by zeros
        self.frames = 0
        self.t_start = datetime.now()

    def add(self, seq, a):             # a: int16 array [nsamp, 16] in USB channel order
        if self.first_seq is None:
            self.first_seq = seq
        elif seq > self.last_seq + 1:
            gap = min(seq - self.last_seq - 1, 6000)          # at most 1 minute of zeros
            self.w.writeframesraw(bytes(gap * a.shape[0] * NCH * 2))
            self.lost += gap
            self.frames += gap * a.shape[0]
        self.last_seq = seq
        self.w.writeframesraw(np.ascontiguousarray(a[:, MIC_ORDER]).tobytes())
        self.frames += a.shape[0]
        self.packets += 1

    def close(self):
        self.w.close()                 # writes the final sizes into the header
        info = os.path.splitext(self.path)[0] + ".txt"
        with open(info, "w") as f:
            f.write("source=USB stream saved by ssl16_recorder_gui.py\n")
            f.write("fs_hz=%d\nnch=%d\nformat=WAV, 16-bit PCM little endian\n" % (FS_OUT, NCH))
            f.write("wav_channel_order=" + " ".join("M%d" % (i + 1) for i in range(NCH)) + "\n")
            f.write("pc_start_time=%s\n" % self.t_start.isoformat(timespec="milliseconds"))
            f.write("first_seq=%s\nlast_seq=%s\npackets=%d\n" % (self.first_seq, self.last_seq, self.packets))
            f.write("samples_per_channel=%d\n" % self.frames)
            f.write("usb_lost_packets=%d (zero-filled, 120 samples each)\n" % self.lost)


class StreamParser:
    """Splits the USB byte stream into SSL6 audio packets and '#SSL16 ...' text lines."""

    def __init__(self):
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.peak = np.zeros(NCH, dtype=np.int32)   # per USB channel, since last take_peaks()
        self.packets = 0
        self.lost = 0                               # packets missing on USB (seq gaps)
        self.last_seq = None
        self.sink = None                            # PcWav while a PC recording is active
        self.sink_error = None

    def take_peaks(self):
        with self.lock:
            p = self.peak.copy()
            self.peak[:] = 0
        return p

    def set_sink(self, sink):
        with self.lock:
            self.sink = sink

    def take_sink(self):
        with self.lock:
            s, self.sink = self.sink, None
        return s

    def feed(self, data):
        """Add received bytes; returns the list of complete text lines found."""
        lines = []
        buf = self.buf
        buf += data
        while True:
            if len(buf) < 12:
                break
            if buf.startswith(PKT_MAGIC):
                seq, nsamp, nch = struct.unpack_from("<IHH", buf, 4)
                if nch != NCH or not (0 < nsamp <= 2048):
                    del buf[:1]                     # false match, resync
                    continue
                total = 12 + nsamp * nch * 2
                if len(buf) < total:
                    break
                a = np.frombuffer(bytes(buf[12:total]), dtype="<i2").reshape(nsamp, nch)
                pk = np.abs(a.astype(np.int32)).max(axis=0)
                with self.lock:
                    np.maximum(self.peak, pk, out=self.peak)
                    if self.sink is not None:
                        try:
                            self.sink.add(seq, a)
                        except Exception as e:      # disk full etc.
                            self.sink_error = str(e)
                # The first packets after connecting are old ones that waited in the board's
                # USB buffer, so the jump right after them is not a real loss.
                if self.packets > 50 and self.last_seq is not None and seq > self.last_seq + 1:
                    self.lost += seq - self.last_seq - 1
                self.last_seq = seq                 # seq going backwards = board restarted
                self.packets += 1
                del buf[:total]
            elif buf.startswith(TXT_MAGIC):
                end = buf.find(b"\n", 0, MAX_LINE)
                if end < 0:
                    if len(buf) < MAX_LINE:
                        break
                    del buf[:1]
                    continue
                lines.append(bytes(buf[len(TXT_MAGIC):end]).decode("ascii", "replace").strip())
                del buf[:end + 1]
            else:                                   # out of sync: jump to the next marker
                i = buf.find(PKT_MAGIC, 1)
                j = buf.find(TXT_MAGIC, 1)
                nxt = min(k for k in (i, j, len(buf) - 6) if k >= 0)
                del buf[:max(nxt, 1)]
        return lines


def parse_kv(line):
    """'T ms=1 temp=25.1 rec=-' -> ('T', {'ms': '1', 'temp': '25.1', 'rec': '-'})"""
    kv = dict(m.groups() for m in re.finditer(r"(\w+)=(\S+)", line))
    head = line.split(" ", 1)[0] if line else ""
    return head, kv


def hms(secs):
    return "%02d:%02d:%02d" % (secs // 3600, secs % 3600 // 60, secs % 60)


class Reader(threading.Thread):
    def __init__(self, ser, parser, out_q):
        super().__init__(daemon=True)
        self.ser, self.parser, self.q = ser, parser, out_q
        self.stop_flag = False

    def run(self):
        try:
            while not self.stop_flag:
                data = self.ser.read(self.ser.in_waiting or 1)
                if data:
                    for ln in self.parser.feed(data):
                        self.q.put(("line", ln))
        except Exception as e:                      # port unplugged etc.
            if not self.stop_flag:
                self.q.put(("error", str(e)))


class App:
    def __init__(self, root):
        self.root = root
        root.title("SSL-16 WAV Recorder")
        root.minsize(760, 680)
        self.ser = None
        self.reader = None
        self.parser = None
        self.q = queue.Queue()
        self.status = {}
        self.t_last_status = 0.0
        self.recording = False         # board is recording to SD (from its status line)
        self.rec_name = ""
        self.pc = None                 # PcWav while recording on the PC
        self.pc_name = ""
        self.pc_follows_sd = False
        self.stop_at = None            # timed recording: time.time() to stop
        self.pending_start = None      # time START was sent, until the board confirms
        self.stop_sent = None          # time STOP was sent, until the board confirms
        self.stop_tries = 0
        self.used_names = set()
        self.last_pkts, self.t_rate, self.rate = 0, time.time(), 0.0

        self._build()
        self.refresh_ports()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self.tick)

    # ------------------------------------------------------------------ UI
    def _build(self):
        pad = dict(padx=8, pady=4)
        top = ttk.LabelFrame(self.root, text="Connection")
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Port:").pack(side="left", padx=(8, 4), pady=6)
        self.port_var = tk.StringVar()
        self.port_box = ttk.Combobox(top, textvariable=self.port_var, width=38, state="readonly")
        self.port_box.pack(side="left", pady=6)
        ttk.Button(top, text="Refresh", command=self.refresh_ports).pack(side="left", padx=6)
        self.conn_btn = ttk.Button(top, text="Connect", command=self.toggle_connect)
        self.conn_btn.pack(side="left", padx=6)

        rec = ttk.LabelFrame(self.root, text="Recording")
        rec.pack(fill="x", **pad)
        r1 = ttk.Frame(rec); r1.pack(fill="x", padx=8, pady=(6, 2))
        ttk.Label(r1, text="Run name:").pack(side="left")
        self.name_var = tk.StringVar()
        ttk.Entry(r1, textvariable=self.name_var, width=30).pack(side="left", padx=6)
        ttk.Button(r1, text="Timestamp name", command=self.fill_timestamp).pack(side="left")
        ttk.Label(r1, text="   Length (s), 0 = until STOP:").pack(side="left")
        self.dur_var = tk.StringVar(value="0")
        ttk.Entry(r1, textvariable=self.dur_var, width=7).pack(side="left", padx=6)
        ttk.Label(rec, text="Letters, digits, _ and - only (max 40). Empty name = timestamp "
                            "(SD-only: board picks auto_001, auto_002, ...)",
                  foreground="#666").pack(anchor="w", padx=8)

        r3 = ttk.Frame(rec); r3.pack(fill="x", padx=8, pady=(6, 0))
        self.sd_var = tk.BooleanVar(value=True)
        self.pc_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="Save on the board's SD card  (/ssl16/<name>.wav)",
                        variable=self.sd_var).pack(side="left")
        r4 = ttk.Frame(rec); r4.pack(fill="x", padx=8, pady=(2, 0))
        ttk.Checkbutton(r4, text="Save on this PC  (<name>_pc.wav) in:", variable=self.pc_var).pack(side="left")
        self.dir_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "SSL16_recordings"))
        ttk.Entry(r4, textvariable=self.dir_var, width=52).pack(side="left", padx=6)
        ttk.Button(r4, text="Browse...", command=self.browse_dir).pack(side="left")
        ttk.Button(r4, text="Open folder", command=self.open_dir).pack(side="left", padx=6)

        r2 = ttk.Frame(rec); r2.pack(fill="x", padx=8, pady=8)
        self.start_btn = tk.Button(r2, text="START", width=14, height=2, bg="#2e9e4f", fg="white",
                                   font=("Segoe UI", 11, "bold"), command=self.start_rec, state="disabled")
        self.start_btn.pack(side="left")
        self.stop_btn = tk.Button(r2, text="STOP", width=14, height=2, bg="#c0392b", fg="white",
                                  font=("Segoe UI", 11, "bold"), command=self.stop_rec, state="disabled")
        self.stop_btn.pack(side="left", padx=10)
        self.state_lbl = tk.Label(r2, text="NOT CONNECTED", font=("Segoe UI", 14, "bold"), fg="#888")
        self.state_lbl.pack(side="left", padx=14)

        st = ttk.LabelFrame(self.root, text="Status")
        st.pack(fill="x", **pad)
        self.fields = {}
        names = [("length", "SD recorded"), ("size", "SD file size"), ("remain", "Auto-stop in"),
                 ("pc", "PC recorded"), ("pc_lost", "PC file USB lost"), ("usb", "USB stream"),
                 ("temp", "Temperature"), ("sd", "SD card"), ("ring_drop", "SD dropped blocks"),
                 ("sd_err", "SD errors"), ("fw", "Firmware")]
        for i, (key, label) in enumerate(names):
            r, c = divmod(i, 3)
            ttk.Label(st, text=label + ":").grid(row=r, column=2 * c, sticky="e", padx=(10, 4), pady=3)
            v = ttk.Label(st, text="-", width=24, font=("Consolas", 10))
            v.grid(row=r, column=2 * c + 1, sticky="w")
            self.fields[key] = v

        mf = ttk.LabelFrame(self.root, text="Microphone levels (peak, dBFS, scale 0 to %d)" % METER_FLOOR_DB)
        mf.pack(fill="x", **pad)
        self.cv = tk.Canvas(mf, height=150, bg="#1b1f24", highlightthickness=0)
        self.cv.pack(fill="x", padx=8, pady=6)
        self.bars = []
        self.cv.bind("<Configure>", lambda e: self._layout_meters())

        lf = ttk.LabelFrame(self.root, text="Log")
        lf.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(lf, height=8, state="disabled", font=("Consolas", 9), wrap="none")
        sb = ttk.Scrollbar(lf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True, padx=(8, 0), pady=6)

    def _layout_meters(self):
        self.cv.delete("all")
        self.bars = []
        w, h = self.cv.winfo_width(), self.cv.winfo_height()
        top, bot = 8, h - 22
        slot = w / NCH
        for db in (-12, -30, -60):                               # guide lines
            y = top + (bot - top) * (db / METER_FLOOR_DB)
            self.cv.create_line(0, y, w, y, fill="#353b43")
            self.cv.create_text(3, y - 6, text=str(db), fill="#6b7480", anchor="w", font=("Consolas", 7))
        for m in range(NCH):
            x0, x1 = m * slot + slot * 0.25, m * slot + slot * 0.75
            self.cv.create_rectangle(x0, top, x1, bot, outline="#353b43")
            bar = self.cv.create_rectangle(x0, bot, x1, bot, fill="#2e9e4f", width=0)
            self.cv.create_text((x0 + x1) / 2, h - 10, text="M%d" % (m + 1), fill="#c9d1d9", font=("Consolas", 8))
            self.bars.append((bar, x0, x1, top, bot))

    def log_line(self, s):
        self.log.configure(state="normal")
        self.log.insert("end", "%s  %s\n" % (datetime.now().strftime("%H:%M:%S"), s))
        if int(self.log.index("end-1c").split(".")[0]) > 2000:
            self.log.delete("1.0", "500.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def browse_dir(self):
        d = filedialog.askdirectory(initialdir=self.dir_var.get() or os.path.expanduser("~"))
        if d:
            self.dir_var.set(os.path.normpath(d))

    def open_dir(self):
        d = self.dir_var.get().strip()
        if not os.path.isdir(d):
            messagebox.showinfo("SSL-16", "The folder does not exist yet. It is created at the first PC recording.")
            return
        try:
            if hasattr(os, "startfile"):
                os.startfile(d)                                  # Windows
            else:
                import subprocess, sys
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", d])
        except Exception as e:
            self.log_line("Could not open the folder: %s" % e)

    # ------------------------------------------------------------------ connection
    def refresh_ports(self):
        ports = list(list_ports.comports())
        items = ["%s - %s" % (p.device, p.description) for p in ports]
        self.port_box["values"] = items
        pick = next((i for i, p in enumerate(ports) if p.vid == ESPRESSIF_VID), 0 if ports else None)
        if pick is not None and not self.ser:
            self.port_box.current(pick)
        elif not ports:
            self.port_var.set("")

    def toggle_connect(self):
        if self.ser:
            self.disconnect()
            return
        dev = self.port_var.get().split(" - ")[0].strip()
        if not dev:
            messagebox.showwarning("SSL-16", "No serial port selected. Plug in the board and press Refresh.")
            return
        try:
            self.ser = serial.Serial(dev, 2000000, timeout=0.1, write_timeout=1)
        except Exception as e:
            self.ser = None
            messagebox.showerror("SSL-16", "Could not open %s:\n%s\n\nClose the Serial Monitor or any other "
                                 "program using this port." % (dev, e))
            return
        self.parser = StreamParser()
        self.reader = Reader(self.ser, self.parser, self.q)
        self.reader.start()
        self.status, self.t_last_status = {}, time.time()
        self.last_pkts, self.t_rate = 0, time.time()
        self.conn_btn.configure(text="Disconnect")
        self.port_box.configure(state="disabled")
        self.log_line("Connected to %s" % dev)
        self.send("STATUS")

    def disconnect(self, why=None):
        if self.reader:
            self.reader.stop_flag = True
        self.stop_pc("connection closed")
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass
        self.ser = self.reader = self.parser = None
        self.recording, self.stop_at, self.pending_start, self.stop_sent = False, None, None, None
        self.conn_btn.configure(text="Connect")
        self.port_box.configure(state="readonly")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="disabled")
        self.state_lbl.configure(text="NOT CONNECTED", fg="#888")
        for v in self.fields.values():
            v.configure(text="-")
        self.log_line("Disconnected" + (": " + why if why else ""))

    def send(self, cmd):
        if not self.ser:
            return False
        try:
            self.ser.write((cmd + "\n").encode("ascii"))
            self.log_line("> " + cmd)
            return True
        except Exception as e:
            self.disconnect(str(e))
            return False

    # ------------------------------------------------------------------ recording
    def fill_timestamp(self):
        self.name_var.set(datetime.now().strftime("run_%Y%m%d_%H%M%S"))

    def start_rec(self):
        use_sd, use_pc = self.sd_var.get(), self.pc_var.get()
        if not use_sd and not use_pc:
            messagebox.showwarning("SSL-16", "Tick at least one place to save: SD card or this PC.")
            return
        name = re.sub(r"[^A-Za-z0-9_-]", "", self.name_var.get().strip())[:40]
        if not name and use_pc:                      # PC file needs a name; SD then uses the same one
            name = datetime.now().strftime("run_%Y%m%d_%H%M%S")
        self.name_var.set(name)
        try:
            dur = float(self.dur_var.get() or 0)
            if dur < 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("SSL-16", "Length must be a number of seconds (0 = record until STOP).")
            return
        if use_sd and self.status.get("sd", "ok") != "ok":
            if not messagebox.askyesno("SSL-16", "The board reports SD card = %s.\nThe SD recording will probably "
                                       "not start. Try anyway?" % self.status.get("sd")):
                return
        if use_sd and name and name in self.used_names:
            if not messagebox.askyesno("SSL-16", "'%s' was already recorded in this session.\n"
                                       "The old file on the SD card will be overwritten. Continue?" % name):
                return
        sink = None
        if use_pc:
            folder = self.dir_var.get().strip()
            path = os.path.join(folder, name + "_pc.wav")
            try:
                os.makedirs(folder, exist_ok=True)
                if os.path.exists(path) and not messagebox.askyesno(
                        "SSL-16", "%s already exists on this PC.\nOverwrite it?" % path):
                    return
                sink = PcWav(path)
            except Exception as e:
                messagebox.showerror("SSL-16", "Could not create the PC file:\n%s" % e)
                return
        if use_sd:
            if not self.send("START " + name if name else "START"):
                if sink:
                    sink.close()
                return
            if name:
                self.used_names.add(name)
            self.pending_start = time.time()
        if sink:
            self.pc, self.pc_name, self.pc_follows_sd = sink, name, use_sd
            self.parser.sink_error = None
            self.parser.set_sink(sink)
            self.log_line("PC recording started: %s" % sink.path)
        self.stop_at = time.time() + dur if dur > 0 else None
        self.start_btn.configure(state="disabled")

    def stop_rec(self):
        self.stop_at = None
        if self.recording or self.pending_start:
            self.pending_start = None
            if self.send("STOP"):
                self.stop_sent, self.stop_tries = time.time(), 1
        self.stop_pc()

    def stop_pc(self, why=None):
        if not self.pc:
            return
        if self.parser:
            self.parser.take_sink()
        sink, self.pc = self.pc, None
        try:
            sink.close()
            self.log_line("PC recording saved: %s  (%s, USB lost %d packets)%s"
                          % (sink.path, hms(sink.frames / FS_OUT), sink.lost, " - " + why if why else ""))
        except Exception as e:
            self.log_line("ERROR closing the PC file: %s" % e)

    # ------------------------------------------------------------------ periodic update
    def handle_line(self, line):
        head, kv = parse_kv(line)
        if head == "T":
            self.status.update(kv)
            self.t_last_status = time.time()
            was = self.recording
            rec = kv.get("rec", "-")
            self.recording = rec != "-"
            if self.recording and not was:
                self.rec_name = rec
                self.pending_start = None
                self.log_line("SD recording started: /ssl16/%s.wav" % rec)
            elif was and not self.recording:
                self.stop_sent = None
                self.log_line("SD recording stopped: /ssl16/%s.wav  (%s)" % (self.rec_name, self.fields["length"].cget("text")))
                if self.pc and self.pc_follows_sd:           # board stopped by itself (error, 4 GB, BOOT button)
                    self.stop_at = None
                    self.stop_pc("board stopped")
            if self.recording:
                self.rec_name = rec
        else:
            if "fw" in kv:
                self.status.update(kv)
            self.log_line(line)

    def tick(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "line":
                    self.handle_line(val)
                elif kind == "error" and self.ser:
                    self.disconnect("serial port error (%s)" % val)
        except queue.Empty:
            pass

        if self.ser:
            now = time.time()
            s = self.status
            if self.parser.sink_error:
                err, self.parser.sink_error = self.parser.sink_error, None
                self.stop_pc("ERROR writing the PC file: %s" % err)
            if self.stop_at and now >= self.stop_at:           # timed recording
                self.stop_rec()
            if self.pending_start and now - self.pending_start > 3.0 and not self.recording:
                self.pending_start = None
                self.log_line("SD recording did NOT start - check the SD card (inserted? FAT32/exFAT formatted?)")
                if not self.pc:
                    self.stop_at = None
            if self.stop_sent and self.recording and now - self.stop_sent > 2.0:
                if self.stop_tries < 3:
                    self.stop_tries += 1
                    self.stop_sent = now
                    self.send("STOP")
                else:
                    self.stop_sent = None
                    self.log_line("Board did NOT stop after 3 STOP commands - press the BOOT button on the board")

            stale = now - self.t_last_status > 3.0
            active = self.recording or self.pc is not None
            if stale and not self.pc:
                self.state_lbl.configure(text="NO STATUS FROM BOARD", fg="#c77700")
            elif active:
                where = " + ".join(w for w, on in (("SD", self.recording), ("PC", self.pc is not None)) if on)
                blink = int(now * 2) % 2
                self.state_lbl.configure(text="\u25cf REC  %s  [%s]" % (self.rec_name if self.recording else self.pc_name, where),
                                         fg="#c0392b" if blink else "#7a241b")
            elif self.pending_start:
                self.state_lbl.configure(text="STARTING...", fg="#c77700")
            else:
                self.state_lbl.configure(text="READY", fg="#2e9e4f")
            busy = active or self.pending_start is not None
            self.start_btn.configure(state="disabled" if (busy or stale) else "normal")
            self.stop_btn.configure(state="normal" if busy else "disabled")

            if self.recording:
                kb = int(s.get("rec_kb", 0) or 0)
                self.fields["length"].configure(text=hms(kb * 1024 / BYTES_PER_SEC))
                self.fields["size"].configure(text="%.1f MB" % (kb / 1024))
            if self.pc:
                fr = self.pc.frames
                self.fields["pc"].configure(text="%s  %.1f MB" % (hms(fr / FS_OUT), fr * NCH * 2 / 1048576))
                self.fields["pc_lost"].configure(text="%d packets" % self.pc.lost,
                                                 foreground="#000" if self.pc.lost == 0 else "#c0392b")
            self.fields["remain"].configure(text="%.0f s" % max(0, self.stop_at - now) if self.stop_at else "-")
            if "temp" in s:
                self.fields["temp"].configure(text=("%s \u00b0C" % s["temp"]) if s["temp"] != "nan" else "sensor FAIL")
            sd = s.get("sd", "-")
            self.fields["sd"].configure(text={"ok": "ok", "none": "no card", "FAIL": "FAIL (mount error)"}.get(sd, sd),
                                        foreground="#000" if sd in ("ok", "-") else "#c0392b")
            for key in ("ring_drop", "sd_err"):
                val = s.get(key, "-")
                self.fields[key].configure(text=val, foreground="#000" if val in ("0", "-") else "#c0392b")
            self.fields["fw"].configure(text=s.get("fw", "-"))

            if now - self.t_rate >= 1.0:
                self.rate = (self.parser.packets - self.last_pkts) / (now - self.t_rate)
                self.last_pkts, self.t_rate = self.parser.packets, now
            self.fields["usb"].configure(text="%.0f pkt/s, lost %d" % (self.rate, self.parser.lost))

            peaks = self.parser.take_peaks()
            for slot, pk in enumerate(peaks):
                if not self.bars:
                    break
                bar, x0, x1, top, bot = self.bars[SLOT_MIC[slot] - 1]
                db = 20 * np.log10(max(int(pk), 1) / 32768.0)
                frac = min(max(1.0 - db / METER_FLOOR_DB, 0.0), 1.0)
                self.cv.coords(bar, x0, bot - (bot - top) * frac, x1, bot)
                self.cv.itemconfigure(bar, fill="#e74c3c" if db > -1 else "#e0b030" if db > -12 else "#2e9e4f")
        self.root.after(100, self.tick)

    def on_close(self):
        if self.ser and self.recording:
            ans = messagebox.askyesnocancel("SSL-16", "An SD recording is running on the board.\n\n"
                                            "Yes = stop the recording, then close\n"
                                            "No = close, the board keeps recording (stop it later with the BOOT button)")
            if ans is None:
                return
            if ans:
                self.send("STOP")
                time.sleep(0.5)
        if self.ser:
            self.disconnect()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()