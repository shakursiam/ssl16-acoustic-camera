# AGENTS.md — SSL-16 Sound Source Localization: project brief for the coding agent (Antigravity)

Read this whole file before doing anything in this repository. It is the single source of truth for the
hardware, firmware, software, test campaign and paper plan of the SSL-16 project. When this file and your
own assumptions disagree, this file wins. When this file and a measurement on the real board disagree, the
measurement wins: update this file in the same commit and say so in the commit message.

Last updated: 2026-11-13 (handoff from the design / bring-up phase to the test-and-publish phase).

---

## 0. Who, what, where

| Item | Value |
|---|---|
| Project | SSL-16: 16-channel MEMS-microphone array for acoustic sound source localization (target application: vehicle-horn localization in Dhaka traffic) |
| Owner / main contact | MD Abdus Shakur Siam (Siam), Research Assistant, HIVE (Hydrogen, Intelligent Vehicles & Energy) Research Group, BUET |
| Designers / co-authors | MD Abdus Shakur Siam, Sadaf Shafin, Ashir Intesher (supervisor and final author list: ask Siam before writing any author block) |
| GitHub repository | `https://github.com/shakursiam/ssl16-acoustic-camera` (private, branch `main`). If it does not exist yet, create it first by following `docs/repo_setup_instructions.md`, then add the contents of this handoff package. |
| Board | Rev A lab prototype (silkscreen: "LAB PROTOTYPE · REV A · 2026-11"). Some fab and firmware files say "Rev D": that is the same board. Use **Rev A** in all new docs and the paper; treat "Rev D" as an alias. |
| Boards on hand | 2 assembled by JLCPCB ("board1", "board2"). Board 1 is brought up; board 2 not yet tested. |
| User's PC | Windows, VS Code, Arduino IDE 2 with ESP32 core 3.x, Python 3.13 at `C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe`, board on `COM19` |
| Original design files | Google Drive `H:\My Drive\Research_2026\Sound Source Localizaton\Project\System_Dev\ECAD_KiCad` (KiCad 10 project `Beamfoarming_16x`). Never edit files there; copy into the repo. |

### 0.1 Your mission, in order of priority
1. **Keep the repo the complete, reproducible record** of hardware, firmware, software, data and results.
2. **Support the lab test campaign** (15–21 Nov 2026): daily data checks, bug fixes, quick analysis.
3. **Produce the journal paper's results**: analysis, figures, tables, and LaTeX text that is traceable to data.
4. **Engineering roadmap** after the paper data exists: on-device localization, horn detection, Rev B hardware.

### 0.2 Ground rules (non-negotiable)
- **Never invent numbers.** Every number in docs, code comments or the paper comes from this file, the design files, a datasheet you cite, or a measurement file in the repo. Unknown → write `TODO:` and ask Siam.
- **Hardware safety:** never write ADC register BIAS_CFG (0x3B) to anything that makes MICBIAS = AVDD. The IM73A135 absolute maximum supply is 3.0 V; MICBIAS must stay at VREF ≈ 2.75 V (`0x3B = 0x00`). Any firmware change touching ADC registers needs a datasheet page reference in the commit message.
- **Raw data is read-only.** Never modify, re-encode, rename or delete recorded WAV/JSON files or `runs.csv` rows. Bad runs are flagged (`flag=bad`, `flag_reason`), never removed.
- **Results are reported honestly**, including bad ones. Do not tune algorithm parameters on the test set and then report that test set as an independent result; if you tune, say so and hold out data.
- **Ask before** anything that is public or hard to undo: making the repo public, pushing to `main` without review, deleting branches, changing the author list, submitting anything, emailing anyone.
- **Small, reviewable changes:** one topic per branch (`feat/...`, `fix/...`, `data/...`, `paper/...`), clear commit messages, PR description lists what was tested and how.
- **Keep packet formats backward compatible** (Section 4.2). If a format must change, bump a version field and keep the old parser.
- **Literature:** cite only papers you have actually opened; give DOI or URL; no fabricated references.

---

## 1. Hardware summary (Rev A)

### 1.1 Key specifications
| Parameter | Value |
|---|---|
| Microphones | 16 × Infineon IM73A135V01 (analog, differential, bottom port), MK1–MK16, bottom side, ports through 0.8 mm NPTH holes |
| Array | Sunflower (Vogel) spiral, R80 aperture (max radius 78.5 mm, aperture ≈157 mm); coordinates in Section 1.4 |
| ADCs | 4 × TI TLV320ADC5140 (U1–U4), 4 differential inputs each |
| Audio format | TDM, 16 slots × 16 bit, fs = 48 kHz, BCLK = 12.288 MHz (256 BCLK per frame) |
| Master clock | 24.576 MHz 3.3 V CMOS XO (Abracon ASE-24.576MHZ-LC-T, Y1) → U4 GPIO1 |
| Clock fan-out | TI LMK1C1104 (U10), 1:4 LVCMOS buffer |
| MCU | ESP32-S3-WROOM-1-N8R8 (U5): 8 MB flash, 8 MB octal PSRAM, native USB; I2S/TDM **target (slave)** |
| Storage | microSD (Molex 104031-0811, J601), 4-bit SDMMC |
| Power input | 12 V DC jack (J8) or USB-C (J2), either or both |
| Temperature sensor | TMP112 (U9), I2C 0x48 |
| PCB | 4 layers, 230 × 170 mm, 1.6 mm, JLC04161H-7628 stack-up, all parts on the bottom side |
| Useful beamforming band | about 1.5–6 kHz (wide main lobe below 1.5 kHz; no grating lobes up to 6 kHz) |

### 1.2 Clock and data architecture
- Y1 24.576 MHz → R22 33 Ω → **U4 GPIO1 = MCLK**. **U4 is the TDM controller**: it generates BCLK 12.288 MHz and FSYNC 48 kHz.
- U4 BCLK → R27 → U10 CLKIN; U10 Y0/Y1/Y2/Y3 → R13/R14/R15/R16 (33 Ω) → U1 BCLK / U2 BCLK / U3 BCLK / ESP32 IO6.
- FSYNC: U4 → R28 → fly-by U3, U2, U1 → ESP32 IO7, end termination R30 51 Ω + C54 100 pF at IO7 (trace ≈ 375 mm).
- Data daisy chain: U4 SDOUT → R26 → SD4 → U3 GPIO1; U3 → R25 → SD3 → U2; U2 → R23 → SD2 → U1; U1 SDOUT → R24 → I2S_DIN → ESP32 IO13. All 16 channels arrive on **one** data line.
- Control: I2C SDA IO8 / SCL IO9, 2.2 kΩ pull-ups (R17/R18), bus ≈ 480 mm long → use 100 kHz. SHDNZ for all ADCs from IO11 with 100 kΩ pull-down (R31): ADCs stay in shutdown, and do not answer I2C, until firmware drives IO11 high.

### 1.3 ADC addresses and TDM slot / microphone map (confirmed on board 1 by data, see 1.6)
| ADC | I2C | IN1 | IN2 | IN3 | IN4 | TDM slots |
|---|---|---|---|---|---|---|
| U1 | 0x4C | MK2 | MK7 | MK10 | MK15 | 0–3 |
| U2 | 0x4D | MK1 | MK4 | MK9 | MK12 | 4–7 |
| U3 | 0x4E | MK3 | MK6 | MK11 | MK14 | 8–11 |
| U4 | 0x4F | MK5 | MK8 | MK13 | MK16 | 12–15 |

Each ADC is programmed to slots 0–3; the daisy chain shifts them so U1 lands in 0–3 and U4 in 12–15. Wiring: mic OUT+ → 1 µF → INxP, OUT− → INxN; mic VDD = that ADC's MICBIAS.

### 1.4 Microphone coordinates (revC1 table, mm, origin = array centre, viewed from the sound-hole face)
Machine-readable copy with slot order: `data/mic_positions_revC1.csv`. Same values are hard-coded in `software/python/ssl16_core.py` (`MICS`, in TDM slot order).

| Mic | x | y | Mic | x | y |
|---|---|---|---|---|---|
| M1 | 9.877 | 1.564 | M9 | 47.843 | 26.590 |
| M2 | −16.122 | 10.668 | M10 | −56.913 | 13.588 |
| M3 | 6.361 | −25.483 | M11 | 34.817 | −51.463 |
| M4 | 15.325 | 28.252 | M12 | 9.600 | 64.914 |
| M5 | −35.329 | −12.187 | M13 | −53.540 | −43.504 |
| M6 | 38.669 | −16.782 | M14 | 72.120 | −4.280 |
| M7 | −18.989 | 42.553 | M15 | −52.491 | 54.144 |
| M8 | −16.064 | −48.167 | M16 | 2.219 | −78.459 |

Mn = MKn in the schematic. PCB port positions match this table within 0.01 mm.
**Open item:** which physical direction on the board is +x / +y, and whether the table is mirrored as seen from the sound side, has **not** yet been verified acoustically. Test E0.5 settles it (flip x / flip y / rotate settings). Until then, treat any left/right result with suspicion.

### 1.5 Power
- 12 V (J8) → XL2596S-5.0 buck (U7) → **+5V**. USB VBUS → Q1 DMP2045U (ideal-diode style, gate on +5V, R5 10 k) and +5V → D1 → **VSYS**.
- VSYS → AP2112K-3.3 (U8) → **+3V3** (ESP32, ADC IOVDD, LMK, SD, TMP112). VSYS → TPS7A2033 (U11) → **3V3A** (ADC AVDD only).
- MICBIAS per ADC (≈ 2.75 V) feeds its 4 mics. WS2812B (D6) is on +5V → only lit with the 12 V adapter.
- Single ground, no analog/digital split.

### 1.6 ESP32-S3 pins
IO6 BCLK (BCLK_Y3), IO7 FSYNC, IO13 I2S_DIN, IO8 SDA, IO9 SCL, IO11 SHDNZ, IO19/IO20 USB D−/D+, SD: CLK IO5, CMD IO4, D0 IO18, D1 IO16, D2 IO15, D3 IO21, card detect IO14; IO48 status LED; IO0 BOOT (SW4); EN (SW3); UART0 → J3. IO35–IO37 are used by the octal PSRAM and must not be used. `TODO:` confirm the WS2812 data GPIO and the J3 / J6 / J7 header pins from the schematic before writing code for them.

### 1.7 ADC register script (verified working on board 1, 2026-11-11)
Order: IO11 (SHDNZ) high → wait 10 ms → on all four: 0x00 = 0x00 (page 0), 0x02 = 0x81 (wake) → wait 2 ms → registers below → power-up U4 first, then U1–U3.

| Reg | Name | U1 (0x4C) | U2 (0x4D) | U3 (0x4E) | U4 (0x4F) |
|---|---|---|---|---|---|
| 0x07 | ASI_CFG0 (TDM, 16-bit) | 0x01 | 0x01 | 0x01 | 0x01 |
| 0x08 | ASI_CFG1 | 0xA1 | 0x81 | 0x81 | 0x81 |
| 0x09 | ASI_CFG2 (daisy) | 0x80 | 0x80 | 0x80 | — |
| 0x13 | MST_CFG0 | 0x00 | 0x00 | 0x00 | 0xA0 (controller) |
| 0x14 | MST_CFG1 | — | — | — | 0x48 (48 kHz, BCLK = 256 fs); 0x28 for 24 kHz |
| 0x16 | CLK_SRC | — | — | — | 0xD8 |
| 0x21 | GPIO1 | 0xB0 (daisy in) | 0xB0 | 0xB0 | 0xA0 (MCLK in) |
| 0x3B | BIAS_CFG | **0x00** | **0x00** | **0x00** | **0x00** |
| 0x3C/0x41/0x46/0x4B | CH1–4 CH_CFG0 | 0x04 | 0x04 | 0x04 | 0x04 |
| 0x74 | IN_CH_EN | 0xF0 | 0xF0 | 0xF0 | 0xF0 |
| 0x75 | PWR_CFG (write last) | 0xE0 | 0xE0 | 0xE0 | 0xC0 (first) |

Health check after power-up: 0x15 ASI_STS = 0x48 on U1–U3 (target sees 48 kHz / 256), 0x76 DEV_STS0 = 0xF0, 0x77 DEV_STS1 = 0xE0.

### 1.8 ESP32 I2S settings (verified on board 1)
TDM **target**, 16 slots × 16 bit, `slot_mask = 0xFFFF`, `ws_width = 1`, `ws_pol = true`, **`bit_shift = true`, `bclk_inv = 1`**, `bclk_div = 8`, sample rate 48 kHz. The other three bit_shift / bclk_inv combinations give garbage (≈ −3 to −10 dBFS with clipping). 48 kHz works; the 24 kHz fallback is not needed.

---

## 2. Bring-up status (board 1)

Measured 2026-11-11 with `firmware/arduino/SSL16_SelfTest`:

| Check | Result |
|---|---|
| PSRAM | 8,388,608 bytes (needs Arduino *PSRAM = OPI PSRAM*) |
| I2C scan | 0x48, 0x4C, 0x4D, 0x4E, 0x4F all present |
| TMP112 | 26.0–26.25 °C (room temperature) |
| ADC register write / readback | PASS |
| U1–U4 status | ASI_STS 0x48, DEV_STS0 0xF0, DEV_STS1 0xE0 on all four |
| TDM alignment | bit_shift = 1, bclk_inv = 1 (median −71.9 / −77.7 dBFS in two runs, no clipping) |
| Quiet-room noise floor | all 16 slots −72 to −78 dBFS, DC ≈ 1–4 LSB, peaks 13–19 LSB |

Artifact to ignore: the first live table right after the alignment search shows peaks of exactly 8191 / 16384 / 24574 (stale misaligned buffers); the next table is clean.

**Not yet measured or not yet reported** (do not claim these as done): rail voltages and currents, MICBIAS on the four test points, scope checks of MCLK/BCLK/FSYNC, tap test of the slot map (slot order is assumed from the design and the data look consistent), SD card test, the USB throughput of `SSL16_HDOA` at 24 kHz, any localization on real hardware (clap, buzzer), board 2. Full procedures: `docs/bringup_test_plan.md`.

Known practical issue: uploading a new sketch while a streaming sketch is running fails with *"A fatal error occurred: No serial data received"*. Fix: hold BOOT, tap EN, release BOOT (download mode), upload, then press EN.

---

## 3. Firmware (`firmware/arduino/`)

Arduino IDE settings for every sketch: board *ESP32S3 Dev Module*, core 3.x (ESP-IDF 5.x), *USB CDC On Boot = Enabled*, *USB Mode = Hardware CDC and JTAG*, *PSRAM = OPI PSRAM*, *Flash = 8 MB*. The ESP32 must be in download mode to upload when a streaming sketch runs (Section 2).

| Sketch | Purpose | Output | Status |
|---|---|---|---|
| `SSL16_SelfTest` | Stage-by-stage self-test: PSRAM, I2C, TMP112, ADC config + readback + status, TDM alignment search (bit_shift × bclk_inv), live per-slot RMS / DC / peak | Text on Serial | Run on board 1, all PASS |
| `SSL16_SDTest` | microSD: mount 4-bit (fallbacks 10 MHz / 1-bit), card info, 4 MB write/verify, speeds, card detect | Text | Written, API checked, **not yet run** |
| `SSL16_Stream` | 16 ch @ 48 kHz → 96-tap FIR → decimate ×4 → **12 kHz**, streams `SSL6` packets | Binary | Written, filter verified in simulation, **not yet run on board** |
| `SSL16_HDOA` | Same capture, 58-tap FIR → **24 kHz** (or 12 kHz via `FS_OUT`), `HDOA` packets + `HDST` JSON status, commands START / STOP / STATUS / REGDUMP n | Binary | Compiles (334,805 B), upload blocked once by the issue in Section 2; **not yet verified streaming** |

Decimation filters (designed with scipy, Kaiser): 12 kHz path flat to 4.5 kHz, −50 dB from 6 kHz; 24 kHz path flat to 9 kHz, −53 dB from 12 kHz.

### 3.1 Packet formats (little endian) — keep compatible
- `SSL6`: `'S''S''L''6' | u32 seq | u16 nsamp | u16 nch(16) | i16 data[nsamp][16]` — 120 samples per packet at 12 kHz (≈ 385 KB/s).
- `HDOA`: `'H''D''O''A' | u32 seq | u64 first_frame | u16 n_frames | u16 n_ch | u16 flags | u16 0 | i16 data[n_frames][16]` — header 24 bytes; flags bit0 = I2S DMA overflow, bit1 = packets dropped because USB was too slow.
- `HDST`: `'H''D''S''T' | u16 len | JSON` (keys include `fs`, `adc_present`, `asi_sts`, `pool_drops`, `i2s_ovf`, `seq`, `frame`, `bit_shift`, `bclk_inv`); REGDUMP replies `{"regdump":{"addr":..,"regs":[128 values]}}`.
- Channel order in every packet = TDM slot order = `M2 M7 M10 M15 M1 M4 M9 M12 M3 M6 M11 M14 M5 M8 M13 M16`.

USB bandwidth note: the HW CDC link carries 12 kHz × 16 ch comfortably; 24 kHz (≈ 770 KB/s) is unproven. If the GUI's gap counter rises, switch `FS_OUT` to 12000.

---

## 4. PC software (`software/python/`)

Install: `pip install -r software/python/requirements.txt` (numpy, pyserial, matplotlib; scipy optional). Keep the three main files in one folder.

| File | Role | Status |
|---|---|---|
| `ssl16_core.py` | Geometry (`MICS`, frames, conversions), `Locator` with `method = srp | das | music`, per-channel `estimate_calibration`, WAV I/O | Unit-tested on synthetic data (`tests/test_core.py`, 7 tests pass) |
| `ssl16_buzzer_gui.py` (v2.0) | Tkinter GUI: connect (or Demo), session dialog, source position entry for Setup A / B / xyz, run labels, live heat-map + top-view dial + 16 level bars, **Measure** (saves 16-ch WAV + JSON + runs.csv + blocks.csv), Flag last bad, Shuffle order | Tested end-to-end in Demo mode on a virtual display; **not yet run with the board** |
| `ssl16_analyze.py` | Offline re-processing of saved sessions: points.csv, summary.csv (bias, MAE with bootstrap CI, RMSE, P95, detection), per-experiment error plots, error CDFs, method/calibration comparison, Wilcoxon test | Tested on a synthetic campaign (calibration reduced MAE 3.9° → 0.2–0.4°) |
| `legacy/ssl16_locate.py` | Earlier command-line locator, has a clap/snap mode (onset detector + broadband SRP-PHAT on the first 21 ms) | Simulation-tested; superseded by the GUI for tones |
| `../../tools/hdoa_pcb_verify_revD.py` | Siam's earlier verification pipeline (written for the two-port Rev C1 design), slot map patched for this board | Its own selftests pass; optional |

### 4.1 Algorithm (what the code does)
- Window 170 ms (2048 samples at 12 kHz / 4096 at 24 kHz), Hann, 50% overlap → one estimate every ≈ 85 ms.
- Band 1.5–5 kHz by default. Pick the 24 strongest bins, then keep only bins within 20 dB of the strongest (`dyn_db`); this matters for PHAT on tonal sources.
- Detection: SNR = mean power of the kept bins ÷ median band power; default threshold 12 dB.
- SRP-PHAT (or DAS / MUSIC) over a far-field grid: azimuth 2° steps, elevation 0–90° in 3° steps, then a 0.5° refinement around the peak. Speed of sound c = 331.3 + 0.606·T.
- Front/back ambiguity: a planar array cannot tell the two sides apart; elevation is folded to ≥ 0.
- Known physics limit (simulation): azimuth stays within about 1°, but elevation is weak when the source is near the board plane (errors up to 10–12° at 10° elevation). Report it as a limitation, do not "fix" it with tuning.

### 4.2 Coordinate frames
- **Array frame:** origin = spiral centre; x, y in the board plane per the mic table; z out of the sound-hole face. GUI azimuth = atan2(y, x); elevation measured up from the board plane.
- **Setup A (camera mode, board vertical):** seen from the sound side, +x right, +y up, z forward. Bearing θ = atan2(x, z) (positive towards +x), vertical φ = asin(y/d). Entered as range r (horizontal), θ, h_src, h_board → x = r sin θ, y = h_src − h_board, z = r cos θ.
- **Setup B (table mode, board face up):** x = r cos α, y = r sin α, z = h_src − h_board.

---

## 5. Test campaign (lab week 15–21 Nov 2026)

Full plan: `docs/test_campaign_plan.md` (also a Claude Doc Siam can share). Summary:

| ID | Setup | Varies | Main output |
|---|---|---|---|
| E0 | A | Daily calibration / characterization: environment + RT60 recording, noise floor, broadside tone calibration (E0.3), source spectra, orientation check (E0.5), boresight offset, real-time figures | Calibration file, system table |
| E1 | A | Bearing −90…+90° (10°), r = 2 m | Main result: error vs bearing |
| E2 | A | Vertical φ −30…+40° | Vertical-angle error |
| E3 | B | Azimuth 0–345° (15°) at elevation 15° and 40° | 360° polar plot, mirror check |
| E4 | A | Range 0.5–4 (5) m at constant SPL | Near-field limit |
| E5 | A | Source: tones 1–5 kHz, 3 buzzers, horn recording, noise | Error vs frequency |
| E6 | A | SNR +30…−5 dB with a pink-noise interferer | Detection rate, false alarms |
| E7 | A | Room: lab, corridor, outdoor | Error CDF vs RT60 |
| E8 | A | Next-day re-mount; board 2 | Repeatability, board-to-board |

Every point: 3 repetitions × 5 s, raw audio saved. Ground-truth bearing uncertainty ≈ ±0.6° (1σ) at 2 m, ±1.5° at 0.5 m. Priority if time is short: E0, E1, E6, E3, E4, E2, E5, E8, E7.

### 5.1 Data layout and policy
```
ssl16_campaign/<YYYY-MM-DD_HHMM>_<room>_<board>/
    session.json  runs.csv  blocks.csv  order_<exp>.txt  photos/
    E1/E1_P07_r1_142233.wav (+ .json)  ...
```
- Raw campaign data (≈ 1–2 GB) lives on Siam's Google Drive and a second backup, **not in git**. Add `ssl16_campaign/` to `.gitignore`. Commit only small derived files (`analysis/<date>/summary.csv`, figures) and a `data/README.md` describing where the raw data is and its checksums.
- For publication, plan a Zenodo (or GitHub release) dataset with a DOI; ask Siam before uploading anything.

### 5.2 What you do each evening of the test week
1. Run `python software/python/ssl16_analyze.py "<session folder>" --out analysis/<date>` (add `--calib <E0 broadside WAV>` once E0.3 exists).
2. Check: detection rates, gaps (USB drops), flagged runs, the control-point drift, obvious mirror errors (sign of θ), outliers.
3. Write `analysis/<date>/daily_report.md`: what was measured, problems found, points to redo tomorrow. Keep it short and factual.
4. Commit derived files only.

---

## 6. Research and paper plan

### 6.1 Research questions
RQ1 bearing accuracy across the field of view · RQ2 vertical accuracy and its limit · RQ3 full 360° operation · RQ4 far-field distance limit · RQ5 effect of frequency / source type (incl. horn) · RQ6 robustness vs SNR · RQ7 effect of room reverberation · RQ8 benefit of per-channel calibration · RQ9 repeatability and board-to-board variation · RQ10 real-time capability.

### 6.2 Figures and tables to produce (scripts in `analysis/` or `paper/figures/`, all generated from data)
Figures: F1 system photo + block diagram; F2 mic layout + simulated beam pattern at 2.8 kHz; F3 bench geometry (Setups A, B); F4 bearing error vs bearing (main result); F5 vertical error vs φ; F6 360° polar plot; F7 error vs range with r_ff = 2D²/λ; F8 error vs frequency with beamwidth ≈ λ/D; F9 detection rate and error vs SNR; F10 error CDF per room with RT60; F11 example SRP maps.
Tables: T1 system spec + real-time figures; T2 test conditions; T3 accuracy summary per experiment; T4 calibration and algorithm comparison (SRP-PHAT / DAS / MUSIC on the same recordings); T5 repeatability / board-to-board; T6 comparison with published low-cost arrays (literature, verified sources only).

### 6.3 Paper workflow
- LaTeX in `paper/` (start from IEEEtran unless Siam names another journal). Structure: Introduction → System design → Localization method → Experimental setup → Results → Discussion (limits: elevation near the board plane, low-frequency horn fundamentals, reverberation) → Conclusion.
- **Traceability:** generate `paper/generated/numbers.tex` (LaTeX macros such as `\EoneMAE`) and table `.tex` files directly from `summary.csv`; never type a result number by hand.
- Figures: vector PDF, consistent style, axis labels with units, colour-blind-safe palette.
- Candidate venues to discuss with Siam (check scope and fees first, do not decide alone): IEEE Sensors Journal, IEEE Sensors Letters, Applied Acoustics, MDPI Sensors, JASA Express Letters.
- Missing pieces to implement for the paper: RT60 from the E0.1 balloon/clap recording (Schroeder backward integration), in-band SNR for E6 from source-only and noise-only recordings, the F2 beam-pattern simulation, publication-style plotting.

---

## 7. Roadmap and first tasks for you

### Phase 1 — repository integration (do now)
1. Make sure the repo exists (Section 0). Add this handoff package at the repo root: `AGENTS.md`, `firmware/`, `software/`, `tools/`, `tests/`, `data/`, `docs/`.
2. Add `.gitignore` entries: `ssl16_campaign/`, `analysis/**/points.csv` (large), `__pycache__/`, `*.pyc`, `.venv/`, Arduino `build/`.
3. Update `README.md`: project status (Section 2), quick start (flash `SSL16_HDOA` or `SSL16_Stream`, run the GUI), links to `docs/`.
4. Run `python -m pytest tests -q` (must pass) and `python -m py_compile` on all Python files. Report results.
5. Open a PR "Integrate test-campaign software and docs"; ask Siam to review.

### Phase 2 — test-week support (15–21 Nov)
Daily analysis and reports (Section 5.2); fix bugs found in the lab quickly and minimally; keep a `CHANGELOG.md`. If a firmware change is needed during the week, version it (`fw_version` in STATUS / packet comments) and record which runs used which version.

### Phase 3 — analysis for the paper (after the week)
Final run over all sessions with `--methods srp,das,music --calib <E0.3 WAV>`; implement the missing pieces in 6.3; generate all figures and tables; write `analysis/final/README.md` with exact commands so anyone can regenerate them.

### Phase 4 — paper drafting
Draft sections from the data and this file; leave `TODO:` where Siam must decide or supply text (motivation statistics about Dhaka traffic noise, related work choices, author list, funding acknowledgement).

### Phase 5 — engineering (after the paper data exists)
- On-device localization on the ESP32-S3 (esp-dsp FFT, SRP-PHAT on a coarse grid, results over USB/Wi-Fi/SD).
- SD-card recording firmware (16 ch WAV) for field tests without a laptop.
- Horn detection (classifier on the beamformed or single-channel signal) before localization.
- Rev B hardware list (Section 8).

---

## 8. Known issues and Rev B candidates
- Y1 is a JLC "global sourcing" part; consider an LCSC-stocked 3.3 V XO.
- JLC 3D model of the IM73A135 differs from the KiCad footprint origin/orientation (placements were corrected manually).
- WS2812B only works with the 12 V adapter; 3.3 V data into a 5 V LED is marginal.
- AP2112K may run hot with Wi-Fi + SD writes; consider a 3.3 V buck.
- I2C bus ≈ 480 mm with 6 devices; keep 100 kHz.
- IO35–IO37 unusable (octal PSRAM).
- Flashing while streaming needs manual download mode (Section 2); a firmware "STOP + reboot to bootloader" command would help.
- Mic-array frame vs board orientation still to be verified (Section 1.4).

---

## 9. How to work with Siam
- He runs everything on Windows; give PowerShell commands with the full Python path when needed, and close the Arduino Serial Monitor before Python opens COM19.
- Report results as: what you did, what you checked, what is still unverified. Do not report something as tested on hardware unless a measurement or log from the board shows it.
- When something needs a decision (paper venue, author list, a hardware change, making anything public), present the options with their trade-offs and wait for his answer.

## 10. File index of this package
```
AGENTS.md                                   this brief
docs/bringup_test_plan.md                   board bring-up phases 0–8, troubleshooting, results log
docs/test_campaign_plan.md                  lab test campaign E0–E9, protocol, schedule, analysis, uncertainty
docs/images/bench_geometry.png              Setup A / B geometry drawing
docs/repo_setup_instructions.md             earlier instructions for creating the repo (hardware facts, KiCad exports)
data/mic_positions_revC1.csv                slot → mic → ADC input → x, y (mm)
firmware/arduino/SSL16_SelfTest/            self-test sketch (verified on board 1)
firmware/arduino/SSL16_SDTest/              SD card test
firmware/arduino/SSL16_Stream/              12 kHz 'SSL6' streamer
firmware/arduino/SSL16_HDOA/                24/12 kHz 'HDOA' streamer with commands
software/python/ssl16_core.py               shared core (geometry, beamformers, calibration, WAV)
software/python/ssl16_buzzer_gui.py         live GUI + campaign logger (v2.0)
software/python/ssl16_analyze.py            offline analysis, figures, statistics
software/python/legacy/ssl16_locate.py      earlier CLI locator with clap mode
software/python/requirements.txt
tools/hdoa_pcb_verify_revD.py               earlier verification pipeline, slot map patched for this board
tests/test_core.py                          baseline unit tests (pytest)
```
