#!/usr/bin/env python3
"""
hdoa_pcb_verify.py - the complete Rev C1 processing chain AND the board verification suite, in ONE file.

Board:   16 x IM73A135V01, sunflower layout R = 80 mm (im73a135_sunflower16_r80_revC1_marked.dxf)
         4 x TLV320ADC5140 -> ESP32-S3 (two TDM ports, 8 x 16-bit slots each) -> USB packets ('HDOA' format)
Laptop:  this file.  Needs numpy; pyserial for a live board; matplotlib (optional) for report.png.

    SECTION 1  constants
    SECTION 2  array geometry (port coordinates) and wiring (TDM slot -> microphone)
    SECTION 3  mounting pose: board coordinates -> room coordinates
    SECTION 4  USB packet format, parser, continuity check, channel re-ordering
    SECTION 5  spectra and cross-spectral matrices (CSM)
    SECTION 6  BUZZER mode: single tone on the floor square -> (x, y);  TABLE-TOP mode: buzzer on the board's own surface -> azimuth
    SECTION 7  HORN mode: harmonic source -> azimuth (and elevation) + tracker
    SECTION 8  calibration from a source at a known position / direction
    SECTION 9  bring-up checks (levels, clipping, per-channel delay)
    SECTION 10 synthetic test signals (exact physics, no external simulator)
    SECTION 11 PCB VERIFICATION SUITE (link, idle, tap, sweep, buzzer, horn) + emulated board
    SECTION 12 command line

BEFORE THE BOARD IS CONNECTED (no hardware needed)
    python hdoa_pcb_verify.py selftest            # algorithm checks on synthetic data
    python hdoa_pcb_verify.py verify-selftest     # the verification suite on emulated healthy / faulty boards
    python hdoa_pcb_verify.py stimuli --out wav   # writes verify_sweep.wav, verify_horn.wav, ... to play back

ON THE BOARD
    Rev D: flash SSL16_HDOA.ino (single daisy chain on IO13, no rework needed; FS below must equal its FS_OUT).
    Rev C1: firmware_esp32s3_hdoa flashed, ADC3 SDOUT -> IO10 rework done, board on USB.
    1. python hdoa_pcb_verify.py verify --port COM5 --stages link,idle
           electrical / data-link health; nothing to play.
    2. python hdoa_pcb_verify.py verify --port COM5 --stages tap
           tap next to each hole when asked -> the real channel map (wiring_measured.json).
    3. python hdoa_pcb_verify.py verify --port COM5 --stages sweep --slotmap <session>/wiring_measured.json
           play verify_sweep.wav from a small loudspeaker 1 m in front of the board (the position is printed)
           -> per-microphone gain, delay, polarity; port A/B alignment; repeatability; calib_sweep.npz.
    4. python hdoa_pcb_verify.py verify --port COM5 --stages buzzer,horn --slotmap ... --calib <session>/calib_sweep.npz
           the two localisation algorithms against positions you measured with a tape.
    or simply all at once:   python hdoa_pcb_verify.py verify --port COM5

TABLE-TOP BUZZER TEST (board flat on a table, top face up; buzzer on the same table, about 1 m away)
    python hdoa_pcb_verify.py verify --port COM5 --stages tabletop                    # buzzer at 0, 90, 180, 270 deg
    python hdoa_pcb_verify.py verify --port COM5 --stages tabletop --table-az 0,45,90 --table-dist 1.0
    python hdoa_pcb_verify.py live --port COM5 --mode tabletop                        # continuous azimuth read-out
    Result = azimuth of the buzzer around the board, counter-clockwise from the DXF +X arrow seen from above.
    The distance only has to be approximate; this geometry cannot measure it.
    Every run writes a session folder: raw captures (*.hdoa), report.txt / report.json / per_mic.csv /
    report.png, wiring_measured.json, calib_sweep.npz.   Re-analyse any time:
           python hdoa_pcb_verify.py verify --replay <session folder>

NORMAL OPERATION (same algorithms as hdoa_pipeline.py)
    python hdoa_pcb_verify.py live --port COM5 --mode buzzer --slotmap wiring_measured.json --calib calib_sweep.npz
    python hdoa_pcb_verify.py record --port COM5 --seconds 20 --out take.hdoa
    python hdoa_pcb_verify.py replay --file take.hdoa --mode horn
    python hdoa_pcb_verify.py walkthrough

Coordinates: room frame x, y horizontal, z up (m).  Microphone numbers M1..M16 and the +X arrow are those of the DXF.
"""
import argparse
import json
import os
import struct
import sys
import time
import wave
import numpy as np

# =====================================================================================================
# SECTION 1 - constants
# =====================================================================================================
FS = 24000                 # sample rate (Hz). 16 ch x 16 bit x 24 kHz = 6.1 Mbit/s, fits USB full speed
NFFT = 512                 # FFT length -> bin spacing FS/NFFT = 46.875 Hz
HOP = NFFT // 2            # 50 % overlap
N_CH = 16
FULL_SCALE_DB_SPL = 138.0  # digital full scale at 0 dB ADC gain: -38 dBV/Pa mic, 2 Vrms ADC input (VERIFY with a calibrator)


def speed_of_sound(temp_c):
    """c = 331.3 + 0.606 T  (m/s). 1 degC error -> 0.18 % scale error in every delay."""
    return 331.3 + 0.606 * temp_c


# =====================================================================================================
# SECTION 2 - array geometry and wiring
# =====================================================================================================
# Sound-port centres as drawn in the DXF, seen from the TOP face (acoustic side).
# Origin = board centre, +X = the 0-degree arrow, angles counter-clockwise. Units: metres.
# Formula used to draw the DXF:   r_k = 0.080 * ((k + 0.5)/16)^0.6,   theta_k = 9 deg + 137.508 deg * k,   k = 0..15 -> M1..M16
def sunflower_ports(R=0.080, n=16, p=0.6, theta0_deg=9.0, golden_deg=137.508):
    k = np.arange(n)
    r = R * ((k + 0.5) / n) ** p
    th = np.radians(theta0_deg + golden_deg * k)
    return np.c_[r * np.cos(th), r * np.sin(th)]


MIC_XY = sunflower_ports()                       # (16, 2), row m = microphone M(m+1)

# The same coordinates as printed in the DXF coordinate table (mm) - checked against the formula in selftest.
DXF_TABLE_MM = np.array([
    [9.877, 1.564], [-16.122, 10.668], [6.361, -25.483], [15.325, 28.252],
    [-35.329, -12.187], [38.669, -16.782], [-18.989, 42.553], [-16.064, -48.167],
    [47.843, 26.590], [-56.913, 13.588], [34.817, -51.463], [9.600, 64.914],
    [-53.540, -43.504], [72.120, -4.280], [-52.491, 54.144], [2.219, -78.459]])

# Wiring (Rev C1 two-port design):
#   I2S port A (IO13): ADC1 (slots 0-3) + ADC2 daisy-chained (slots 4-7)
#   I2S port B (IO10): ADC3 (slots 0-3) + ADC4 daisy-chained (slots 4-7)
#   ADC groups: ADC1 = M1,M4,M9,M12 | ADC2 = M2,M7,M10,M15 | ADC3 = M3,M6,M11,M14 | ADC4 = M5,M8,M13,M16
#   (inputs IN1..IN4 in that order).  Values below are microphone indices (0 = M1).
# If the tap test on the real board gives a different order, edit only this table.
# --- SSL-16 Rev D (single daisy chain U4->U3->U2->U1 -> IO13, 16 TDM slots; firmware SSL16_HDOA.ino) ---
#   stream 0-3  = U1 (0x4C): M2, M7, M10, M15      stream 8-11  = U3 (0x4E): M3, M6, M11, M14
#   stream 4-7  = U2 (0x4D): M1, M4, M9,  M12      stream 12-15 = U4 (0x4F): M5, M8, M13, M16
#   "port A" = stream 0-7, "port B" = stream 8-15; both are the same I2S frame, so port_b_shift = 0.
#   Order confirmed on the board by the self-test tap check (Nov 2026).
#   Rev C1 (two ports) was:  A = [0, 3, 8, 11, 1, 6, 9, 14],  B = [2, 5, 10, 13, 4, 7, 12, 15]
SLOT_TO_MIC = {"A": [1, 6, 9, 14, 0, 3, 8, 11],
               "B": [2, 5, 10, 13, 4, 7, 12, 15]}
SCHEMATIC_NAME = {m: f"MK{m + 1}" for m in range(16)}       # Rev D reference designators MK1..MK16 = M1..M16


def stream_to_mic_index(slot_to_mic=SLOT_TO_MIC):
    """The board sends 16 int16 per frame in STREAM order: port A slots 0..7, then port B slots 0..7.
    Returns s2m with s2m[stream_index] = microphone index, and m2s, its inverse."""
    s2m = np.array(list(slot_to_mic["A"]) + list(slot_to_mic["B"]))
    assert sorted(s2m) == list(range(N_CH)), "slot map must use every microphone exactly once"
    return s2m, np.argsort(s2m)


S2M, M2S = stream_to_mic_index()


def to_mic_order(x_stream):
    """(16, n) in stream order -> (16, n) in microphone order M1..M16.  Row m of the result is mic m."""
    return x_stream[M2S]


WIRING = dict(port_b_shift=0)     # frames by which port B lags port A (measured by the sweep stage); 0 = aligned


def set_wiring(slot_to_mic=None, port_b_shift=None):
    """Replace the schematic channel map / port alignment by measured values (wiring_measured.json)."""
    global S2M, M2S
    if slot_to_mic is not None:
        S2M, M2S = stream_to_mic_index(slot_to_mic)
    if port_b_shift is not None:
        WIRING["port_b_shift"] = int(port_b_shift)


def load_wiring(path=None, port_b_shift=None):
    cfg = json.load(open(path)) if path else {}
    set_wiring(cfg.get("slot_to_mic"), port_b_shift if port_b_shift is not None else cfg.get("port_b_shift"))


class PortAligner:
    """If port B lags port A by k frames (k > 0), delay port A by k frames so both line up (k < 0: delay B).
    Works block by block: the last |k| frames of the delayed port are carried over to the next block."""

    def __init__(self, shift=None):
        self.k = WIRING["port_b_shift"] if shift is None else int(shift)
        self.rows = slice(0, 8) if self.k > 0 else slice(8, 16)
        self.reset()

    def reset(self):
        self.carry = None

    def push(self, x_stream):
        n = abs(self.k)
        if n == 0 or x_stream.shape[1] == 0:
            return x_stream
        if self.carry is None:
            self.carry = np.zeros((8, n), x_stream.dtype)
        joined = np.concatenate([self.carry, x_stream[self.rows]], axis=1)
        out = x_stream.copy()
        out[self.rows] = joined[:, :x_stream.shape[1]]
        self.carry = joined[:, x_stream.shape[1]:]
        return out


# =====================================================================================================
# SECTION 3 - mounting pose (board coordinates -> room coordinates)
# =====================================================================================================
# Room frame: x, y horizontal, z up, metres. For the floor-square demo the square is 0 <= x, y <= 2 m.
# A pose = (centre, ex, ey): where the board centre is, and which room directions the board +X and +Y axes
# point to. The top-face normal (the way the holes "look") is n = ex x ey.
class Pose:
    def __init__(self, centre, ex, ey):
        self.centre = np.asarray(centre, float)
        self.ex = np.asarray(ex, float) / np.linalg.norm(ex)
        self.ey = np.asarray(ey, float) / np.linalg.norm(ey)
        self.n = np.cross(self.ex, self.ey)

    def mics_world(self, xy=MIC_XY):
        """Room coordinates of the 16 ports:  P_m = centre + x_m * ex + y_m * ey."""
        return self.centre[None] + xy[:, :1] * self.ex[None] + xy[:, 1:2] * self.ey[None]


def pose_tilted(centre, heading_deg, tilt_deg):
    """Top face looks towards azimuth `heading`, tilted `tilt` degrees below horizontal.
    Board +X stays horizontal and points to the RIGHT of a person standing in front of the board looking at it."""
    h, t = np.radians(heading_deg), np.radians(tilt_deg)
    n = np.array([np.cos(t) * np.cos(h), np.cos(t) * np.sin(h), -np.sin(t)])
    ex = np.array([-np.sin(h), np.cos(h), 0.0])
    return Pose(centre, ex, np.cross(n, ex))


POSES = {
    # Lab demo: board centre 1 m above corner (0, 0) of the 2 m x 2 m floor square, top face tilted 45 deg down,
    # looking along the square's diagonal.
    "lab_floor_square": pose_tilted((0.0, 0.0, 1.0), heading_deg=45.0, tilt_deg=45.0),
    # Board flat on a table, top face up: azimuth is measured CCW from the DXF +X arrow, seen from above.
    "table_face_up": Pose((0.0, 0.0, 1.2), (1, 0, 0), (0, 1, 0)),
    # Board flat on a pole, top face down towards the road (mirror image of face-up, handled automatically).
    "pole_face_down": Pose((0.0, 0.0, 4.0), (1, 0, 0), (0, -1, 0)),
}
# Table-top test: board lying flat on a table, top face up, on its standoffs (sound ports ~10 mm above the table).
# The buzzer stands on the same table.  Azimuth is counter-clockwise from the DXF +X arrow, seen from above.
POSES["tabletop"] = Pose((0.0, 0.0, 0.010), (1, 0, 0), (0, 1, 0))
FLOOR_REGION = dict(x=(0.0, 2.0), y=(0.0, 2.0), z=0.02)     # buzzers lie on the floor; centre of the sound ~2 cm up


# =====================================================================================================
# SECTION 4 - USB packets
# =====================================================================================================
# Data packet (little-endian), 24-byte header + payload:
#   'HDOA' | uint32 seq | uint64 first_frame | uint16 n_frames | uint16 n_ch | uint16 flags | uint16 reserved
#   int16 data[n_frames][16]  (stream order)
#   flags bit0 = I2S DMA overflow on the board, bit1 = board dropped packets (USB too slow)
# Status packet: 'HDST' | uint16 length | JSON text.     Commands to the board: START / STOP / STATUS lines.
HDR = struct.Struct("<4sIQHHHH")
MAGIC, MAGIC_STATUS = b"HDOA", b"HDST"


def encode_packet(seq, first_frame, x_stream_int16, flags=0):
    x = np.asarray(x_stream_int16, dtype="<i2")
    return HDR.pack(MAGIC, seq, first_frame, x.shape[1], x.shape[0], flags, 0) + x.T.tobytes()


class PacketParser:
    """Byte stream in, packets out. If bytes are lost or corrupted, it skips ahead to the next magic word."""

    def __init__(self):
        self.buf = bytearray()
        self.skipped_bytes = 0

    def feed(self, data):
        self.buf += data
        out = []
        while True:
            hits = [i for i in (self.buf.find(MAGIC), self.buf.find(MAGIC_STATUS)) if i >= 0]
            if not hits:                                   # keep 3 bytes: a magic word may be split across reads
                self.skipped_bytes += max(0, len(self.buf) - 3)
                del self.buf[:-3 or None]
                return out
            i = min(hits)
            self.skipped_bytes += i
            del self.buf[:i]
            if self.buf[:4] == MAGIC_STATUS:
                if len(self.buf) < 6:
                    return out
                n = struct.unpack_from("<H", self.buf, 4)[0]
                if len(self.buf) < 6 + n:
                    return out
                out.append(("status", bytes(self.buf[6:6 + n]).decode("utf-8", "replace")))
                del self.buf[:6 + n]
                continue
            if len(self.buf) < HDR.size:
                return out
            _, seq, first, nfr, nch, flags, _ = HDR.unpack_from(self.buf, 0)
            if nch != N_CH or not 0 < nfr <= 4096:         # not a real header: skip one byte and search again
                self.skipped_bytes += 1
                del self.buf[:1]
                continue
            n = HDR.size + 2 * nfr * nch
            if len(self.buf) < n:
                return out
            x = np.frombuffer(bytes(self.buf[HDR.size:n]), "<i2").reshape(nfr, nch).T.copy()
            out.append(("data", dict(seq=seq, first_frame=first, flags=flags, x=x)))
            del self.buf[:n]


class Assembler:
    """Checks that packets are consecutive, then converts them to float blocks in MICROPHONE order.
    Emits ('block', first_frame, x[16, n] with +-1.0 = full scale) or ('gap', missing_frames).
    After a gap the localisers must be reset, because their averages would mix non-adjacent audio."""

    def __init__(self):
        self.next_frame = None
        self.aligner = PortAligner()
        self.stats = dict(packets=0, gaps=0, missing_frames=0, flagged=0)

    def process(self, packets):
        for kind, p in packets:
            if kind != "data":
                yield (kind, p)
                continue
            self.stats["packets"] += 1
            if p["flags"]:
                self.stats["flagged"] += 1
            if self.next_frame is not None and p["first_frame"] != self.next_frame:
                miss = int(p["first_frame"] - self.next_frame)
                self.stats["gaps"] += 1
                self.stats["missing_frames"] += max(miss, 0)
                self.aligner.reset()
                yield ("gap", miss)
            elif p["flags"]:
                self.aligner.reset()
                yield ("gap", 0)
            self.next_frame = p["first_frame"] + p["x"].shape[1]
            yield ("block", p["first_frame"], to_mic_order(self.aligner.push(p["x"])).astype(np.float64) / 32768.0)


# =====================================================================================================
# SECTION 5 - spectra and cross-spectral matrices
# =====================================================================================================
def stft(x, nfft=NFFT, hop=HOP):
    """x (16, n) -> S (n_frames, 16, nfft/2+1).  Hann window, 50 % overlap.  S[b, m, k] is the complex
    amplitude of microphone m in frequency bin k (f_k = k * FS / nfft) in time frame b."""
    w = np.hanning(nfft)
    nb = 1 + (x.shape[1] - nfft) // hop
    return np.stack([np.fft.rfft(x[:, b * hop:b * hop + nfft] * w, axis=1) for b in range(nb)])


def csm(S, k):
    """Cross-spectral matrix of bin k:  C = mean_b( s_b s_b^H ),  s_b = S[b, :, k] (16 complex values).
    C[m, n] = average of X_m X_n^*: its phase is the phase difference between mics m and n, which is
    what encodes the source position."""
    s = S[:, :, k]
    return np.einsum("bm,bn->mn", s, s.conj()) / s.shape[0]


def beam_power(C, w, remove_diagonal=True):
    """Conventional (delay-and-sum) beamformer output for steering vectors w (n_points, 16):
          P = w^H C w
    With the diagonal of C removed, each microphone's own (uncorrelated) noise does not contribute."""
    if remove_diagonal:
        C = C - np.diag(np.diag(C))
    return np.maximum(np.einsum("pm,mn,pn->p", w.conj(), C, w).real, 0.0)


# =====================================================================================================
# SECTION 6 - BUZZER mode: single tone, source on a known plane (the floor)
# =====================================================================================================
# Idea: for each candidate floor point p, compute what the 16 microphones WOULD receive from a tone at p
# (spherical wave: phase -k r_m, amplitude 1/r_m, r_m = distance from p to mic m), and measure how well the
# recorded CSM matches it (beam_power). The best-matching point is the estimate.
# Near field matters here: the square is 1-3 m from a 0.16 m array, so plane waves would be a poor model.
def find_tone(S, f, band=(300.0, 6000.0)):
    """Strongest spectral peak in the band, its exact frequency (parabolic interpolation on log power across
    bins k-1, k, k+1) and its prominence (peak level minus the median level in the band, dB)."""
    P = np.mean(np.abs(S) ** 2, axis=(0, 1))
    L = 10 * np.log10(P + 1e-30)
    idx = np.where((f >= band[0]) & (f <= band[1]))[0]
    k = int(idx[np.argmax(P[idx])])
    a, b, c = np.log(P[k - 1:k + 2] + 1e-30)
    d = a - 2 * b + c
    f_tone = f[k] + (0.0 if d == 0 else 0.5 * (a - c) / d) * (f[1] - f[0])
    return k, float(f_tone), float(L[k] - np.median(L[idx]))


def spherical_steering(points, mics, f, c):
    """w[p, m] = exp(-j 2 pi f r_pm / c) / r_pm, normalised so ||w_p|| = 1 (every point judged on equal terms)."""
    r = np.linalg.norm(points[:, None, :] - mics[None, :, :], axis=2)
    w = np.exp(-1j * 2 * np.pi * f / c * r) / r
    return w / np.linalg.norm(w, axis=1, keepdims=True)


def floor_map(Cs, f_tone, points, mics, c):
    """Sum over the three bins around the tone of the normalised beam power maps. All three bins hold the same
    tone (Hann window spreads it), so all are steered at the tone frequency, not at the bin centres."""
    w = spherical_steering(points, mics, f_tone, c)
    Z = 0.0
    for C in Cs:
        v = beam_power(C, w)
        Z = Z + v / (v.max() + 1e-30)
    return Z


def grid(xr, yr, step, z):
    xs = np.arange(xr[0], xr[1] + 1e-9, step)
    ys = np.arange(yr[0], yr[1] + 1e-9, step)
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    return gx, gy, np.c_[gx.ravel(), gy.ravel(), np.full(gx.size, z)]


def locate_buzzer(x, pose, temp_c=20.0, W=None, region=FLOOR_REGION, min_prom_db=15.0, verbose=False):
    """x: (16, n) microphone order, typically the last 0.4 s.  Returns a dict with the floor position."""
    c = speed_of_sound(temp_c)
    mics = pose.mics_world()
    f = np.fft.rfftfreq(NFFT, 1 / FS)
    S = stft(x)
    if W is not None:
        S = S * W[None]                                        # calibration (SECTION 8)
    k, f_tone, prom = find_tone(S, f)
    out = dict(detected=prom >= min_prom_db, f_tone=f_tone, prom_db=prom)
    if verbose:
        print(f"  [6a] {S.shape[0]} FFT frames, strongest peak bin {k} ({f[k]:.1f} Hz), "
              f"interpolated tone {f_tone:.1f} Hz, prominence {prom:.1f} dB")
    if not out["detected"]:
        return out
    Cs = [csm(S, b) for b in (k - 1, k, k + 1)]
    if verbose:
        ph = np.degrees(np.angle(Cs[1][:, 0]))
        print(f"  [6b] CSM of bins {k - 1},{k},{k + 1}; phase of C[m, M1] for M1..M16 (deg): {np.round(ph).astype(int).tolist()}")
    gx, gy, P1 = grid(region["x"], region["y"], 0.04, region["z"])            # coarse: 51 x 51 points
    Z = floor_map(Cs, f_tone, P1, mics, c).reshape(gx.shape)
    i, j = np.unravel_index(np.argmax(Z), Z.shape)
    fx, fy, P2 = grid((gx[i, j] - 0.06, gx[i, j] + 0.06), (gy[i, j] - 0.06, gy[i, j] + 0.06), 0.005, region["z"])
    Zf = floor_map(Cs, f_tone, P2, mics, c).reshape(fx.shape)                   # fine: 25 x 25 points
    i2, j2 = np.unravel_index(np.argmax(Zf), Zf.shape)
    p = np.array([fx[i2, j2], fy[i2, j2], region["z"]])
    u = (p - pose.centre) / np.linalg.norm(p - pose.centre)
    out.update(x=float(p[0]), y=float(p[1]), az_deg=float(np.degrees(np.arctan2(u[1], u[0])) % 360),
               el_deg=float(np.degrees(np.arcsin(u[2]))), map=Z, peak_to_mean=float(Z.max() / Z.mean()))
    if verbose:
        print(f"  [6c] coarse 4 cm grid {Z.shape}: best ({gx[i, j]:.2f}, {gy[i, j]:.2f}) m, peak/mean {out['peak_to_mean']:.2f}")
        print(f"  [6d] fine 0.5 cm grid {Zf.shape}: best ({p[0]:.3f}, {p[1]:.3f}) m; "
              f"direction from board az {out['az_deg']:.1f} deg, el {out['el_deg']:.1f} deg")
    return out


class BuzzerStream:
    """Streaming wrapper: keeps the last 0.4 s and produces an estimate every 0.1 s."""
    locate = staticmethod(lambda x, pose, **kw: locate_buzzer(x, pose, **kw))

    def __init__(self, pose, window_s=0.4, update_s=0.1, **kw):
        self.pose, self.kw = pose, kw
        self.win, self.upd = int(window_s * FS), int(update_s * FS)
        self.reset()

    def reset(self):
        self.buf = np.zeros((N_CH, 0))
        self.since = 0
        self.t = 0.0

    def process_block(self, x):
        self.buf = np.concatenate([self.buf, x], axis=1)[:, -self.win:]
        self.since += x.shape[1]
        self.t += x.shape[1] / FS
        if self.since >= self.upd and self.buf.shape[1] >= self.win:
            self.since = 0
            o = self.locate(self.buf, self.pose, **self.kw)
            o["t"] = self.t
            yield o


# ---- TABLE-TOP mode: board and buzzer on the same surface, buzzer roughly 1 m away -------------------------
# The buzzer is (almost) in the plane of the array, so the only quantity the array can measure well is the
# AZIMUTH around the board.  The distance is assumed (default 1.0 m): the wave-front curvature across the
# 157 mm aperture is only ~3 mm at 1 m, so an error of several 10 cm in the assumed distance changes the
# azimuth by a small fraction of a degree, and for the same reason the array cannot measure the distance.
#   steering points: p(az) = centre + d (cos az * ex + sin az * ey) + (h_buzzer - h_board) * n
def tabletop_points(pose, az_deg, dist, src_h):
    a = np.radians(np.atleast_1d(az_deg))
    return (pose.centre[None] + dist * (np.cos(a)[:, None] * pose.ex[None] + np.sin(a)[:, None] * pose.ey[None])
            + (src_h - pose.centre[2]) * pose.n[None])


def locate_tabletop(x, pose, dist=1.0, src_h=0.010, temp_c=20.0, W=None, min_prom_db=15.0, verbose=False):
    """x: (16, n) microphone order.  Returns azimuth (deg, CCW from the DXF +X arrow) of a single-tone buzzer on the
    same surface as the board, plus the peak-to-sidelobe ratio of the azimuth scan as a quality figure."""
    c = speed_of_sound(temp_c)
    mics = pose.mics_world()
    f = np.fft.rfftfreq(NFFT, 1 / FS)
    S = stft(x)
    if W is not None:
        S = S * W[None]
    k, f_tone, prom = find_tone(S, f)
    out = dict(detected=prom >= min_prom_db, f_tone=f_tone, prom_db=prom)
    if not out["detected"]:
        return out
    Cs = [csm(S, b) for b in (k - 1, k, k + 1)]
    az1 = np.arange(0.0, 360.0, 1.0)                                              # coarse: 1 deg
    Z = floor_map(Cs, f_tone, tabletop_points(pose, az1, dist, src_h), mics, c)
    i = int(np.argmax(Z))
    az2 = az1[i] + np.arange(-1.5, 1.5001, 0.05)                                  # fine: 0.05 deg
    Zf = floor_map(Cs, f_tone, tabletop_points(pose, az2, dist, src_h), mics, c)
    az = float(az2[int(np.argmax(Zf))] % 360)
    n = len(Z)
    side = [Z[j] for j in range(n) if Z[j] > Z[j - 1] and Z[j] >= Z[(j + 1) % n] and min((j - i) % n, (i - j) % n) > 2]
    half = Z >= 0.5 * Z[i]
    p = tabletop_points(pose, az, dist, src_h)[0]
    out.update(az_deg=az, x=float(p[0] - pose.centre[0]), y=float(p[1] - pose.centre[1]), map=Z,
               psr_db=float(10 * np.log10(Z[i] / max(side))) if side else float("inf"), beamwidth_deg=float(half.sum()))
    if verbose:
        print(f"  tone {f_tone:.1f} Hz ({prom:.0f} dB), azimuth {az:.2f} deg, beam {out['beamwidth_deg']:.0f} deg wide (-3 dB), "
              f"highest sidelobe {fmt_sidelobe(out['psr_db'])}")
    return out


def fmt_sidelobe(psr_db):
    """Highest other peak of the azimuth scan relative to the main peak.  'none' = every sidelobe is below the
    level that diagonal removal subtracts (about -12 dB for 16 microphones)."""
    return "none" if not np.isfinite(psr_db) else f"{-psr_db:.1f} dB"


class TabletopStream(BuzzerStream):
    """Same streaming wrapper as BuzzerStream (0.4 s window, one estimate per 0.1 s), table-top geometry."""
    locate = staticmethod(lambda x, pose, **kw: locate_tabletop(x, pose, **kw))


# =====================================================================================================
# SECTION 7 - HORN mode: harmonic source, far field, direction only
# =====================================================================================================
# A horn has two or three harmonic series (f0 ~ 300-650 Hz). We (1) detect it by its harmonic pattern, (2) use
# every prominent harmonic between 300 and 5000 Hz, (3) for each one compute a plane-wave beam map over
# directions, and (4) add the maps with weights that favour high, clean harmonics (more angular information).
#   plane-wave steering: w_m(u) = exp(+j 2 pi f (u . p_m) / c), u = unit vector towards the source
#   weight per bin: (f/1 kHz)^2 * SNR^2 / (1 + SNR)   (SNR from the peak prominence, capped at 30 dB)
#   if the highest usable harmonic is < 1.5 kHz, plain (power-weighted) summation is more robust
class HornConfig:
    lam = 0.88                  # CSM averaging: C <- lam C + (1 - lam) s s^H per hop (time constant ~85 ms); None = plain mean
    update_hops = 4             # one estimate every 4 hops = 42.7 ms
    f0_range = (300.0, 650.0)
    det_band = (300.0, 5000.0)
    det_prom_db = 10.0          # a harmonic must stand 10 dB above the local noise floor
    min_harmonics = 3
    loc_band = (300.0, 5000.0)  # sunflower R80 has no grating lobes below ~5.6 kHz
    loc_prom_db = 6.0
    max_bins = 24
    snr_cap_db = 30.0
    power_fallback_hz = 1500.0
    az_step = 5.0               # azimuth grid (deg); parabolic refinement gives sub-grid accuracy
    el_grid = (0.0,)            # elevation rows (deg); use range(0, -65, -5) when the board is above the sources


def moving_percentile(L, q=20, size=31):
    """Local noise floor: q-th percentile of L in a sliding window of `size` bins (edges padded by repetition)."""
    h = size // 2
    Lp = np.r_[np.full(h, L[0]), L, np.full(h, L[-1])]
    return np.percentile(np.lib.stride_tricks.sliding_window_view(Lp, size), q, axis=-1)


def unit_vectors(az_deg, el_deg):
    az, el = np.radians(np.asarray(az_deg, float)), np.radians(np.asarray(el_deg, float))
    ce, se = np.cos(el)[:, None], np.sin(el)[:, None]
    return np.stack([ce * np.cos(az)[None], ce * np.sin(az)[None], np.broadcast_to(se, (len(el), len(az)))], -1)


class HornLocator:
    def __init__(self, pose, temp_c=20.0, W=None, cfg=None):
        self.cfg = cfg or HornConfig()
        self.c = speed_of_sound(temp_c)
        f_all = np.fft.rfftfreq(NFFT, 1 / FS)
        self.kb = np.where(f_all <= self.cfg.det_band[1] + 16 * f_all[1])[0]      # keep bins up to ~5.75 kHz
        self.f = f_all[self.kb]
        self.W = None if W is None else W[:, self.kb]
        self.az = np.arange(0, 360, self.cfg.az_step)
        self.el = np.asarray(self.cfg.el_grid, float)
        rel = pose.mics_world() - pose.centre[None]
        self.D = unit_vectors(self.az, self.el) @ rel.T          # (n_el, n_az, 16): path difference u . p_m (m)
        self.win = np.hanning(NFFT)
        self.reset()

    def reset(self):
        self.C = None
        self.buf = np.zeros((N_CH, 0))
        self.nhop = 0
        self.track = None

    def process_block(self, x):
        cfg = self.cfg
        self.buf = np.concatenate([self.buf, x], axis=1)
        while self.buf.shape[1] >= NFFT:
            X = np.fft.rfft(self.buf[:, :NFFT] * self.win, axis=1)[:, self.kb]
            self.buf = self.buf[:, HOP:]
            if self.W is not None:
                X = X * self.W
            R = np.einsum("mf,nf->fmn", X, X.conj())                    # one CSM per bin from this frame
            self.nhop += 1
            if self.C is None:
                self.C = R
            elif cfg.lam is None:
                self.C += (R - self.C) / self.nhop
            else:
                self.C = cfg.lam * self.C + (1 - cfg.lam) * R
            if self.nhop % cfg.update_hops == 0:
                yield self.estimate()

    def detect(self):
        """Harmonic-series test on the array-averaged spectrum (trace of the CSM)."""
        cfg, f = self.cfg, self.f
        P = np.real(np.einsum("fmm->f", self.C)) / N_CH
        L = 10 * np.log10(P + 1e-30)
        prom = L - moving_percentile(L, 20, 31)
        band = (f >= cfg.det_band[0]) & (f <= cfg.det_band[1])
        is_peak = np.r_[False, (L[1:-1] > L[:-2]) & (L[1:-1] >= L[2:]), False]
        peaks = np.where(is_peak & band & (prom > cfg.det_prom_db))[0]
        best = (0, None)
        if len(peaks):
            f0s = np.arange(cfg.f0_range[0], cfg.f0_range[1], 1.0)
            H = np.arange(1, int(cfg.det_band[1] // cfg.f0_range[0]) + 1)
            target = f0s[:, None] * H[None]                              # every harmonic of every candidate f0
            hit = (np.abs(target[..., None] - f[peaks][None, None]) <= 1.5 * f[1]).any(-1) & (target <= cfg.det_band[1])
            n_h = hit.sum(1)
            j = int(np.argmax(n_h))
            best = (int(n_h[j]), float(f0s[j]))
        return best[0] >= cfg.min_harmonics, best, L, prom, is_peak

    def estimate(self):
        cfg, f = self.cfg, self.f
        ok, (n_h, f0), L, prom, is_peak = self.detect()
        out = dict(t=self.nhop * HOP / FS, detected=bool(ok), f0=f0, n_harmonics=n_h)
        if not ok:
            return out
        cand = np.where(is_peak & (prom > cfg.loc_prom_db) & (f >= cfg.loc_band[0]) & (f <= cfg.loc_band[1]))[0]
        if len(cand) == 0:
            out["detected"] = False
            return out
        bins = cand[np.argsort(L[cand])[::-1][:cfg.max_bins]]
        use_power = f[bins].max() < cfg.power_fallback_hz
        Pmap = np.zeros(self.D.shape[:2])
        for b in bins:
            w = np.exp(1j * 2 * np.pi * f[b] / self.c * self.D)          # plane-wave steering (n_el, n_az, 16)
            Pb = beam_power(self.C[b], w.reshape(-1, N_CH)).reshape(self.D.shape[:2]) / N_CH ** 2
            if use_power:
                Pmap += Pb
            else:
                snr = float(np.clip(10 ** (prom[b] / 10) - 1, 1e-3, 10 ** (cfg.snr_cap_db / 10)))
                Pmap += (f[b] / 1e3) ** 2 * snr ** 2 / (1 + snr) * Pb / (Pb.max() + 1e-30)
        ie = int(np.unravel_index(np.argmax(Pmap), Pmap.shape)[0])
        P = Pmap[ie]
        i, n = int(np.argmax(P)), len(P)
        a, b_, c_ = P[(i - 1) % n], P[i], P[(i + 1) % n]                  # parabola through the peak and neighbours
        d = a - 2 * b_ + c_
        az = (self.az[i] + (0.0 if d == 0 else 0.5 * (a - c_) / d) * cfg.az_step) % 360
        side = [j for j in range(n) if P[j] > P[j - 1] and P[j] >= P[(j + 1) % n] and j != i]
        out.update(az_deg=float(az), el_deg=float(self.el[ie]), n_bins=int(len(bins)), f_top=float(f[bins].max()),
                   psr=float(P[i] / max(P[side])) if side else float("inf"), map=P,
                   weighting="power" if use_power else "f2snr")
        out["track_az_deg"] = self.update_track(az, out["t"])
        return out

    def update_track(self, az, t, alpha=0.5, beta=0.1, gate=30.0, hold_s=0.5):
        """alpha-beta tracker on azimuth: predict, compare, correct; ignore jumps > gate; restart after hold_s."""
        tr = self.track
        if tr is None or t - tr["t"] > hold_s:
            self.track = dict(az=az, rate=0.0, t=t)
            return az
        dt = t - tr["t"]
        pred = tr["az"] + tr["rate"] * dt
        r = (az - pred + 180) % 360 - 180
        if abs(r) > gate:
            tr.update(az=pred % 360, t=t)
            return tr["az"]
        tr["az"] = (pred + alpha * r) % 360
        tr["rate"] += beta * r / max(dt, 1e-3)
        tr["t"] = t
        return tr["az"]


# =====================================================================================================
# SECTION 8 - calibration
# =====================================================================================================
# Each channel has a slightly different gain and phase (mic sensitivity +-1 dB, coupling-capacitor tolerance,
# ADC differences). With a source at a KNOWN position we know what the channels should look like relative to M1:
#   measured   h_m = C_m1 / C_11                    (from the recording)
#   expected   g_m / g_1, g_m = exp(-j k r_m)/r_m   (from the geometry)
#   correction W_m = (g_m / g_1) / h_m              (multiply channel m's spectrum by W_m before forming the CSM)
# Averaging W over 2-3 positions reduces the influence of room reflections.
def calibrate(x, pose, src_pos=None, direction=None, temp_c=20.0, min_snr_db=10.0):
    f = np.fft.rfftfreq(NFFT, 1 / FS)
    c = speed_of_sound(temp_c)
    mics = pose.mics_world()
    S = stft(x)
    C1 = np.mean(S * S[:, :1].conj(), axis=0)                     # (16, F): cross-spectra with M1
    h = C1 / (C1[:1] + 1e-30)
    if src_pos is not None:
        r = np.linalg.norm(mics - np.asarray(src_pos, float)[None], axis=1)
        g = np.exp(-1j * 2 * np.pi * f[None] / c * r[:, None]) / r[:, None]
    else:
        g = np.exp(1j * 2 * np.pi * f[None] / c * ((mics - pose.centre) @ np.asarray(direction, float))[:, None])
    W = (g / g[:1]) / (h + 1e-30)
    L = 10 * np.log10(np.mean(np.abs(S) ** 2, axis=(0, 1)) + 1e-30)
    valid = L > np.median(L) + min_snr_db                         # only bins where the reference source is strong
    W[:, ~valid] = 1.0
    return W, valid


def combine_calibrations(results):
    Ws = np.array([w for w, _ in results])
    V = np.array([v for _, v in results])
    cnt = V.sum(0)
    W = np.where(cnt[None] > 0, (Ws * V[:, None]).sum(0) / np.maximum(cnt, 1)[None], 1.0)
    return W, cnt > 0


# =====================================================================================================
# SECTION 9 - bring-up checks
# =====================================================================================================
def channel_report(x):
    """Level (dBFS and approx. dB SPL), DC offset, clipped samples, dead channels; one row per microphone."""
    rows = []
    for m in range(N_CH):
        rms = float(np.sqrt(np.mean((x[m] - x[m].mean()) ** 2)))
        rows.append(dict(mic=f"M{m + 1}", schematic=SCHEMATIC_NAME[m], rms_dbfs=20 * np.log10(rms + 1e-12),
                         spl_db=20 * np.log10(rms + 1e-12) + FULL_SCALE_DB_SPL - 3.01, dc=float(x[m].mean()),
                         clipped=int(np.sum(np.abs(x[m]) > 0.999)), dead=rms < 1e-5))
    return rows


def residual_delays_us(x, pose, src_pos, temp_c=20.0, band=(300.0, 4000.0), nfft=2048):
    """Broadband source (clap, noise burst) at a known position: per-channel timing error after removing the
    geometric delays, from the slope of phase vs frequency.  A whole port offset by ~41.7 us (one sample at
    24 kHz) means port B is one frame behind/ahead of port A."""
    f = np.fft.rfftfreq(nfft, 1 / FS)
    c = speed_of_sound(temp_c)
    mics = pose.mics_world()
    S = stft(x, nfft, nfft // 2)
    C1 = np.mean(S * S[:, :1].conj(), axis=0)
    h = C1 / (C1[:1] + 1e-30)
    r = np.linalg.norm(mics - np.asarray(src_pos, float)[None], axis=1)
    g = np.exp(-1j * 2 * np.pi * f[None] / c * r[:, None]) / r[:, None]
    ph = np.unwrap(np.angle(h * g[:1] / g), axis=1)                     # phase left after geometry
    sel = (f >= band[0]) & (f <= band[1])
    wts = np.sqrt(np.mean(np.abs(S) ** 2, axis=(0, 1))[sel])
    A = np.c_[2 * np.pi * f[sel], np.ones(sel.sum())] * wts[:, None]
    return np.array([-np.linalg.lstsq(A, ph[m, sel] * wts, rcond=None)[0][0] * 1e6 for m in range(N_CH)])


# =====================================================================================================
# SECTION 10 - synthetic test signals (exact: sum of delayed sinusoids, 1/r spreading)
# =====================================================================================================
def synth(mics, sources, dur, temp_c=20.0, noise_dbfs=-95.0, gain_err_db=None, delay_err_s=None,
          floor_coef=0.0, seed=0):
    """sources: list of (position (x,y,z), [freqs], [rms Pa at 1 m]). Optional mirror source below z = 0
    (floor reflection), per-mic gain/delay errors, white noise, 16-bit quantisation. Returns (16, n), +-1 = FS."""
    rng = np.random.default_rng(seed)
    c = speed_of_sound(temp_c)
    t = np.arange(int(dur * FS)) / FS
    tau = np.zeros(N_CH) if delay_err_s is None else np.asarray(delay_err_s)
    gain = np.ones(N_CH) if gain_err_db is None else 10 ** (np.asarray(gain_err_db) / 20)
    fs_pa = 10 ** ((FULL_SCALE_DB_SPL - 94) / 20) * np.sqrt(2)        # peak pressure at digital full scale
    x = np.zeros((N_CH, len(t)))
    for pos, freqs, amps in sources:
        images = [(np.asarray(pos, float), 1.0)]
        if floor_coef:
            images.append((np.asarray(pos, float) * [1, 1, -1], floor_coef))
        phases = rng.uniform(0, 2 * np.pi, len(freqs))
        for p, coef in images:
            r = np.linalg.norm(mics - p[None], axis=1)
            for fr, a, ph in zip(freqs, amps, phases):
                x += coef * a * np.sqrt(2) / r[:, None] * np.sin(2 * np.pi * fr * (t[None] - r[:, None] / c - tau[:, None]) + ph)
    x = x * gain[:, None] / fs_pa + rng.standard_normal(x.shape) * 10 ** (noise_dbfs / 20)
    return np.round(np.clip(x, -1, 1 - 2 ** -15) * 32767) / 32768.0


def horn_spectrum(f0s=(420.0, 500.0), fmax=6000.0, tilt=0.7, level_db_1m=110.0):
    freqs, amps = [], []
    for f0 in f0s:
        for h in range(1, int(fmax // f0) + 1):
            freqs.append(h * f0)
            amps.append(h ** -tilt)
    amps = np.array(amps) * 10 ** ((level_db_1m - 94) / 20) / np.sqrt(np.sum(np.square(amps)))
    return freqs, list(amps)


def to_packets(x_mic, frames_per_packet=120):
    """What the board would send: microphone order -> stream order -> int16 -> packets."""
    xs = np.round(np.clip(x_mic, -1, 1 - 2 ** -15) * 32768).astype(np.int16)[S2M]
    n = xs.shape[1] // frames_per_packet
    return [encode_packet(i, i * frames_per_packet, xs[:, i * frames_per_packet:(i + 1) * frames_per_packet]) for i in range(n)]


# =====================================================================================================
# SECTION 10b - example signal levels, walkthrough and algorithm selftest
# =====================================================================================================
BUZZ_AMP = [10 ** ((65 - 94) / 20)]        # piezo buzzer, 65 dB SPL at 1 m (= 85 dB at 10 cm)


def walkthrough():
    """One synthetic buzzer, followed stage by stage through the whole chain."""
    pose = POSES["lab_floor_square"]
    mics = pose.mics_world()
    src = (1.30, 0.70, 0.02)
    print("STAGE 2  geometry: 16 ports, radius %.1f-%.1f mm, closest pair %.1f mm" % (
        1000 * np.hypot(*MIC_XY.T).min(), 1000 * np.hypot(*MIC_XY.T).max(),
        1000 * min(np.linalg.norm(MIC_XY[i] - MIC_XY[j]) for i in range(16) for j in range(i))))
    print("STAGE 3  pose 'lab_floor_square': board centre", pose.centre, "face normal", np.round(pose.n, 3))
    print("         mic M1 in the room at", np.round(mics[0], 4), "m; distances to the buzzer %.3f-%.3f m" % (
        np.linalg.norm(mics - src, axis=1).min(), np.linalg.norm(mics - src, axis=1).max()))
    x = synth(mics, [(src, [2700.0], BUZZ_AMP)], 1.0, seed=1)
    print(f"STAGE 10 synthetic recording: buzzer 2700 Hz at {src}, 1.0 s, shape {x.shape}")
    pk = to_packets(x)
    raw = b"".join(pk)
    print(f"STAGE 4  board side: {len(pk)} packets x {len(pk[0])} bytes; first stream channels are mics "
          f"{[f'M{m + 1}' for m in S2M[:4]]} ...")
    parser, asm = PacketParser(), Assembler()
    blocks = [ev[2] for ev in asm.process(parser.feed(raw)) if ev[0] == "block"]
    y = np.concatenate(blocks, axis=1)
    print(f"         laptop side: {asm.stats['packets']} packets, {asm.stats['gaps']} gaps; re-ordered back to "
          f"mic order, max difference {np.abs(y - x[:, :y.shape[1]]).max() * 32768:.0f} LSB")
    print("STAGE 9  levels (dBFS):", [round(float(r["rms_dbfs"]), 1) for r in channel_report(y)][:6], "...")
    print("STAGE 5-6 buzzer localisation on the last 0.4 s:")
    o = locate_buzzer(y[:, -int(0.4 * FS):], pose, verbose=True)
    print(f"RESULT   estimate ({o['x']:.3f}, {o['y']:.3f}) m, true {src[:2]}, error "
          f"{100 * np.hypot(o['x'] - src[0], o['y'] - src[1]):.2f} cm")


def selftest():
    ok = True

    def check(name, val, lim):
        nonlocal ok
        good = val <= lim
        ok &= good
        print(f"[{'PASS' if good else 'FAIL'}] {name}: {val:.3f} (limit {lim})")

    check("coordinates vs DXF table (mm)", float(np.abs(MIC_XY * 1000 - DXF_TABLE_MM).max()), 0.001)
    pose = POSES["lab_floor_square"]
    mics = pose.mics_world()
    x = synth(mics, [((1.3, 0.7, 0.02), [2700.0], BUZZ_AMP)], 1.0, seed=1)
    pk = to_packets(x)
    raw = b"".join(pk[:50]) + b"\x13junk" + b"".join(pk[51:])          # corruption + one lost packet
    parser, asm = PacketParser(), Assembler()
    evs = []
    for i in range(0, len(raw), 4093):
        evs += list(asm.process(parser.feed(raw[i:i + 4093])))
    y = np.concatenate([e[2] for e in evs if e[0] == "block"], axis=1)
    check("re-ordering error (LSB)", float(np.abs(y[:, :6000] - x[:, :6000]).max() * 32768), 1.0)
    check("lost packet detected (|missing - 120| frames)", abs(asm.stats["missing_frames"] - 120), 0)
    o = locate_buzzer(x[:, :9600], pose)
    check("buzzer error, ideal mics (cm)", 100 * np.hypot(o["x"] - 1.3, o["y"] - 0.7), 0.5)
    rng = np.random.default_rng(7)
    ge, de = rng.normal(0, 1.0, 16), rng.normal(0, 5e-6, 16)
    rec = lambda p, s: synth(mics, [(p, [2700.0], BUZZ_AMP)], 0.5, gain_err_db=ge, delay_err_s=de, floor_coef=0.8, seed=s)
    W, _ = combine_calibrations([calibrate(rec(p, 100 + i), pose, src_pos=p)
                                 for i, p in enumerate([(1.0, 1.0, 0.02), (0.5, 1.5, 0.02), (1.5, 0.5, 0.02)])])
    e0, e1 = [], []
    for i, (px, py) in enumerate(rng.uniform(0.05, 1.95, (15, 2))):
        xx = rec((px, py, 0.02), 500 + i)[:, :9600]
        for W_, e in ((None, e0), (W, e1)):
            r = locate_buzzer(xx, pose, W=W_)
            e.append(100 * np.hypot(r["x"] - px, r["y"] - py))
    print(f"       mic errors (gain 1 dB, delay 5 us) + floor reflection: {np.mean(e0):.2f} cm uncalibrated, "
          f"{np.mean(e1):.2f} cm calibrated")
    check("buzzer error after calibration (cm)", float(np.mean(e1)), 1.5)
    fr, am = horn_spectrum()
    for pname, el_src, el_grid in (("table_face_up", 0.0, (0.0,)), ("pole_face_down", -30.0, tuple(range(0, -65, -5)))):
        pz = POSES[pname]
        cfg = HornConfig()
        cfg.lam, cfg.el_grid = None, el_grid
        worst = 0.0
        for az in (20.0, 137.0, 251.0, 333.0):
            u = unit_vectors([az], [el_src])[0, 0]
            xh = synth(pz.mics_world(), [(pz.centre + 3.0 * u, fr, am)], 0.6, noise_dbfs=-80, seed=3)
            res = [r for r in HornLocator(pz, cfg=cfg).process_block(xh) if "az_deg" in r][-1]
            worst = max(worst, abs((res["az_deg"] - az + 180) % 360 - 180))
        check(f"horn azimuth worst error, {pname} (deg)", worst, 0.5)
    xb = synth(mics, [((1.0, 1.0, 0.02), list(np.arange(300, 4000, 37.0)), [0.02] * 100)], 1.0, delay_err_s=de, seed=9)
    d = residual_delays_us(xb, pose, (1.0, 1.0, 0.02))
    check("timing-error estimator (us)", float(np.abs(d - (de - de[0]) * 1e6).max()), 0.5)
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return ok


# =====================================================================================================
# SECTION 11 - PCB verification suite
# =====================================================================================================
# Six stages, run in this order on the real board (--port), on a saved session folder (--replay), or on an
# emulated board with optional injected faults (--emulate):
#   link    USB stream integrity: status reply, ADCs present, frame rate, gaps, overflows, corrupt bytes
#   idle    quiet room: stuck / duplicated / clipped / DC-offset channels, silent I2S port
#   tap     channel map: tap next to each top-face hole in turn -> which stream channel responds
#   sweep   loudspeaker log-sweep from a KNOWN position: per-mic gain, delay, polarity, port-A/B alignment;
#           the direct sound is time-gated, so room reflections arriving > ~1 ms later are removed.
#           Its result is also the calibration file (calib_sweep.npz) used by the later stages and by `live`.
#   buzzer  floor-square demo: buzzers at known (x, y) -> position error, uncalibrated and calibrated
#   horn    board face-up, loudspeaker playing a synthetic horn at known azimuths -> azimuth error
# Every capture is saved as raw bytes, so a session folder can be re-analysed or sent to someone else.
# Limits: the hardware limits come from the earlier bring-up plan (PIPELINE_revC1); the localisation limits are
# engineering judgement (simulation gave 2-3 cm floor-only and 4-13 cm with a wall) and should be tightened once
# real data exist.
VERIFY_LIMITS = dict(
    rate_tol=0.02,            # measured frame rate within +-2 % of FS (wall clock; USB buffering adds jitter)
    dc_max=0.01,              # |DC| < 1 % FS (inputs are AC coupled and the ADC high-pass is on)
    level_pass_db=3.0,        # per-mic level within +-3 dB of the median (mic spec is +-1 dB)
    level_good_db=1.5,
    dead_db=-20.0,            # >= 20 dB low -> dead / unpowered mic
    leg_open_db=(-8.0, -4.5), # ~ -6 dB -> one differential leg (OUT+ or OUT-) not connected
    min_quality=0.80,         # coherence of the channel transfer function with a pure delay model
    delay_pass_us=10.0,       # residual delay after geometry and plane removal
    delay_good_us=5.0,        # 5 us = 1.8 deg phase at 1 kHz, 9 deg at 5 kHz
    port_slip_us=1e6 / FS,    # one frame at FS = 41.7 us
    polarity_deg=90.0,        # |phase intercept| > 90 deg -> polarity inverted
    tap_min_db=6.0,           # tapped channel must be 6 dB above the median channel
    buzz_median_cm=10.0, buzz_max_cm=20.0,
    horn_median_deg=5.0, horn_max_deg=10.0,
    table_median_deg=5.0, table_max_deg=10.0)
ADC_GROUPS = {1: [0, 3, 8, 11], 2: [1, 6, 9, 14], 3: [2, 5, 10, 13], 4: [4, 7, 12, 15]}
ADC_OF_MIC = {m: a for a, ms in ADC_GROUPS.items() for m in ms}
SWEEP = dict(T=3.0, f1=200.0, f2=8000.0, gap=1.0, reps=3)          # the sweep in verify_sweep.wav
SWEEP_BAND = (500.0, 6000.0)                                        # analysis band (window 2.2 ms -> > 450 Hz)
RANK = {"PASS": 0, "INFO": 0, "SKIP": 0, "WARN": 1, "FAIL": 2}


def worst(levels):
    levels = list(levels) or ["PASS"]
    return max(levels, key=lambda s: RANK[s])


def stream_label(k):
    return f"{'A' if k < 8 else 'B'}{k % 8}"


def mic_of_stream(s2m):
    """s2m[k] = microphone carried by stream channel k.  Returns (port label, slot) per microphone."""
    out = {}
    for k, m in enumerate(s2m):
        out[int(m)] = stream_label(k)
    return out


def apply_map(x_stream, s2m):
    """(16, n) stream order -> microphone order, using slot map s2m (stream k carries mic s2m[k])."""
    return x_stream[np.argsort(np.asarray(s2m))]


def decode_capture(raw):
    """Raw USB bytes -> (x_stream (16, n) float, stats, list of status dicts).  No re-ordering; the port A/B
    frame alignment (--port-b-shift) is applied."""
    parser = PacketParser()
    data, stat = [], []
    for kind, p in parser.feed(bytes(raw)):
        (data if kind == "data" else stat).append(p)
    st = dict(packets=len(data), gaps=0, missing_frames=0, flagged=0, skipped_bytes=parser.skipped_bytes)
    nxt, xs = None, []
    for p in data:
        if nxt is not None and p["first_frame"] != nxt:
            st["gaps"] += 1
            st["missing_frames"] += max(int(p["first_frame"]) - int(nxt), 0)
        st["flagged"] += int(p["flags"] != 0)
        nxt = p["first_frame"] + p["x"].shape[1]
        xs.append(p["x"])
    x = np.concatenate(xs, axis=1).astype(np.float64) / 32768.0 if xs else np.zeros((N_CH, 0))
    x = PortAligner().push(x)
    sts = []
    for s in stat:
        try:
            sts.append(json.loads(s))
        except ValueError:
            sts.append({"raw": s})
    return x, st, sts


SETTLE_S = 0.25      # dropped at the start of every capture: ADC power-up and high-pass settling after START


def grab(board, seconds, name, stim):
    """Capture + drop the settling time.  Returns (x_stream, stats)."""
    x, st, _ = board.capture(seconds + SETTLE_S, name, stim)
    return x[:, int(SETTLE_S * FS):], st


def gap_note(st):
    return ([f"WARNING: this capture had {st['gaps']} gap(s) / {st['flagged']} flagged packet(s): timing results are unreliable"]
            if st.get("gaps") or st.get("flagged") else [])


# ---------- stimuli (what the user plays / does) ------------------------------------------------------------
def log_sweep(fs, T=SWEEP["T"], f1=SWEEP["f1"], f2=SWEEP["f2"], ppm=0.0):
    """Exponential sine sweep (Farina).  ppm: playback clock error, for the emulator."""
    t = np.arange(int(T * fs)) / fs * (1 + ppm * 1e-6)
    K = T / np.log(f2 / f1)
    s = np.sin(2 * np.pi * f1 * K * (np.exp(t / K) - 1))
    nf = int(0.02 * fs)
    fade = np.ones(len(s))
    fade[:nf] = 0.5 - 0.5 * np.cos(np.pi * np.arange(nf) / nf)
    fade[-nf:] = fade[:nf][::-1]
    return s * fade


def sweep_train(fs, ppm=0.0, lead_s=0.5):
    one = log_sweep(fs, ppm=ppm)
    gap = np.zeros(int(SWEEP["gap"] * fs))
    return np.concatenate([np.zeros(int(lead_s * fs))] + [np.r_[one, gap]] * SWEEP["reps"])


def pink_noise(n, rng):
    X = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n)
    X[1:] /= np.sqrt(f[1:])
    X[0] = 0
    x = np.fft.irfft(X, n)
    return x / np.std(x)


def horn_signal(fs, dur, level_db_1m=95.0):
    t = np.arange(int(dur * fs)) / fs
    freqs, amps = horn_spectrum(level_db_1m=level_db_1m, fmax=min(6000.0, 0.45 * fs))
    rng = np.random.default_rng(3)
    return sum(a * np.sqrt(2) * np.sin(2 * np.pi * fr * t + rng.uniform(0, 2 * np.pi)) for fr, a in zip(freqs, amps))


def write_wav(path, x, fs=48000):
    x = np.asarray(x, float)
    x = x / (np.max(np.abs(x)) + 1e-12) * 0.7                         # -3 dBFS peak: no clipping in the player
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes(np.round(x * 32767).astype("<i2").tobytes())


def make_stimuli(outdir="."):
    """Writes the files to play from a laptop / phone during the verification."""
    fs, rng = 48000, np.random.default_rng(0)
    os.makedirs(outdir, exist_ok=True)
    files = {"verify_sweep.wav": sweep_train(fs),
             "verify_pink_noise.wav": pink_noise(20 * fs, rng),
             "verify_horn.wav": horn_signal(fs, 20.0),
             "verify_tone_1k.wav": np.sin(2 * np.pi * 1000 * np.arange(10 * fs) / fs)}
    for k, v in files.items():
        write_wav(os.path.join(outdir, k), v, fs)
        print(f"wrote {os.path.join(outdir, k)}  ({len(v) / fs:.1f} s)")


# ---------- three interchangeable board sources ---------------------------------------------------------------
def describe(stim):
    k = stim["kind"]
    if k == "quiet":
        return "Keep the room quiet and do not touch the board."
    if k == "tap":
        m = stim["mic"]
        return (f"Tap or scratch with a fingernail right NEXT TO the top-face hole of M{m + 1} ({SCHEMATIC_NAME[m]}, "
                f"x = {MIC_XY[m, 0] * 1000:+.1f} mm, y = {MIC_XY[m, 1] * 1000:+.1f} mm), about 3 taps per second. "
                "Do not blow into the hole or push anything into it.")
    if k == "sweep":
        return (f"Board in pose '{stim.get('pose')}'. Small loudspeaker at {tuple(stim['pos'])} m (room frame), pointing at the "
                "board; keep walls, tables and people >= 0.6 m away from the speaker-board line. "
                "Press Enter, then START verify_sweep.wav within 1 s (clearly audible, not distorted).")
    if k == "buzzer":
        return f"Place a buzzer at x = {stim['pos'][0]:.2f} m, y = {stim['pos'][1]:.2f} m on the floor square and switch it on."
    if k == "tabletop":
        return (f"Board flat on the table, top face up. Put the buzzer on the same table about {stim['dist']:.1f} m from the "
                f"board centre at azimuth {stim['az']:.0f} deg (counter-clockwise from the DXF +X arrow, seen from above; "
                "0 deg = along the arrow) and switch it on. Keep hands and objects off the line between them.")
    if k == "horn":
        return (f"Board flat, top face up. Loudspeaker {stim['dist']:.1f} m away at azimuth {stim['az']:.0f} deg "
                "(counter-clockwise from the DXF +X arrow, seen from above), at board height. Play verify_horn.wav.")
    return str(stim)


class LiveBoard:
    """The real board over USB CDC (pip install pyserial)."""
    interactive = True

    def __init__(self, port, sess):
        import serial
        self.ser = serial.Serial(port, 2000000, timeout=0.05)
        self.sess = sess

    def command(self, line, timeout=1.5):
        self.ser.write((line + "\n").encode())
        parser, t0 = PacketParser(), time.time()
        while time.time() - t0 < timeout:
            for kind, p in parser.feed(self.ser.read(4096)):
                if kind == "status":
                    try:
                        r = json.loads(p)
                    except ValueError:
                        r = {"raw": p}
                    self.sess.log_command(line, r)
                    return r
        self.sess.log_command(line, None)
        return None

    def capture(self, seconds, name, stim):
        input(f"\n[{name}] {describe(stim)}\n    press Enter to record {seconds:.0f} s ... ")
        self.ser.write(b"STOP\n")                                    # a fresh START for every capture
        time.sleep(0.15)
        self.ser.reset_input_buffer()
        self.ser.write(b"START\n")
        raw, parser = bytearray(), PacketParser()
        need, got, t_first, t_last, f_first, f_last = int(seconds * FS), 0, None, None, None, None
        t_stop = time.time() + 3 * seconds + 5
        while got < need and time.time() < t_stop:
            d = self.ser.read(65536)
            if not d:
                continue
            raw += d
            for kind, p in parser.feed(d):
                if kind == "data":
                    now = time.time()
                    f_last = int(p["first_frame"]) + p["x"].shape[1]
                    got += p["x"].shape[1]
                    if t_first is None:
                        t_first, f_first = now, f_last
                    t_last = now
        self.ser.write(b"STOP\n")
        time.sleep(0.2)
        self.ser.reset_input_buffer()
        rate = (f_last - f_first) / (t_last - t_first) if t_first is not None and t_last - t_first > 1.0 else None
        self.sess.save_capture(name, raw, stim, rate)
        x, st, sts = decode_capture(raw)
        st["wall_rate_hz"] = rate
        return x, st, sts


class ReplayBoard:
    """A saved session folder: same analysis, no hardware, no prompts."""
    interactive = False

    def __init__(self, folder):
        self.folder = folder
        self.meta = json.load(open(os.path.join(folder, "session.json")))
        self.count = {}

    def command(self, line, timeout=0):
        replies = self.meta["commands"].get(line) or [None]
        i = self.count.get(line, 0)
        self.count[line] = i + 1
        return replies[min(i, len(replies) - 1)]

    def capture(self, seconds, name, stim):
        path = os.path.join(self.folder, name + ".hdoa")
        if not os.path.exists(path):
            return np.zeros((N_CH, 0)), dict(packets=0, gaps=0, missing_frames=0, flagged=0, skipped_bytes=0,
                                             wall_rate_hz=None), []
        x, st, sts = decode_capture(open(path, "rb").read())
        st["wall_rate_hz"] = self.meta["captures"].get(name, {}).get("wall_rate_hz")
        return x, st, sts

    def stimulus(self, name, default):
        return self.meta["captures"].get(name, {}).get("stim", default)


class EmulatedBoard:
    """Physics + wiring model of the board, so the whole suite can be tested before the hardware works.
    faults: swap=(mA, mB) wiring swap | port_b_lag=frames | inverted=[m] | leg_open=[m] | dead=[m] |
            stuck_stream=[k] | drop_every=N packets | missing_adc=[a] | ppm=playback clock error."""
    interactive = False

    def __init__(self, sess, faults=None, seed=1, temp_c=20.0, gain_sigma_db=0.5, delay_sigma_us=2.0):
        self.sess, self.f, self.temp = sess, dict(faults or {}), temp_c
        self.rng = np.random.default_rng(seed)
        self.gain_db = self.rng.normal(0, gain_sigma_db, N_CH)
        self.delay_s = self.rng.normal(0, delay_sigma_us, N_CH) * 1e-6
        s2m = list(S2M)
        if "swap" in self.f:
            a, b = self.f["swap"]
            ia, ib = s2m.index(a), s2m.index(b)
            s2m[ia], s2m[ib] = s2m[ib], s2m[ia]
        self.s2m = np.array(s2m)
        self.pose = POSES["lab_floor_square"]

    def command(self, line, timeout=0):
        present = [0 if a in self.f.get("missing_adc", []) else 1 for a in (1, 2, 3, 4)]
        r = dict(fw="emulated", fs=FS, link_mode=1, frames_per_pkt=120, streaming=False, seq=0, pool_drops=0,
                 i2s_ovf=0, gain_db=0, adc_present=present)
        if line.startswith("REGDUMP"):
            r["regdump"] = {"addr": 0x4B + int(line.split()[-1]), "regs": [0] * 128}
        self.sess.log_command(line, r)
        return r

    def _render(self, stim, n):
        pose = POSES[stim.get("pose", "lab_floor_square")]
        mics = pose.mics_world()
        k, srcs, floor = stim["kind"], [], 0.0
        t = np.arange(n) / FS
        if k == "tap":
            p = mics[stim["mic"]] + 0.005 * pose.n
            sig = np.zeros(n)
            for t0 in np.arange(0.3, n / FS - 0.1, 0.33):
                i0 = int(t0 * FS)
                sig[i0:i0 + 24] += 0.02 * self.rng.standard_normal(24) * np.hanning(24)
            srcs.append((p, sig))
        elif k == "sweep":
            s = sweep_train(FS, ppm=self.f.get("ppm", 50.0), lead_s=0.3)[:n]
            srcs.append((np.asarray(stim["pos"], float), 0.3 * np.sqrt(2) * np.r_[s, np.zeros(n - len(s))]))
            floor = 0.6
        elif k == "buzzer":
            p = np.array([stim["pos"][0], stim["pos"][1], FLOOR_REGION["z"]])
            srcs.append((p, BUZZ_AMP[0] * np.sqrt(2) * np.sin(2 * np.pi * stim.get("f", 2700.0) * t)))
            floor = 0.0                                          # buzzer on the floor: its image coincides
        elif k == "tabletop":
            d_true = stim["dist"] + self.f.get("table_range_error", 0.0)      # "approximately 1 m"
            p = tabletop_points(pose, stim["az"], d_true, stim.get("src_h", 0.010))[0]
            srcs.append((p, BUZZ_AMP[0] * np.sqrt(2) * np.sin(2 * np.pi * stim.get("f", 2700.0) * t)))
            floor = 0.9                                          # the table: image source 2 cm below the buzzer
        elif k == "horn":
            a = np.radians(stim["az"])
            p = pose.centre + stim["dist"] * np.array([np.cos(a), np.sin(a), 0.0])
            srcs.append((p, horn_signal(FS, n / FS)))
            floor = 0.5
        x = np.zeros((N_CH, n))
        if srcs:
            c = speed_of_sound(self.temp)
            N = int(2 ** np.ceil(np.log2(n + int(0.05 * FS))))
            f = np.fft.rfftfreq(N, 1 / FS)
            X = np.zeros((N_CH, len(f)), complex)
            for pos, sig in srcs:
                Sg = np.fft.rfft(sig, N)
                imgs = [(pos, 1.0)] + ([(pos * [1, 1, -1], floor)] if floor else [])
                for pp, cf in imgs:
                    r = np.linalg.norm(mics - pp[None], axis=1)
                    X += cf * Sg[None] * np.exp(-2j * np.pi * f[None] * (r[:, None] / c + self.delay_s[:, None])) / r[:, None]
            x = np.fft.irfft(X, N)[:, :n]
            if k == "tap":
                x += 0.03 * x[stim["mic"]][None]                    # structure-borne crosstalk to every channel
        g = 10 ** (self.gain_db / 20)
        for m in self.f.get("inverted", []):
            g[m] = -g[m]
        for m in self.f.get("leg_open", []):
            g[m] *= 0.5
        for m in self.f.get("dead", []):
            g[m] = 0.0
        fs_pa = 10 ** ((FULL_SCALE_DB_SPL - 94) / 20) * np.sqrt(2)
        x = x * g[:, None] / fs_pa + self.rng.standard_normal(x.shape) * 10 ** (-100 / 20)
        for a in self.f.get("missing_adc", []):
            x[ADC_GROUPS[a]] = 0.0
        return x

    def capture(self, seconds, name, stim):
        n = int(seconds * FS) // 120 * 120
        xm = self._render(stim, n)
        xs = np.round(np.clip(xm, -1, 1 - 2 ** -15) * 32768).astype(np.int16)[self.s2m]
        lag = int(self.f.get("port_b_lag", 0))
        if lag:
            xs[8:] = np.c_[np.zeros((8, lag), np.int16), xs[8:, :-lag]]
        for k in self.f.get("stuck_stream", []):
            xs[k] = 0
        pk = [encode_packet(i, i * 120, xs[:, i * 120:(i + 1) * 120]) for i in range(n // 120)]
        de = int(self.f.get("drop_every", 0))
        if de:
            pk = [p for i, p in enumerate(pk) if (i + 1) % de]
        raw = b"".join(pk)
        self.sess.save_capture(name, raw, stim, float(FS))
        x, st, sts = decode_capture(raw)
        st["wall_rate_hz"] = float(FS)
        return x, st, sts


class Session:
    """Folder with every raw capture, the commands' replies, the report and the calibration."""

    def __init__(self, folder):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)
        self.meta = dict(created=time.strftime("%Y-%m-%d %H:%M:%S"), commands={}, captures={})

    def log_command(self, line, reply):
        self.meta["commands"].setdefault(line, []).append(reply)      # every reply, in order

    def save_capture(self, name, raw, stim, rate):
        with open(os.path.join(self.folder, name + ".hdoa"), "wb") as fh:
            fh.write(raw)
        self.meta["captures"][name] = dict(stim=stim, wall_rate_hz=rate, bytes=len(raw))
        self.flush()

    def flush(self):
        json.dump(self.meta, open(os.path.join(self.folder, "session.json"), "w"), indent=1, default=float)


def get_stim(board, name, default):
    return board.stimulus(name, default) if isinstance(board, ReplayBoard) else default


# ---------- stage 1: link ---------------------------------------------------------------------------------------
def stage_link(board, seconds):
    msgs, lv = [], []
    board.command("STOP")
    st0 = board.command("STATUS")
    if st0 is None:
        return dict(verdict="FAIL", msgs=["no STATUS reply: firmware not running, wrong COM port, or USB CDC not up"])
    regs = {k: board.command(f"REGDUMP {k}") for k in (1, 2, 3, 4)}
    present = st0.get("adc_present", [])
    if st0.get("fs") != FS:
        lv.append("FAIL"); msgs.append(f"board reports fs = {st0.get('fs')} Hz, this file expects {FS} Hz")
    for a, p in zip((1, 2, 3, 4), present):
        if not p:
            lv.append("FAIL")
            msgs.append(f"ADC{a} (I2C 0x{0x4B + a:02X}) not answering: check its supply, SHDNZ (IO11), ADDR pins, SDA/SCL")
    x, s, _ = board.capture(seconds, "link", get_stim(board, "link", {"kind": "quiet"}))      # untrimmed: counts every frame
    st1 = board.command("STATUS") or {}
    got = x.shape[1]
    exp_frames = int(seconds * FS) // 120 * 120
    m = dict(frames=got, packets=s["packets"], gaps=s["gaps"], missing_frames=s["missing_frames"],
             flagged=s["flagged"], skipped_bytes=s["skipped_bytes"], wall_rate_hz=s.get("wall_rate_hz"),
             pool_drops=st1.get("pool_drops", 0) - st0.get("pool_drops", 0),
             i2s_ovf=st1.get("i2s_ovf", 0) - st0.get("i2s_ovf", 0), status=st0,
             regdump_ok=[bool(r and "regdump" in r) for r in regs.values()])
    if got < 0.98 * exp_frames:
        lv.append("FAIL"); msgs.append(f"only {got} of ~{exp_frames} frames received")
    for key, why in (("gaps", "lost packets"), ("missing_frames", "missing frames"), ("flagged", "packets flagged by the board"),
                     ("pool_drops", "board dropped packets (USB too slow -> try HDOA_FS_HZ 16000)"),
                     ("i2s_ovf", "I2S DMA overflow on the board")):
        if m[key]:
            lv.append("FAIL"); msgs.append(f"{m[key]} {why}")
    if m["skipped_bytes"]:
        lv.append("WARN"); msgs.append(f"{m['skipped_bytes']} unparseable bytes (USB corruption or a firmware printf in the stream)")
    r = m["wall_rate_hz"]
    if r is None:
        lv.append("WARN"); msgs.append("frame rate not measured (capture too short)")
    elif abs(r / FS - 1) > VERIFY_LIMITS["rate_tol"]:
        lv.append("FAIL"); msgs.append(f"frame rate {r:.0f} Hz, expected {FS} Hz: check BCLK/FSYNC (IO6/IO7) and the ADC clock-detect")
    return dict(verdict=worst(lv), metrics=m, msgs=msgs or ["stream clean"])


# ---------- stage 2: idle ---------------------------------------------------------------------------------------
def stage_idle(board, seconds):
    x, s = grab(board, seconds, "idle", get_stim(board, "idle", {"kind": "quiet"}))
    if x.shape[1] < FS:
        return dict(verdict="FAIL", msgs=["no audio captured"])
    rows, lv, msgs = [], [], []
    xc = x - x.mean(1, keepdims=True)
    rms = np.sqrt(np.mean(xc ** 2, axis=1))
    for k in range(N_CH):
        flags = []
        if np.all(x[k] == x[k, 0]):
            flags.append("STUCK")
        if np.sum(np.abs(x[k]) > 0.999):
            flags.append("CLIP")
        if abs(x[k].mean()) > VERIFY_LIMITS["dc_max"]:
            flags.append("DC")
        rows.append(dict(stream=stream_label(k), rms_dbfs=float(20 * np.log10(rms[k] + 1e-12)),
                         spl_db=float(20 * np.log10(rms[k] + 1e-12) + FULL_SCALE_DB_SPL - 3.01),
                         dc=float(x[k].mean()), flags=flags))
    live = [k for k in range(N_CH) if rms[k] > 0]
    for i in live:
        for j in live:
            if j > i and abs(np.corrcoef(xc[i], xc[j])[0, 1]) > 0.999:
                rows[i]["flags"].append(f"DUP:{stream_label(j)}"); rows[j]["flags"].append(f"DUP:{stream_label(i)}")
    for name, ks in (("A", range(8)), ("B", range(8, 16))):
        if all("STUCK" in rows[k]["flags"] for k in ks):
            lv.append("FAIL")
            msgs.append(f"port {name} completely silent: " + ("check ADC1 SDOUT -> IO13 and ADC2 -> ADC1 daisy chain" if name == "A"
                        else "check the Rev C1 rework (ADC3 SDOUT -> IO10, ADC4 -> ADC3 daisy chain) and I2S1 slave setup"))
    for r in rows:
        if r["flags"]:
            lv.append("FAIL"); msgs.append(f"stream {r['stream']}: {', '.join(r['flags'])}")
    msgs.append(f"median idle level {np.median([r['rms_dbfs'] for r in rows]):.1f} dBFS "
                f"(~{np.median([r['spl_db'] for r in rows]):.0f} dB SPL). At 0 dB gain the 16-bit floor is ~34 dB SPL, so a quiet "
                "room cannot tell a live mic from a dead one: that is decided by the tap and sweep stages.")
    return dict(verdict=worst(lv), rows=rows, msgs=msgs)


# ---------- stage 3: tap / channel map --------------------------------------------------------------------------
def tap_channel(x_stream):
    hp = np.diff(x_stream, axis=1)
    top = max(int(0.002 * hp.shape[1]), 5)
    e = np.sort(np.abs(hp), axis=1)[:, -top:].mean(1)
    k = int(np.argmax(e))
    return k, float(20 * np.log10(e[k] / (np.median(np.delete(e, k)) + 1e-12)))


def stage_tap(board, seconds):
    found, rows, lv, msgs = {}, [], [], []
    for m in range(N_CH):
        name = f"tap_M{m + 1:02d}"
        x, _ = grab(board, seconds, name, get_stim(board, name, {"kind": "tap", "mic": m}))
        if x.shape[1] < FS // 2:
            rows.append(dict(mic=f"M{m + 1}", stream=None, ratio_db=None)); lv.append("FAIL"); continue
        k, ratio = tap_channel(x)
        rows.append(dict(mic=f"M{m + 1}", schematic=SCHEMATIC_NAME[m], stream=stream_label(k), expected=stream_label(int(M2S[m])),
                         ratio_db=ratio))
        if ratio < VERIFY_LIMITS["tap_min_db"]:
            lv.append("FAIL"); msgs.append(f"M{m + 1}: weak response ({ratio:.1f} dB) - repeat, or mic dead / port blocked")
        else:
            found[m] = k
    diff = [f"M{m + 1}: expected {stream_label(int(M2S[m]))}, found {stream_label(k)}" for m, k in found.items() if k != M2S[m]]
    if diff:
        lv.append("WARN"); msgs.append("channel map differs from the schematic: " + "; ".join(diff))
    s2m = None
    missing = [m for m in range(N_CH) if m not in found]
    free = [k for k in range(N_CH) if k not in found.values()]
    if len(set(found.values())) != len(found):
        lv.append("FAIL"); msgs.append("two microphones answered on the same stream channel: repeat the tap stage; "
                                       "later stages use the schematic map")
    elif all(int(M2S[m]) in free for m in missing):                  # silent mics: assume their schematic slots
        s2m = np.zeros(N_CH, int)
        for m, k in found.items():
            s2m[k] = m
        for m in missing:
            s2m[int(M2S[m])] = m
        msgs.append("channel map matches the schematic" if not diff and not missing else
                    "later stages use the MEASURED map" + (f" (schematic slots assumed for the silent mics "
                    f"{[f'M{m + 1}' for m in missing]})" if missing else ""))
    else:
        lv.append("FAIL"); msgs.append("map could not be completed: later stages use the schematic map")
    return dict(verdict=worst(lv), rows=rows, msgs=msgs, s2m=None if s2m is None else s2m.tolist())


# ---------- stage 4: sweep (gain, delay, polarity, port alignment) and calibration ------------------------------
def gate_window(pre, post, rise, fall):
    """Flat-topped time gate: half-Hann rise, 1.0 across the direct sound of every mic, half-Hann fall."""
    w = np.ones(pre + post)
    w[:rise] = 0.5 - 0.5 * np.cos(np.pi * (np.arange(rise) + 0.5) / rise)
    w[-fall:] = 0.5 + 0.5 * np.cos(np.pi * (np.arange(fall) + 0.5) / fall)
    return w


def sweep_transfer(x_mic, nfft=2048, pre_s=0.0010, post_s=0.0013):
    """Deconvolve every channel with the known sweep, find each sweep repetition's direct-sound peak, gate
    -1.0 ... +1.3 ms around it (flat from -0.5 to +0.7 ms; the mics differ by at most +-0.23 ms) and return
    the averaged transfer functions H (16, nfft/2+1).  Reflections arriving later than ~1 ms are suppressed."""
    s = log_sweep(FS)
    N = int(2 ** np.ceil(np.log2(x_mic.shape[1] + len(s))))
    Sf = np.fft.rfft(s, N)
    X = np.fft.rfft(x_mic, N, axis=1)
    h = np.fft.irfft(X * Sf.conj()[None] / (np.abs(Sf) ** 2 + 1e-3 * np.max(np.abs(Sf)) ** 2)[None], N, axis=1)
    env = np.sum(h ** 2, axis=0)
    env[x_mic.shape[1]:] = 0                                         # only causal (real) positions
    period = int((SWEEP["T"] + SWEEP["gap"]) * FS)
    peaks, e = [], env.copy()
    while len(peaks) < SWEEP["reps"] + 2:
        p = int(np.argmax(e))
        if e[p] < 0.3 * env.max() or e[p] == 0:
            break
        peaks.append(p)
        e[max(0, p - period // 2):p + period // 2] = 0
    pre, post = int(round(pre_s * FS)), int(round(post_s * FS))
    win = gate_window(pre, post, int(round(0.0005 * FS)), int(round(0.0006 * FS)))
    H = 0
    for p in peaks:
        if p - pre < 0:
            continue
        H = H + np.fft.rfft(h[:, p - pre:p + post] * win[None], nfft, axis=1)
    return H, len(peaks)


def fit_delay(hrel, f, w):
    """hrel ~ a exp(j(phi0 - 2 pi f tau)).  Coarse grid then fine grid on |sum w hrel exp(+j 2 pi f tau)|."""
    w = w / (w.sum() + 1e-30)
    taus = np.arange(-500.0, 500.5, 1.0) * 1e-6
    sc = np.abs(np.exp(2j * np.pi * np.outer(taus, f)) @ (w * hrel))
    t0 = taus[int(np.argmax(sc))]
    taus = t0 + np.arange(-1.5, 1.5001, 0.02) * 1e-6
    z = np.exp(2j * np.pi * np.outer(taus, f)) @ (w * hrel)
    i = int(np.argmax(np.abs(z)))
    q = float(np.abs(z[i]) / (np.sum(w * np.abs(hrel)) + 1e-30))
    return float(taus[i]), float(np.angle(z[i])), q


def remove_plane(tau, xy, ok, is_b):
    """Model  tau_m = a + b x_m + c y_m + d [m on port B]:
       a, b, c  = what a slightly wrong source position / board pose produces (not a board property),
       d        = timing offset between the two I2S ports (a board / firmware property).
    Robust least squares (outliers dropped); returns per-mic residuals, (a, b, c), d."""
    use = ok.copy()
    A = np.c_[np.ones(N_CH), xy, is_b.astype(float)]
    two_ports = is_b[ok].any() and (~is_b[ok]).any()
    if not two_ports:
        A = A[:, :3]
    coef = np.zeros(A.shape[1])
    for _ in range(5):
        if use.sum() < A.shape[1] + 2:
            break
        coef = np.linalg.lstsq(A[use], tau[use], rcond=None)[0]
        res = tau - A @ coef
        mad = 1.4826 * np.median(np.abs(res[use] - np.median(res[use])))
        new = ok & (np.abs(res) < max(4 * mad, 3e-6))
        if np.array_equal(new, use):
            break
        use = new
    res = tau - A @ coef
    return res, coef[:3], (float(coef[3]) if two_ports else float("nan"))


def analyse_sweep(x_mic, pose, src_pos, s2m, temp_c=20.0):
    H, npk = sweep_transfer(x_mic)
    f = np.fft.rfftfreq(2048, 1 / FS)
    band = (f >= SWEEP_BAND[0]) & (f <= SWEEP_BAND[1])
    if npk == 0 or not np.any(np.abs(H) > 0):
        return None
    c = speed_of_sound(temp_c)
    mics = pose.mics_world()
    r = np.linalg.norm(mics - np.asarray(src_pos, float)[None], axis=1)
    g = np.exp(-2j * np.pi * f[None] * r[:, None] / c) / r[:, None]
    lev = 10 * np.log10(np.mean(np.abs(H[:, band] / g[:, band]) ** 2, axis=1) + 1e-30)
    rel = lev - np.median(lev)
    ref = int(np.argmin(np.abs(rel)))
    tau, phi, q = np.zeros(N_CH), np.zeros(N_CH), np.zeros(N_CH)
    for m in range(N_CH):
        hrel = (H[m, band] / (H[ref, band] + 1e-30)) * (g[ref, band] / g[m, band])
        tau[m], phi[m], q[m] = fit_delay(hrel, f[band], np.abs(H[ref, band]) ** 2)
    ok = (rel > VERIFY_LIMITS["dead_db"]) & (q > VERIFY_LIMITS["min_quality"])
    phi = (phi + np.pi) % (2 * np.pi) - np.pi
    if np.sum(np.abs(phi[ok]) > np.pi / 2) > ok.sum() / 2:           # the reference channel itself was the inverted one
        phi = (phi + 2 * np.pi) % (2 * np.pi) - np.pi
    port = mic_of_stream(s2m)
    is_b = np.array([port[m][0] == "B" for m in range(N_CH)])
    res, coef, d = remove_plane(tau, MIC_XY, ok, is_b)
    # Delays for the CALIBRATION: everything except the least-squares plane.  A plane in the delays cannot be told
    # apart from a small error in the stated loudspeaker position (1 cm at 1 m = 0.6 deg), so it is left out;
    # the port offset and all per-microphone differences stay in.
    A3 = np.c_[np.ones(N_CH), MIC_XY]
    cal_tau = tau - A3 @ np.linalg.lstsq(A3[ok], tau[ok], rcond=None)[0] if ok.sum() >= 5 else np.zeros(N_CH)
    dir_err = float(np.degrees(np.arcsin(min(1.0, np.hypot(coef[1], coef[2]) * c))))
    return dict(level_db=rel, tau_us=tau * 1e6, res_us=res * 1e6, port_offset_us=d * 1e6, is_b=is_b, cal_tau_us=cal_tau * 1e6,
                phase_deg=np.degrees(phi), quality=q, ok=ok, ref=ref, n_sweeps=npk, dir_err_deg=dir_err, H=H, f=f)


def judge_sweep(a, s2m):
    L = VERIFY_LIMITS
    port = mic_of_stream(s2m)
    rows, lv, msgs = [], [], []
    for m in range(N_CH):
        fl, v = [], "PASS"
        d, lvl, ph = a["res_us"][m], a["level_db"][m], a["phase_deg"][m]
        if lvl < L["dead_db"]:
            fl.append("DEAD (no signal)"); v = "FAIL"
        elif L["leg_open_db"][0] <= lvl <= L["leg_open_db"][1]:
            fl.append(f"LEVEL {lvl:+.1f} dB: one output leg (OUT+ or OUT-) open?"); v = "FAIL"
        elif abs(lvl) > L["level_pass_db"]:
            fl.append(f"LEVEL {lvl:+.1f} dB"); v = "FAIL"
        elif abs(lvl) > L["level_good_db"]:
            fl.append(f"level {lvl:+.1f} dB"); v = worst([v, "WARN"])
        if a["quality"][m] < L["min_quality"] and lvl >= L["dead_db"]:
            fl.append(f"poor fit (quality {a['quality'][m]:.2f}): noise, distortion or wrong map"); v = "FAIL"
        if abs(ph) > L["polarity_deg"] and lvl >= L["dead_db"]:
            fl.append(f"POLARITY inverted (phase {ph:+.0f} deg): OUT+/OUT- swapped"); v = "FAIL"
        if a["ok"][m]:
            if abs(d) > L["delay_pass_us"]:
                fl.append(f"DELAY {d:+.1f} us"); v = "FAIL"
            elif abs(d) > L["delay_good_us"]:
                fl.append(f"delay {d:+.1f} us"); v = worst([v, "WARN"])
        rows.append(dict(mic=f"M{m + 1}", schematic=SCHEMATIC_NAME[m], adc=ADC_OF_MIC[m], stream=port[m],
                         level_db=float(lvl), res_delay_us=float(d), phase_deg=float(ph), quality=float(a["quality"][m]),
                         verdict=v, flags=fl))
        lv.append(v)
    off = float(a["port_offset_us"])
    if np.isfinite(off) and abs(off) > L["delay_pass_us"]:
        lv.append("FAIL")
        k = off / L["port_slip_us"]
        whole = abs(k - round(k)) < 0.25 and round(k) != 0
        msgs.append(f"port B - port A offset {off:+.1f} us" + (f" = {k:+.2f} frames: the two I2S ports are not frame-aligned. "
                    f"Fix in firmware (start both ports on the same FSYNC edge) or, if it is the same after every START, "
                    f"run with --port-b-shift {int(round(k))}" if whole else " (not a whole number of frames: check BCLK/FSYNC routing to ADC3/ADC4)"))
    else:
        msgs.append(f"port B - port A offset {off:+.1f} us (limit {L['delay_pass_us']:.0f} us)")
    for adc, ms in ADC_GROUPS.items():
        if all(rows[m]["verdict"] == "FAIL" for m in ms):
            msgs.append(f"all four mics of ADC{adc} fail: suspect that ADC's MICBIAS, its register setup (REGDUMP {adc}) or its SDOUT")
    if a["dir_err_deg"] > 5:
        lv.append("WARN"); msgs.append(f"delays imply the source is {a['dir_err_deg']:.1f} deg from where you said: re-measure the speaker / board pose")
    msgs.append(f"{a['n_sweeps']} sweeps found; reference channel M{a['ref'] + 1}; source-direction mismatch {a['dir_err_deg']:.1f} deg")
    return rows, worst(lv), msgs, off


def calibration_from_sweep(a):
    """Per-mic correction W_m(f) = 1/hrel_m = 10^(-level/20) exp(-j phi0) exp(+j 2 pi f tau), on the pipeline's
    FFT grid (16 x NFFT/2+1); tau = measured delay minus its least-squares plane (see analyse_sweep): per-mic
    differences and the port offset are corrected, a common tilt (= source-position / pose error) is not."""
    f = np.fft.rfftfreq(NFFT, 1 / FS)
    tau = a["cal_tau_us"] * 1e-6
    W = (10 ** (-a["level_db"] / 20))[:, None] * np.exp(-1j * np.radians(a["phase_deg"]))[:, None] \
        * np.exp(2j * np.pi * f[None] * tau[:, None])
    W[~a["ok"]] = 1.0                                                # no trustworthy measurement: leave untouched
    W[a["level_db"] < VERIFY_LIMITS["dead_db"]] = 0.0                # dead microphone: remove it from the beamformer
    return W


def stage_sweep(board, s2m, pose_name, src_pos, temp_c, seconds, folder, runs=2):
    """`runs` separate captures (each after a fresh START): the second one shows whether delays and the port
    offset are REPEATABLE, which is what makes a stored calibration usable."""
    results, msgs, lv, rows = [], [], [], None
    for i in range(runs):
        name = "sweep" if i == 0 else f"sweep_run{i + 1}"
        stim = get_stim(board, name, {"kind": "sweep", "pos": list(src_pos), "pose": pose_name})
        x, st = grab(board, seconds, name, stim)
        if x.shape[1] < FS:
            msgs.append(f"{name}: no audio captured"); lv.append("FAIL"); continue
        a = analyse_sweep(apply_map(x, s2m), POSES[stim.get("pose", pose_name)], stim["pos"], s2m, temp_c)
        if a is None:
            msgs.append(f"{name}: no sweep found - was verify_sweep.wav playing during the capture?"); lv.append("FAIL"); continue
        msgs += gap_note(st)
        results.append(a)
    if not results:
        return dict(verdict="FAIL", msgs=msgs), None
    a = results[0]
    rows, v, m2, off = judge_sweep(a, s2m)
    lv.append(v); msgs += m2
    out = dict(rows=rows, port_offset_us=off, analysis=a)
    if len(results) > 1:
        b = results[1]
        both = a["ok"] & b["ok"]
        d_delay = float(np.max(np.abs(a["res_us"][both] - b["res_us"][both]))) if both.any() else float("nan")
        d_level = float(np.max(np.abs(a["level_db"][both] - b["level_db"][both]))) if both.any() else float("nan")
        d_port = float(abs(a["port_offset_us"] - b["port_offset_us"]))
        out["repeat"] = dict(delay_us=d_delay, level_db=d_level, port_us=d_port)
        bad = d_port > 5.0 or d_delay > 5.0 or d_level > 1.0
        lv.append("FAIL" if d_port > 5.0 else "WARN" if bad else "PASS")
        msgs.append(f"repeatability after a new START: per-mic delay within {d_delay:.2f} us, level within {d_level:.2f} dB, "
                    f"port offset change {d_port:.2f} us" + (" -> the port A/B alignment CHANGES between starts: "
                    "a stored calibration cannot fix this, the firmware start sequence must" if d_port > 5.0 else ""))
    W = calibration_from_sweep(a)
    np.savez(os.path.join(folder, "calib_sweep.npz"), W=W, valid=np.ones(W.shape[1], bool))
    msgs.append(f"calibration written to {os.path.join(folder, 'calib_sweep.npz')}")
    out.update(verdict=worst(lv), msgs=msgs)
    return out, W


def common_rotation(pose, true_xy, est_xy, z):
    """Is the buzzer error one common rotation (board not aimed exactly as assumed) or scatter?
    Best rigid rotation (Kabsch) of the estimated directions onto the true ones, as seen from the board centre;
    returns the rotation angle (deg) and the position errors (cm) that remain after undoing it."""
    T = np.c_[np.asarray(true_xy, float), np.full(len(true_xy), z)] - pose.centre
    E = np.c_[np.asarray(est_xy, float), np.full(len(est_xy), z)] - pose.centre
    ut, ue = T / np.linalg.norm(T, axis=1)[:, None], E / np.linalg.norm(E, axis=1)[:, None]
    U, _, Vt = np.linalg.svd(ue.T @ ut)
    D = np.diag([1.0, 1.0, np.sign(np.linalg.det(U @ Vt))])
    R = (U @ D @ Vt).T                                              # ut ~ R ue
    ang = float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))
    v = ue @ R.T
    hit = pose.centre[None] + v * ((z - pose.centre[2]) / v[:, 2])[:, None]      # rays back onto the floor plane
    return ang, 100 * np.hypot(hit[:, 0] - T[:, 0] - pose.centre[0], hit[:, 1] - T[:, 1] - pose.centre[1])


# ---------- stage 5: buzzer localisation --------------------------------------------------------------------------
DEFAULT_BUZZ = [(1.0, 1.0), (0.5, 0.5), (1.5, 0.5), (0.5, 1.5), (1.5, 1.5)]


def buzzer_estimate(x_mic, pose, temp_c, W):
    est, bs, step = [], BuzzerStream(pose, temp_c=temp_c, W=W), int(0.1 * FS)
    for i in range(0, x_mic.shape[1] - step + 1, step):              # the same 0.1 s blocks as in live operation
        for o in bs.process_block(x_mic[:, i:i + step]):
            if o["detected"]:
                est.append((o["x"], o["y"], o["f_tone"]))
    if not est:
        return None
    e = np.array(est)
    return float(np.median(e[:, 0])), float(np.median(e[:, 1])), float(np.median(e[:, 2])), len(e)


def stage_buzzer(board, s2m, positions, temp_c, W, seconds):
    pose = POSES["lab_floor_square"]
    rows, lv = [], []
    for i, p in enumerate(positions):
        name = f"buzzer_{i + 1:02d}"
        stim = get_stim(board, name, {"kind": "buzzer", "pos": list(p)})
        x, _ = grab(board, seconds, name, stim)
        xm = apply_map(x, s2m)
        row = dict(true_x=stim["pos"][0], true_y=stim["pos"][1])
        for tag, w in (("raw", None), ("cal", W)):
            if tag == "cal" and w is None:
                continue
            r = buzzer_estimate(xm, pose, temp_c, w) if x.shape[1] > FS // 2 else None
            if r is None:
                row[f"err_{tag}_cm"] = None
                continue
            row.update({f"x_{tag}": r[0], f"y_{tag}": r[1], f"err_{tag}_cm": 100 * float(np.hypot(r[0] - row["true_x"], r[1] - row["true_y"])),
                        "f_tone": r[2]})
        rows.append(row)
    L, msgs = VERIFY_LIMITS, []
    for tag in ("raw", "cal"):
        errs = [r.get(f"err_{tag}_cm") for r in rows if f"err_{tag}_cm" in r]
        if not errs:
            continue
        if any(e is None for e in errs):
            lv.append("FAIL"); msgs.append(f"{tag}: buzzer not detected at {sum(e is None for e in errs)} position(s)")
        e = np.array([v for v in errs if v is not None])
        if len(e):
            med, mx = float(np.median(e)), float(e.max())
            v = "PASS" if med <= L["buzz_median_cm"] and mx <= L["buzz_max_cm"] else "FAIL"
            if tag == "cal" or W is None:
                lv.append(v)
            msgs.append(f"{'calibrated' if tag == 'cal' else 'uncalibrated'}: median error {med:.1f} cm, max {mx:.1f} cm "
                        f"(limits {L['buzz_median_cm']:.0f} / {L['buzz_max_cm']:.0f} cm) -> {v}")
            got = [r for r in rows if r.get(f"err_{tag}_cm") is not None]
            if len(got) >= 4 and (tag == "cal" or W is None):
                ang, rem = common_rotation(pose, [(r["true_x"], r["true_y"]) for r in got],
                                           [(r[f"x_{tag}"], r[f"y_{tag}"]) for r in got], FLOOR_REGION["z"])
                msgs.append(f"diagnostic: the errors are equivalent to a common rotation of {ang:.2f} deg (board mounting / "
                            f"aim / stated positions); after undoing it the median error would be {np.median(rem):.1f} cm, "
                            f"max {rem.max():.1f} cm (optimistic: 3 parameters fitted to {len(got)} points)")
    return dict(verdict=worst(lv), rows=rows, msgs=msgs)


# ---------- stage 6: horn direction --------------------------------------------------------------------------------
def stage_horn(board, s2m, azimuths, dist, temp_c, W, seconds):
    pose = POSES["table_face_up"]
    rows, lv = [], []
    for i, az in enumerate(azimuths):
        name = f"horn_{i + 1:02d}"
        stim = get_stim(board, name, {"kind": "horn", "az": float(az), "dist": float(dist), "pose": "table_face_up"})
        x, _ = grab(board, seconds, name, stim)
        xm = apply_map(x, s2m)
        row = dict(true_az=stim["az"])
        for tag, w in (("raw", None), ("cal", W)):
            if tag == "cal" and w is None:
                continue
            loc = HornLocator(pose, temp_c=temp_c, W=w)
            est = [o["az_deg"] for o in loc.process_block(xm) if o.get("detected") and "az_deg" in o]
            if not est:
                row[f"err_{tag}_deg"] = None
                continue
            ang = np.radians(est)
            az_med = float(np.degrees(np.arctan2(np.median(np.sin(ang)), np.median(np.cos(ang)))) % 360)
            row.update({f"az_{tag}": az_med, f"err_{tag}_deg": float(abs((az_med - stim["az"] + 180) % 360 - 180)),
                        f"n_{tag}": len(est)})
        rows.append(row)
    L, msgs = VERIFY_LIMITS, []
    for tag in ("raw", "cal"):
        errs = [r.get(f"err_{tag}_deg") for r in rows if f"err_{tag}_deg" in r]
        if not errs:
            continue
        if any(e is None for e in errs):
            lv.append("FAIL"); msgs.append(f"{tag}: horn not detected at {sum(e is None for e in errs)} azimuth(s)")
        e = np.array([v for v in errs if v is not None])
        if len(e):
            med, mx = float(np.median(e)), float(e.max())
            v = "PASS" if med <= L["horn_median_deg"] and mx <= L["horn_max_deg"] else "FAIL"
            if tag == "cal" or W is None:
                lv.append(v)
            msgs.append(f"{'calibrated' if tag == 'cal' else 'uncalibrated'}: median error {med:.1f} deg, max {mx:.1f} deg "
                        f"(limits {L['horn_median_deg']:.0f} / {L['horn_max_deg']:.0f} deg) -> {v}")
    return dict(verdict=worst(lv), rows=rows, msgs=msgs)


# ---------- optional stage: table-top buzzer azimuth -------------------------------------------------------------
def stage_tabletop(board, s2m, azimuths, dist, src_h, temp_c, W, seconds):
    """Board and buzzer on the same surface.  For every stated azimuth: estimated azimuth, error, beam quality.
    Because the board's arrow is aligned by eye, the COMMON offset of all errors is reported separately from
    their scatter: the offset is a set-up error, the scatter is what the array and the algorithm contribute."""
    pose = POSES["tabletop"]
    rows, lv, msgs = [], [], []
    for i, az in enumerate(azimuths):
        name = f"tabletop_{i + 1:02d}"
        stim = get_stim(board, name, {"kind": "tabletop", "az": float(az), "dist": float(dist), "src_h": float(src_h),
                                      "pose": "tabletop"})
        x, _ = grab(board, seconds, name, stim)
        xm = apply_map(x, s2m)
        row = dict(true_az=stim["az"])
        for tag, w in (("raw", None), ("cal", W)):
            if tag == "cal" and w is None:
                continue
            ts, est, step = TabletopStream(pose, temp_c=temp_c, W=w, dist=stim["dist"], src_h=stim["src_h"]), [], int(0.1 * FS)
            for j in range(0, xm.shape[1] - step + 1, step):
                est += [o for o in ts.process_block(xm[:, j:j + step]) if o["detected"]]
            if not est:
                row[f"err_{tag}_deg"] = None
                continue
            ang = np.radians([o["az_deg"] for o in est])
            az_med = float(np.degrees(np.arctan2(np.median(np.sin(ang)), np.median(np.cos(ang)))) % 360)
            spread = float(np.degrees(np.sqrt(np.mean(np.angle(np.exp(1j * (ang - np.radians(az_med)))) ** 2))))
            row.update({f"az_{tag}": az_med, f"err_{tag}_deg": float((az_med - stim["az"] + 180) % 360 - 180),
                        f"spread_{tag}_deg": spread, "f_tone": float(np.median([o["f_tone"] for o in est])),
                        f"psr_{tag}_db": float(np.median([o["psr_db"] for o in est])),
                        "beamwidth_deg": float(np.median([o["beamwidth_deg"] for o in est]))})
        rows.append(row)
    L = VERIFY_LIMITS
    for tag in ("raw", "cal"):
        errs = [r.get(f"err_{tag}_deg") for r in rows if f"err_{tag}_deg" in r]
        if not errs:
            continue
        if any(e is None for e in errs):
            lv.append("FAIL"); msgs.append(f"{tag}: buzzer tone not detected at {sum(e is None for e in errs)} position(s)")
        e = np.array([v for v in errs if v is not None])
        if len(e):
            med, mx = float(np.median(np.abs(e))), float(np.abs(e).max())
            v = "PASS" if med <= L["table_median_deg"] and mx <= L["table_max_deg"] else "FAIL"
            if tag == "cal" or W is None:
                lv.append(v)
            msgs.append(f"{'calibrated' if tag == 'cal' else 'uncalibrated'}: median |error| {med:.1f} deg, max {mx:.1f} deg "
                        f"(limits {L['table_median_deg']:.0f} / {L['table_max_deg']:.0f} deg) -> {v}")
            if len(e) >= 3:
                off = float(np.degrees(np.angle(np.mean(np.exp(1j * np.radians(e))))))
                rest = (e - off + 180) % 360 - 180
                msgs.append(f"   common offset {off:+.1f} deg (how far the board's +X arrow is turned from where you assumed); "
                            f"scatter around it: max {np.abs(rest).max():.1f} deg")
    f_t = [r["f_tone"] for r in rows if "f_tone" in r]
    if f_t:
        msgs.append(f"buzzer tone {np.median(f_t):.0f} Hz; beam {np.median([r['beamwidth_deg'] for r in rows if 'beamwidth_deg' in r]):.0f} deg wide "
                    f"at -3 dB (this is the RESOLUTION for two buzzers of the same pitch, not the accuracy for one)")
    return dict(verdict=worst(lv), rows=rows, msgs=msgs)


# ---------- the suite ------------------------------------------------------------------------------------------------
STAGES = ("link", "idle", "tap", "sweep", "buzzer", "horn")       # run by default
ALL_STAGES = STAGES + ("tabletop",)                               # 'tabletop' only when asked for: --stages tabletop


def run_verification(board, folder, stages=STAGES, sweep_pose="lab_floor_square", sweep_src=None, sweep_runs=2,
                     buzz_positions=DEFAULT_BUZZ, horn_az=(0, 90, 180, 270), horn_dist=3.0, temp_c=20.0,
                     table_az=(0, 90, 180, 270), table_dist=1.0, table_src_h=0.010, table_s=3.0,
                     link_s=60.0, idle_s=5.0, tap_s=3.0, sweep_s=14.0, buzz_s=3.0, horn_s=4.0, calib=None, quiet=False):
    rep, s2m, W = {}, S2M.copy(), (np.load(calib)["W"] if calib else None)
    if sweep_src is None:                                            # 1 m in front of the board, on its axis
        sweep_src = tuple(np.round(POSES[sweep_pose].centre + 1.0 * POSES[sweep_pose].n, 3))
    say = (lambda *a: None) if quiet else print
    if "link" in stages:
        rep["link"] = stage_link(board, link_s)
    if "idle" in stages:
        rep["idle"] = stage_idle(board, idle_s)
    if "tap" in stages:
        rep["tap"] = stage_tap(board, tap_s)
        if rep["tap"].get("s2m") is not None:
            s2m = np.array(rep["tap"]["s2m"])
    if "sweep" in stages:
        rep["sweep"], W_sweep = stage_sweep(board, s2m, sweep_pose, sweep_src, temp_c, sweep_s, folder, sweep_runs)
        if W_sweep is not None and rep["sweep"]["verdict"] != "FAIL":
            W = W_sweep
        elif W_sweep is not None:
            rep["sweep"]["msgs"].append("sweep stage FAILED: its calibration is NOT applied in the later stages")
    if "buzzer" in stages:
        rep["buzzer"] = stage_buzzer(board, s2m, buzz_positions, temp_c, W, buzz_s)
    if "horn" in stages:
        rep["horn"] = stage_horn(board, s2m, horn_az, horn_dist, temp_c, W, horn_s)
    if "tabletop" in stages:
        rep["tabletop"] = stage_tabletop(board, s2m, table_az, table_dist, table_src_h, temp_c, W, table_s)
    rep["slot_map_used"] = {"A": [int(v) for v in s2m[:8]], "B": [int(v) for v in s2m[8:]]}
    json.dump({"slot_to_mic": rep["slot_map_used"], "port_b_shift": WIRING["port_b_shift"]},
              open(os.path.join(folder, "wiring_measured.json"), "w"), indent=1)
    write_report(rep, folder, say)
    return rep


def write_report(rep, folder, say=print):
    lines = [f"HDOA Rev C1 board verification - {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    for st in ALL_STAGES:
        if st not in rep:
            continue
        r = rep[st]
        lines.append(f"[{r['verdict']:4s}] {st}")
        lines += [f"         {m}" for m in r.get("msgs", [])]
    if "sweep" in rep and rep["sweep"].get("rows"):
        lines += ["", "per-microphone results (sweep stage)",
                  "mic  schem.  ADC stream  level dB  delay us  phase deg  quality  verdict  notes"]
        for r in rep["sweep"]["rows"]:
            lines.append(f"{r['mic']:<4} {r['schematic']:<7} {r['adc']:>3} {r['stream']:>6} {r['level_db']:+9.2f} {r['res_delay_us']:+9.2f} "
                         f"{r['phase_deg']:+10.1f} {r['quality']:8.3f}  {r['verdict']:<7}  {'; '.join(r['flags'])}")
    if "tap" in rep and rep["tap"].get("rows"):
        lines += ["", "tap stage: mic -> stream channel (expected)"]
        lines += [f"  {r['mic']:<4} -> {r.get('stream')} ({r.get('expected')})  {r['ratio_db'] if r['ratio_db'] is None else round(r['ratio_db'], 1)} dB"
                  for r in rep["tap"]["rows"]]
    if "tabletop" in rep and rep["tabletop"].get("rows"):
        lines += ["", "table-top stage", "stated az   estimate   error    spread   sidelobe"]
        for r in rep["tabletop"]["rows"]:
            tag = "cal" if r.get("az_cal") is not None else "raw"
            lines.append(f"{r['true_az']:8.1f}   " + ("not detected" if r.get(f"az_{tag}") is None else
                         f"{r[f'az_{tag}']:8.2f}  {r[f'err_{tag}_deg']:+6.2f}  {r[f'spread_{tag}_deg']:7.2f}  {fmt_sidelobe(r[f'psr_{tag}_db'])}"))
    lines += ["", f"slot map used: {rep['slot_map_used']}",
              f"OVERALL: {worst(rep[s]['verdict'] for s in ALL_STAGES if s in rep)}"]
    txt = "\n".join(lines)
    say("\n" + txt)
    open(os.path.join(folder, "report.txt"), "w").write(txt + "\n")
    slim = {k: ({kk: vv for kk, vv in v.items() if kk != "analysis"} if isinstance(v, dict) else v) for k, v in rep.items()}
    json.dump(slim, open(os.path.join(folder, "report.json"), "w"), indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
    if "sweep" in rep and rep["sweep"].get("rows"):
        with open(os.path.join(folder, "per_mic.csv"), "w") as fh:
            fh.write("mic,schematic,adc,stream,level_db,res_delay_us,phase_deg,quality,verdict,flags\n")
            for r in rep["sweep"]["rows"]:
                fh.write(f"{r['mic']},{r['schematic']},{r['adc']},{r['stream']},{r['level_db']:.3f},{r['res_delay_us']:.3f},"
                         f"{r['phase_deg']:.2f},{r['quality']:.4f},{r['verdict']},\"{'; '.join(r['flags'])}\"\n")
    if ("sweep" in rep and rep["sweep"].get("rows")) or "buzzer" in rep:
        try:
            plot_report(rep, os.path.join(folder, "report.png"))
        except ImportError:
            pass                                                     # matplotlib not installed: text reports only


def plot_report(rep, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(1, 3, figsize=(15, 4.2))
    if "sweep" in rep and rep["sweep"].get("rows"):
        rows = rep["sweep"]["rows"]
        col = ["#2a7" if r["verdict"] == "PASS" else "#e90" if r["verdict"] == "WARN" else "#c33" for r in rows]
        lab = [r["mic"] for r in rows]
        axs[0].bar(lab, [r["level_db"] for r in rows], color=col)
        for y in (-3, 3):
            axs[0].axhline(y, ls="--", c="k", lw=0.8)
        axs[0].set(title="Level re median (dB)", ylabel="dB")
        axs[1].bar(lab, [r["res_delay_us"] for r in rows], color=col)
        for y in (-10, 10):
            axs[1].axhline(y, ls="--", c="k", lw=0.8)
        axs[1].set(title="Residual delay (us)", ylabel="us")
        for ax in axs[:2]:
            ax.tick_params(axis="x", rotation=90)
    if "buzzer" in rep:
        ax = axs[2]
        ax.add_patch(plt.Rectangle((0, 0), 2, 2, fill=False, ec="k"))
        for r in rep["buzzer"]["rows"]:
            ax.plot(r["true_x"], r["true_y"], "k+", ms=12)
            for tag, mk in (("raw", "o"), ("cal", "s")):
                if r.get(f"x_{tag}") is not None:
                    ax.plot([r["true_x"], r[f"x_{tag}"]], [r["true_y"], r[f"y_{tag}"]], "-", c="0.6", lw=0.8)
                    ax.plot(r[f"x_{tag}"], r[f"y_{tag}"], mk, mfc="none", c="#c33" if tag == "raw" else "#27a",
                            label="uncalibrated" if tag == "raw" else "calibrated")
        h, l = ax.get_legend_handles_labels()
        d = dict(zip(l, h))
        ax.legend(d.values(), d.keys(), loc="upper right")
        ax.set(xlim=(-0.1, 2.1), ylim=(-0.1, 2.1), aspect="equal", title="Buzzer: true (+) vs estimate", xlabel="x (m)", ylabel="y (m)")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def verify_selftest():
    """The suite on emulated boards: a healthy board must pass, every injected fault must be reported."""
    import tempfile
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")

    short = dict(link_s=3.0, idle_s=2.0, tap_s=1.5, sweep_s=13.0, buzz_s=2.0, horn_s=3.0, quiet=True)
    d = tempfile.mkdtemp(prefix="hdoa_verify_")

    s = Session(os.path.join(d, "healthy"))
    eb = EmulatedBoard(s)
    rep = run_verification(eb, s.folder, **short)
    for st in STAGES:
        check(f"healthy board: stage '{st}' = {rep[st]['verdict']}", rep[st]["verdict"] in ("PASS", "WARN") and
              (st in ("sweep", "horn", "buzzer") or rep[st]["verdict"] == "PASS"))
    a = rep["sweep"]["analysis"]
    true_d = eb.delay_s * 1e6
    A = np.c_[np.ones(N_CH), MIC_XY]
    true_res = true_d - A @ np.linalg.lstsq(A, true_d, rcond=None)[0]
    est = a["res_us"] + np.where(a["is_b"], a["port_offset_us"], 0.0)
    est = est - A @ np.linalg.lstsq(A, est, rcond=None)[0]
    err_d = float(np.max(np.abs(est - true_res)))
    check(f"measured delays match the emulated ones (worst {err_d:.2f} us, limit 1 us)", err_d < 1.0)
    g = eb.gain_db - np.median(eb.gain_db)
    err_g = float(np.max(np.abs(a["level_db"] - g)))
    check(f"measured levels match the emulated ones (worst {err_g:.2f} dB, limit 0.3 dB)", err_g < 0.3)
    e_cal = [r["err_cal_cm"] for r in rep["buzzer"]["rows"]]
    e_raw = [r["err_raw_cm"] for r in rep["buzzer"]["rows"]]
    check(f"buzzer positions: max error {max(e_raw):.1f} cm uncalibrated, {max(e_cal):.1f} cm with sweep calibration (limit 3 cm)",
          max(e_cal) < 3.0 and max(e_cal) <= max(e_raw) + 0.5)
    healthy_offset = rep["sweep"]["port_offset_us"]
    e_h = [r["err_cal_deg"] for r in rep["horn"]["rows"]]
    check(f"horn azimuths with sweep calibration: max error {max(e_h):.1f} deg (limit 5 deg)", max(e_h) < 5.0)

    os.makedirs(os.path.join(d, "healthy_replay"))
    rep2 = run_verification(ReplayBoard(s.folder), os.path.join(d, "healthy_replay"), **short)
    same = all(abs(r1["res_delay_us"] - r2["res_delay_us"]) < 1e-9 for r1, r2 in zip(rep["sweep"]["rows"], rep2["sweep"]["rows"]))
    check("replaying the saved session gives identical per-mic numbers", same and rep2["buzzer"]["verdict"] == rep["buzzer"]["verdict"])

    s = Session(os.path.join(d, "faulty_a"))
    rep = run_verification(EmulatedBoard(s, faults=dict(swap=(4, 9), dead=[2])), s.folder, stages=("tap", "sweep", "buzzer"), **short)
    check("wiring swap M5 <-> M10 found by the tap stage", any("M5:" in m and "M10:" in m for m in rep["tap"]["msgs"]))
    check("dead M3 reported by the tap stage", any(m.startswith("M3:") for m in rep["tap"]["msgs"]))
    check(f"with the measured map and M3 removed the buzzer stage still passes ({rep['buzzer']['verdict']})",
          rep["buzzer"]["verdict"] == "PASS")
    s = Session(os.path.join(d, "faulty_a2"))
    rep = run_verification(EmulatedBoard(s, faults=dict(port_b_lag=1, inverted=[6], leg_open=[13], dead=[2])),
                           s.folder, stages=("sweep",), **short)
    rows = {r["mic"]: r for r in rep["sweep"]["rows"]}
    check("M7 polarity inversion flagged", any("POLARITY" in fl for fl in rows["M7"]["flags"]))
    check("M14 open output leg flagged (-6 dB)", any("leg" in fl for fl in rows["M14"]["flags"]))
    check("M3 dead flagged", any("DEAD" in fl for fl in rows["M3"]["flags"]))
    check(f"port B one-frame lag reported ({rep['sweep']['port_offset_us']:+.1f} us)", any("--port-b-shift 1" in m for m in rep["sweep"]["msgs"]))
    others = [r["verdict"] for m, r in rows.items() if m not in ("M7", "M14", "M3")]
    check("the 13 healthy microphones of that board are not blamed", all(vd != "FAIL" for vd in others))

    set_wiring(port_b_shift=1)
    try:
        s = Session(os.path.join(d, "faulty_a_fixed"))
        rep = run_verification(EmulatedBoard(s, faults=dict(port_b_lag=1)), s.folder, stages=("sweep", "buzzer"), **short)
    finally:
        set_wiring(port_b_shift=0)
    check(f"--port-b-shift 1 repairs the lag (offset {rep['sweep']['port_offset_us']:+.2f} us, healthy board {healthy_offset:+.2f} us)",
          abs(rep["sweep"]["port_offset_us"] - healthy_offset) < 0.5 and rep["buzzer"]["verdict"] == "PASS")

    s = Session(os.path.join(d, "tabletop"))
    rep = run_verification(EmulatedBoard(s), s.folder, stages=("tabletop",), table_az=(0, 60, 135, 250, 330), table_s=2.0, quiet=True)
    e = max(abs(r["err_raw_deg"]) for r in rep["tabletop"]["rows"])
    check(f"table-top stage, buzzer at exactly 1.0 m: max azimuth error {e:.2f} deg (limit 2 deg)", e < 2.0)
    s = Session(os.path.join(d, "tabletop_far"))
    rep = run_verification(EmulatedBoard(s, faults=dict(table_range_error=0.4)), s.folder, stages=("tabletop",),
                           table_az=(0, 60, 135, 250, 330), table_s=2.0, quiet=True)
    e = max(abs(r["err_raw_deg"]) for r in rep["tabletop"]["rows"])
    check(f"table-top stage, buzzer really at 1.4 m while 1.0 m is assumed: max error {e:.2f} deg (limit 2 deg)", e < 2.0)

    s = Session(os.path.join(d, "faulty_b"))
    rep = run_verification(EmulatedBoard(s, faults=dict(stuck_stream=[11], drop_every=40, missing_adc=[3])), s.folder,
                           stages=("link", "idle"), **short)
    check("lost packets reported by the link stage", any("lost packets" in m for m in rep["link"]["msgs"]))
    check("missing ADC3 reported", any(m.startswith("ADC3") for m in rep["link"]["msgs"]))
    check("stuck stream channel B3 reported by the idle stage", any(m.startswith("stream B3") for m in rep["idle"]["msgs"]))
    print("VERIFY SELFTEST:", "ALL PASS" if ok else "SOME CHECKS FAILED", "| session folders in", d)
    return ok


def parse_faults(items):
    """--fault port_b_lag=1 --fault inverted=7 --fault swap=5,10 ...  (microphone numbers as on the DXF: 1..16)"""
    f = {}
    for it in items or []:
        k, val = it.split("=")
        nums = [float(t) if "." in t else int(t) for t in val.split(",")]
        if k in ("port_b_lag", "drop_every", "ppm", "table_range_error"):
            f[k] = nums[0]
        elif k == "swap":
            f[k] = (nums[0] - 1, nums[1] - 1)
        elif k in ("inverted", "leg_open", "dead"):
            f[k] = [n - 1 for n in nums]
        elif k in ("stuck_stream", "missing_adc"):
            f[k] = nums
        else:
            raise SystemExit(f"unknown fault '{k}'")
    return f


def run_verify_cli(a):
    load_wiring(a.slotmap, a.port_b_shift)
    folder = a.out or time.strftime("verify_%Y%m%d_%H%M%S")
    stages = tuple(t.strip() for t in a.stages.split(",")) if a.stages else STAGES
    bad = [t for t in stages if t not in ALL_STAGES]
    if bad:
        raise SystemExit(f"unknown stage(s) {bad}; choose from {ALL_STAGES}")
    kw = dict(stages=stages, sweep_pose=a.sweep_pose, temp_c=a.temp, calib=a.calib, sweep_runs=a.sweep_runs,
              horn_dist=a.horn_dist, link_s=a.link_seconds)
    if a.sweep_src:
        kw["sweep_src"] = tuple(float(t) for t in a.sweep_src.split(","))
    if a.buzz:
        kw["buzz_positions"] = [tuple(float(t) for t in b.split(",")) for b in a.buzz]
    if a.horn_az:
        kw["horn_az"] = tuple(float(t) for t in a.horn_az.split(","))
    if a.table_az:
        kw["table_az"] = tuple(float(t) for t in a.table_az.split(","))
    kw.update(table_dist=a.table_dist, table_src_h=a.table_buzzer_height)
    if a.replay:
        board = ReplayBoard(a.replay)
        folder = a.out or os.path.join(a.replay, "reanalysis_" + time.strftime("%H%M%S"))
        os.makedirs(folder, exist_ok=True)
    else:
        sess = Session(folder)
        board = EmulatedBoard(sess, faults=parse_faults(a.fault)) if a.emulate else LiveBoard(a.port, sess)
    rep = run_verification(board, folder, **kw)
    print(f"\nsession folder: {folder}")
    return worst(rep[s]["verdict"] for s in ALL_STAGES if s in rep) != "FAIL"


# =====================================================================================================
# SECTION 12 - command line
# =====================================================================================================
def byte_source(args):
    """Yields raw byte chunks from the live board (--port) or a recording (--file)."""
    if args.file:
        with open(args.file, "rb") as f:
            while True:
                d = f.read(65536)
                if not d:
                    return
                if getattr(args, "realtime", False):
                    time.sleep(len(d) / (FS * N_CH * 2))
                yield d
        return
    import serial                                                    # pip install pyserial
    ser = serial.Serial(args.port, 2000000, timeout=0.05)            # baud rate is ignored by USB CDC
    rec = open(args.record_to, "wb") if getattr(args, "record_to", None) else None
    ser.reset_input_buffer()
    ser.write(b"START\n")
    try:
        while True:
            d = ser.read(65536)
            if rec and d:
                rec.write(d)
            yield d
    finally:
        ser.write(b"STOP\n")
        ser.close()
        if rec:
            rec.close()


def audio_blocks(args, seconds=None):
    parser, asm = PacketParser(), Assembler()
    got = 0
    for chunk in byte_source(args):
        for ev in asm.process(parser.feed(chunk)):
            if ev[0] == "status":
                print("board status:", ev[1])
            elif ev[0] in ("block", "gap"):
                if ev[0] == "block":
                    got += ev[2].shape[1]
                yield ev
        if seconds is not None and got >= seconds * FS:
            break
    audio_blocks.stats = asm.stats


def run_localiser(args):
    load_wiring(args.slotmap, args.port_b_shift)
    pose = POSES[args.pose or {"buzzer": "lab_floor_square", "tabletop": "tabletop"}.get(args.mode, "table_face_up")]
    W = np.load(args.calib)["W"] if args.calib else None
    if args.mode == "buzzer":
        loc = BuzzerStream(pose, temp_c=args.temp, W=W)
    elif args.mode == "tabletop":
        loc = TabletopStream(pose, temp_c=args.temp, W=W, dist=args.table_dist, src_h=args.table_buzzer_height)
        print(f"table-top mode: azimuth counter-clockwise from the DXF +X arrow (seen from above); x, y are in the board "
              f"frame for the ASSUMED distance of {args.table_dist:.2f} m")
    else:
        cfg = HornConfig()
        if args.el_scan:
            cfg.el_grid = tuple(range(0, -65, -5))
        loc = HornLocator(pose, temp_c=args.temp, W=W, cfg=cfg)
    log = open(args.log, "w")
    log.write("t_s,detected,x_m,y_m,az_deg,el_deg,f_hz,quality\n")
    try:
        for ev in audio_blocks(args):
            if ev[0] == "gap":
                loc.reset()
                print(f"gap of {ev[1]} frames - averages reset")
                continue
            for o in loc.process_block(ev[2]):
                if args.mode == "tabletop":
                    log.write(f"{o['t']:.3f},{o['detected']},{o.get('x', '')},{o.get('y', '')},{o.get('az_deg', '')},0.0,"
                              f"{o['f_tone']:.1f},{o['prom_db']:.1f}\n")
                    if o["detected"]:
                        print(f"t={o['t']:7.2f} s  f={o['f_tone']:7.1f} Hz  azimuth={o['az_deg']:7.2f} deg  "
                              f"(x={o['x']:+.3f} m, y={o['y']:+.3f} m at the assumed distance)  sidelobe {fmt_sidelobe(o['psr_db'])}")
                elif args.mode == "buzzer":
                    log.write(f"{o['t']:.3f},{o['detected']},{o.get('x', '')},{o.get('y', '')},{o.get('az_deg', '')},"
                              f"{o.get('el_deg', '')},{o['f_tone']:.1f},{o['prom_db']:.1f}\n")
                    if o["detected"]:
                        print(f"t={o['t']:7.2f} s  f={o['f_tone']:7.1f} Hz  x={o['x']:.3f} m  y={o['y']:.3f} m  "
                              f"prominence={o['prom_db']:.0f} dB")
                else:
                    log.write(f"{o['t']:.3f},{o['detected']},,,{o.get('az_deg', '')},{o.get('el_deg', '')},{o.get('f0', '')},{o.get('psr', '')}\n")
                    if o["detected"]:
                        print(f"t={o['t']:7.2f} s  az={o['az_deg']:6.1f}  tracked={o['track_az_deg']:6.1f}  "
                              f"el={o['el_deg']:5.1f}  harmonics used={o['n_bins']}")
    except KeyboardInterrupt:
        pass
    finally:
        log.close()
        print("stream stats:", getattr(audio_blocks, "stats", {}), "| log:", args.log)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("walkthrough")
    sub.add_parser("selftest")
    for name in ("live", "replay"):
        p = sub.add_parser(name)
        if name == "live":
            p.add_argument("--port", required=True)
            p.set_defaults(file=None)
        else:
            p.add_argument("--file", required=True)
            p.add_argument("--realtime", action="store_true")
            p.set_defaults(port=None)
        p.add_argument("--mode", choices=["buzzer", "tabletop", "horn"], required=True,
                       help="buzzer: floor square below a tilted board | tabletop: board and buzzer on the same surface | horn")
        p.add_argument("--table-dist", type=float, default=1.0, help="tabletop: assumed buzzer distance (m)")
        p.add_argument("--table-buzzer-height", type=float, default=0.010, help="tabletop: buzzer sound hole above the table (m)")
        p.add_argument("--pose", choices=list(POSES))
        p.add_argument("--calib")
        p.add_argument("--temp", type=float, default=20.0)
        p.add_argument("--el-scan", action="store_true")
        p.add_argument("--log", default="estimates.csv")
        p.add_argument("--slotmap", help="wiring_measured.json from the verification")
        p.add_argument("--port-b-shift", type=int, help="frames by which port B lags port A")
    p = sub.add_parser("record")
    p.add_argument("--port", required=True)
    p.add_argument("--seconds", type=float, default=10.0)
    p.add_argument("--out", required=True)
    p.set_defaults(file=None)
    p = sub.add_parser("calibrate")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--port")
    g.add_argument("--file")
    p.add_argument("--pose", default="lab_floor_square", choices=list(POSES))
    p.add_argument("--src", action="append", required=True, help="x,y,z (m) of the reference source; repeat")
    p.add_argument("--seconds", type=float, default=4.0)
    p.add_argument("--temp", type=float, default=20.0)
    p.add_argument("--out", default="calib.npz")
    p.add_argument("--slotmap")
    p.add_argument("--port-b-shift", type=int)
    sub.add_parser("verify-selftest", help="run the verification suite on emulated healthy and faulty boards")
    p = sub.add_parser("stimuli", help="write the WAV files to play during the verification")
    p.add_argument("--out", default=".")
    p = sub.add_parser("verify", help="board verification: link, idle, tap, sweep, buzzer, horn")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--port", help="serial port of the board, e.g. COM5 or /dev/ttyACM0")
    g.add_argument("--replay", help="re-analyse a saved session folder")
    g.add_argument("--emulate", action="store_true", help="emulated board (add --fault ... to inject faults)")
    p.add_argument("--fault", action="append", help="emulator only, e.g. port_b_lag=1, inverted=7, leg_open=14, dead=3, "
                   "swap=5,10, stuck_stream=11, drop_every=40, missing_adc=3, table_range_error=0.3")
    p.add_argument("--stages", help="comma list out of link,idle,tap,sweep,buzzer,horn (default: all six) and the optional 'tabletop'")
    p.add_argument("--out", help="session folder (default verify_<date>_<time>)")
    p.add_argument("--temp", type=float, default=20.0, help="air temperature, deg C")
    p.add_argument("--sweep-pose", default="lab_floor_square", choices=list(POSES))
    p.add_argument("--sweep-src", help="x,y,z of the loudspeaker (default: 1 m in front of the board on its axis)")
    p.add_argument("--sweep-runs", type=int, default=2)
    p.add_argument("--buzz", action="append", help="x,y of a buzzer position on the floor square; repeat (default: 5 positions)")
    p.add_argument("--horn-az", help="comma list of loudspeaker azimuths in deg (default 0,90,180,270)")
    p.add_argument("--horn-dist", type=float, default=3.0)
    p.add_argument("--table-az", help="tabletop stage: comma list of buzzer azimuths in deg (default 0,90,180,270)")
    p.add_argument("--table-dist", type=float, default=1.0, help="tabletop stage: approximate buzzer distance (m)")
    p.add_argument("--table-buzzer-height", type=float, default=0.010, help="tabletop stage: buzzer sound hole above the table (m)")
    p.add_argument("--link-seconds", type=float, default=60.0)
    p.add_argument("--slotmap", help="wiring_measured.json from an earlier tap stage")
    p.add_argument("--port-b-shift", type=int)
    p.add_argument("--calib", help="calibration .npz to use in the buzzer / horn stages when the sweep stage is not run")
    a = ap.parse_args()

    if a.cmd == "verify":
        sys.exit(0 if run_verify_cli(a) else 1)
    elif a.cmd == "verify-selftest":
        sys.exit(0 if verify_selftest() else 1)
    elif a.cmd == "stimuli":
        make_stimuli(a.out)
    elif a.cmd == "walkthrough":
        walkthrough()
    elif a.cmd == "selftest":
        sys.exit(0 if selftest() else 1)
    elif a.cmd in ("live", "replay"):
        run_localiser(a)
    elif a.cmd == "record":
        a.record_to = a.out                                          # raw bytes are written by byte_source()
        for _ in audio_blocks(a, a.seconds):
            pass
        print("recorded to", a.out, "| stream stats:", audio_blocks.stats)
    elif a.cmd == "calibrate":
        load_wiring(a.slotmap, a.port_b_shift)
        results = []
        for s in a.src:
            pos = [float(v) for v in s.split(",")]
            if a.port:
                input(f"Place the reference source (same tone as the demo) at {pos} and press Enter...")
            x = np.concatenate([ev[2] for ev in audio_blocks(a, a.seconds) if ev[0] == "block"], axis=1)
            results.append(calibrate(x, POSES[a.pose], src_pos=pos, temp_c=a.temp))
        W, valid = combine_calibrations(results)
        np.savez(a.out, W=W, valid=valid)
        print(f"wrote {a.out}: {int(valid.sum())} calibrated bins; per-mic gain corrections (dB):",
              np.round(20 * np.log10(np.abs(W[:, valid]).mean(1)), 2) if valid.any() else "none")


if __name__ == "__main__":
    main()
