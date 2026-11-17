# Task for Antigravity: create the GitHub repository for the SSL‑16 acoustic camera board (Rev A)

You are creating a well‑documented **private** GitHub repository for a 16‑channel MEMS‑microphone
acoustic camera (sound source localization) PCB designed in KiCad 10. Work carefully: this is a
research hardware project, so every number you write in the docs must come from this instruction
file or from the KiCad files — never invent values. If something is unclear or a file is missing,
leave a clearly marked `TODO:` instead of guessing.

---

## 0. Inputs and settings

| Item | Value |
|---|---|
| Source folder (Windows) | `H:\My Drive\Research_2026\Sound Source Localizaton\Project\System_Dev\ECAD_KiCad` |
| GitHub account | `shakursiam` |
| Repository name | `ssl16-acoustic-camera` |
| Visibility | **private** |
| Default branch | `main` |
| Board revision | **Rev A** (as printed on the silkscreen: "LAB PROTOTYPE · REV A · 2026‑11") |
| Organisation | HIVE (Hydrogen, Intelligent Vehicles & Energy) Research Group, BUET |
| Designers | MD Abdus Shakur Siam, Sadaf Shafin, Ashir Intesher |
| KiCad version | 10.0.x |

Rules:
- **Copy** files into a new working folder (e.g. `C:\Users\<you>\workspace\ssl16-acoustic-camera`). Never move, rename or edit anything inside the Google Drive source folder.
- Do **not** add a LICENSE file (unpublished research). Put a short "All rights reserved – contact the authors" line in the README instead.
- Do not commit personal data, tokens, or files outside the listed folders.

---

## 1. Repository layout to create

```
ssl16-acoustic-camera/
├── README.md
├── .gitignore
├── .gitattributes
├── hardware/
│   ├── kicad/                    ← full KiCad project (copied from ECAD_KiCad)
│   │   ├── Beamfoarming_16x.kicad_pro
│   │   ├── Beamfoarming_16x.kicad_pcb
│   │   ├── Beamfoarming_16x.kicad_sch
│   │   ├── Beamfoarming_16x.kicad_dru
│   │   ├── MCU_sch.kicad_sch, adc_1..adc_4.kicad_sch, tdm.kicad_sch, sdcard.kicad_sch,
│   │   │   MIC_ADC.kicad_sch, MICS_ADC.kicad_sch, Block_diagram.kicad_sch (all *.kicad_sch present)
│   │   ├── fp-lib-table, sym-lib-table (if present)
│   │   └── Library_BeamForming/  ← custom symbols, footprints, 3D models
│   ├── fabrication/
│   │   └── rev_A/
│   │       ├── gerbers/          ← Gerber + drill files exactly as sent to JLCPCB
│   │       ├── assembly/         ← JLC BOM + CPL (xlsx and csv) and the KiCad position file
│   │       └── README.md         ← order settings (section 6 below)
│   └── exports/
│       ├── SSL16_RevA_schematic.pdf
│       ├── SSL16_RevA_pcb_layers.pdf
│       └── renders/              ← 3D renders top/bottom (PNG)
├── docs/
│   ├── architecture.md
│   ├── clocking_and_tdm.md
│   ├── adc_configuration.md
│   ├── microphone_array.md
│   ├── power.md
│   ├── pcb_stackup_and_rules.md
│   ├── esp32_pinout.md
│   ├── bringup_checklist.md
│   ├── known_issues_and_todo.md
│   ├── design_review_log.md
│   └── images/
└── firmware/
    └── README.md                 ← placeholder: "Firmware will be added in a later revision" + firmware notes (section 5.9)
```

If a listed file does not exist in the source folder, skip it and note it in the final report.

---

## 2. .gitignore and .gitattributes

`.gitignore`:
```
# KiCad temporary / backup files
*.lck
~*.lck
*-backups/
*.kicad_prl
fp-info-cache
_autosave-*
*.bak
*-bak
\#auto_saved_files#
# OS / Google Drive junk
desktop.ini
Thumbs.db
.DS_Store
*.tmp
```

`.gitattributes` (use **Git LFS** for large binaries; run `git lfs install` first):
```
*.step  filter=lfs diff=lfs merge=lfs -text
*.stp   filter=lfs diff=lfs merge=lfs -text
*.wrl   filter=lfs diff=lfs merge=lfs -text
*.zip   filter=lfs diff=lfs merge=lfs -text
*.pdf   filter=lfs diff=lfs merge=lfs -text
*.png   filter=lfs diff=lfs merge=lfs -text
*.kicad_pcb text eol=lf
*.kicad_sch text eol=lf
*.kicad_pro text eol=lf
```
If Git LFS is not available, skip `.gitattributes` and make sure no single file is larger than 50 MB.

---

## 3. Generate exports with kicad-cli (if available)

kicad-cli is normally at `C:\Program Files\KiCad\10.0\bin\kicad-cli.exe`. Run from `hardware/kicad/`:

```bash
kicad-cli sch export pdf  -o ../exports/SSL16_RevA_schematic.pdf  Beamfoarming_16x.kicad_sch
kicad-cli pcb export pdf  -o ../exports/SSL16_RevA_pcb_layers.pdf --layers "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Silkscreen,B.Silkscreen,Edge.Cuts" Beamfoarming_16x.kicad_pcb
kicad-cli pcb render -o ../exports/renders/top.png    --side top    Beamfoarming_16x.kicad_pcb
kicad-cli pcb render -o ../exports/renders/bottom.png --side bottom Beamfoarming_16x.kicad_pcb
kicad-cli pcb drc  -o ../exports/drc_report.txt  --schematic-parity Beamfoarming_16x.kicad_pcb
kicad-cli sch erc  -o ../exports/erc_report.txt  Beamfoarming_16x.kicad_sch
```
If an option is not supported by the installed kicad-cli, run `kicad-cli <cmd> --help`, adapt, and report what you changed. Do **not** regenerate the Gerbers — use the exact files that were sent to the fab (ask the user where they are if not inside the source folder; they were exported to `C:\Users\HP\Downloads\gerber_v2\` / `Fabrication_Files.zip`).

Copy into `docs/images/`: `exports/renders/top.png`, `bottom.png` (for the README), plus any screenshots the user provides.

---

## 4. README.md content

Write a clear README with these sections (use the facts in section 5):

1. Title: **SSL‑16 — 16‑Channel Acoustic Sound Source Localization Board (Lab Prototype, Rev A)**
2. One‑paragraph summary: downward‑tilted acoustic camera that localizes sound sources (target application: vehicle‑horn localization in Dhaka traffic). 16 Infineon IM73A135 differential analog MEMS microphones in a sunflower layout inside an R80 aperture, digitized by four TI TLV320ADC5140 4‑channel ADCs on one shared TDM bus into an ESP32‑S3.
3. Renders (top/bottom images).
4. Key specs table (section 5.1).
5. System block diagram as a Mermaid diagram (section 5.2).
6. Repository structure.
7. How to open the project (KiCad 10, library tables use `${KIPRJMOD}`).
8. Fabrication summary + link to `hardware/fabrication/rev_A/README.md`.
9. Documentation index (links to every file in `docs/`).
10. Status: "Rev A ordered from JLCPCB (Oct 2026), bring‑up pending".
11. Authors and affiliation; "All rights reserved – contact the authors for use."

---

## 5. Technical facts to use in docs/ (copy accurately)

### 5.1 Key specifications
| Parameter | Value |
|---|---|
| Microphones | 16 × Infineon IM73A135V01 (analog, differential, bottom port), MK1–MK16 |
| ADCs | 4 × TI TLV320ADC5140 (U1–U4), 4 differential inputs each |
| Sample format | TDM, 16 slots × 16 bit, fs = 48 kHz, BCLK = 12.288 MHz (256 BCLK per frame) |
| Master clock | 24.576 MHz 3.3 V CMOS XO (Abracon ASE‑24.576MHZ‑LC‑T, Y1) → U4 GPIO1 |
| Clock fan‑out | TI LMK1C1104 (U10), 1:4 LVCMOS buffer |
| MCU | ESP32‑S3‑WROOM‑1‑N8R8 (U5), I2S/TDM slave, native USB |
| Storage | microSD (Molex 104031‑0811, J601), 4‑bit SDMMC |
| Power input | 12 V DC barrel jack (J8) or USB‑C (J2) |
| PCB | 4 layers, 230 × 170 mm, 1.6 mm, JLC04161H‑7628 stack‑up, all SMD parts on bottom side |
| Useful beamforming band | ~1.5–6 kHz (no usable beam below 1.5 kHz, no grating lobes up to 6 kHz) |

### 5.2 Architecture (for the Mermaid block diagram and architecture.md)
- Y1 24.576 MHz → R22 33 Ω → **U4 (ADC‑4) GPIO1 = MCLK**.
- **U4 is the TDM controller**: generates BCLK 12.288 MHz and FSYNC 48 kHz.
- U4 BCLK → R27 33 Ω → **U10 LMK1C1104 CLKIN**; U10 Y0/Y1/Y2/Y3 → R13/R14/R15/R16 33 Ω → U1 BCLK / U2 BCLK / U3 BCLK / ESP32 IO6.
- FSYNC: U4 → R28 33 Ω → fly‑by to U3, U2, U1 → ESP32 IO7, end termination R30 51 Ω + C54 100 pF at IO7.
- Data daisy chain: U4 SDOUT → R26 → SD4 → U3 GPIO1 (daisy input); U3 → R25 → SD3 → U2; U2 → R23 → SD2 → U1; U1 SDOUT → R24 → I2S_DIN → ESP32 IO13.
- Control: I2C (SCL IO9, SDA IO8, 2.2 kΩ pull‑ups R17/R18) to all four ADCs, TMP112 (U9, 0x48) and header J4. SHDNZ for all ADCs from IO11 with 100 kΩ pull‑down R31 (ADCs held in shutdown until firmware releases them).

### 5.3 ADC addresses and TDM slot / microphone map
| ADC | I2C addr | ADDR1/ADDR0 | IN1 | IN2 | IN3 | IN4 | TDM slots |
|---|---|---|---|---|---|---|---|
| U1 (ADC‑1) | 0x4C | GND/GND | MK2 | MK7 | MK10 | MK15 | 0–3 |
| U2 (ADC‑2) | 0x4D | GND/3V3 | MK1 | MK4 | MK9 | MK12 | 4–7 |
| U3 (ADC‑3) | 0x4E | 3V3/GND | MK3 | MK6 | MK11 | MK14 | 8–11 |
| U4 (ADC‑4) | 0x4F | 3V3/3V3 | MK5 | MK8 | MK13 | MK16 | 12–15 |

Every ADC is programmed to slots 0–3; the daisy chain shifts them so U1 lands in slots 0–3 and U4 in slots 12–15 (TI app note SBAA383). Mic wiring: OUT+ → 1 µF → INxP, OUT− → 1 µF → INxN; mic VDD = that ADC's MICBIAS with a local 1 µF.

### 5.4 ADC register script (adc_configuration.md) — mark as "to be verified at bring‑up"
- All: SLEEP_CFG 0x02 = 0x81 (wake, internal AREG); ASI_CFG0 0x07 = 0x01 (TDM, 16‑bit); CH_CFG0 = 0x04 (10 kΩ input impedance) for CH1–4; **BIAS_CFG 0x3B = 0x00 → MICBIAS = VREF ≈ 2.75 V. Never set MICBIAS to AVDD (3.3 V): the IM73A135 absolute maximum is 3.0 V.**
- ASI_CFG1 0x08 = 0xA1 for U1, 0x81 for U2–U4.
- Targets U1–U3: ASI_CFG2 0x09 = 0x80 (daisy chain on); GPIO_CFG0 0x21 = 0xB0 (GPIO1 = daisy‑chain input); MST_CFG0 0x13 = 0x00 (target mode); PWR_CFG 0x75 = 0xE0 last.
- Controller U4: GPIO_CFG0 0x21 = 0xA0 (GPIO1 = MCLK input); 0x13 = 0xA0; 0x14 = 0x48; 0x16 = 0xD8; PWR_CFG 0x75 = 0xC0 last.
- Sequence: power up → keep SHDNZ low → raise SHDNZ (IO11) → wait ≥1 ms → configure targets U1–U3 → configure controller U4 last.

### 5.5 Microphone array (microphone_array.md)
Sunflower (Vogel) spiral, 16 mics, radius 80 mm aperture. Coordinates in mm, origin = array centre, +X = 0° direction, view from top face (mics are bottom‑mounted, bottom‑port through 0.8 mm NPTH holes):

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

(Mn = MKn in the schematic.) Port positions in the PCB match these to within 0.01 mm.

### 5.6 Power (power.md)
- 12 V (J8) → XL2596S‑5.0 buck (U7, L2 47 µH, D2 Schottky, C106/C107 470 µF) → **+5V**.
- USB VBUS → Q1 DMP2045U P‑MOSFET (ideal‑diode style, gate on +5V, R5 10 k pull‑down) and +5V → D1 B5818WS → **VSYS** (works from USB, adapter or both).
- VSYS → AP2112K‑3.3 (U8) → **+3V3** (ESP32, ADC IOVDD, LMK, SD, TMP112).
- VSYS → TPS7A2033 (U11) → **3V3A** (ADC AVDD only, low noise).
- MICBIAS per ADC (≈2.75 V) powers its 4 mics.
- WS2812B (D6) runs from +5V → lights only with the 12 V adapter.
- Single ground (GND) everywhere; no split analog ground.

### 5.7 PCB stack‑up and rules (pcb_stackup_and_rules.md)
- JLC04161H‑7628: F.Cu 35 µm / prepreg 0.2104 mm (εr 4.4) / In1 15.2 µm / core 1.065 mm (εr 4.6) / In2 15.2 µm / prepreg 0.2104 mm / B.Cu 35 µm; finished ≈1.6 mm.
- Layer use: L1 F.Cu = signals + GND pour; L2 In1 = GND, with +3V3 / +5V / adapter islands in the power/MCU section; L3 In2 = solid GND reference; L4 B.Cu = all components, mic pairs, most routing + GND pour.
- Net classes: **50_ohm** (BCLK*, FSYNC*, SD2–SD4, *SDOUT*, I2S_DIN, *MCLK*): 0.32 mm / 0.25 mm clearance, coplanar 50 Ω (JLC calculator). **USB_90R**: 0.2703 mm / 0.2032 mm gap, 90 Ω differential. **MIC_DIFF** (*MK*_P/N, *_IN?P/N): 0.2 mm / 0.2 mm, tightly coupled pairs. **MICBIAS**/POWER: 0.25 mm.
- Series 33 Ω source termination on all clock/data lines; no length matching needed (timing margin ≈40 ns, trace skew <1 ns).
- ESP32 antenna keep‑out on all copper layers; 5 mm keep‑out around each mic port on the top side; 9 thermal vias in each ADC exposed pad.
- Custom DRC rules in `Beamfoarming_16x.kicad_dru` relax clearance only for fine‑pitch footprints (U1–U4, U10, J601, J2) and mic port holes.

### 5.8 ESP32‑S3 pin map (esp32_pinout.md) — read pins from the schematic and confirm
IO6 BCLK (BCLK_Y3), IO7 FSYNC, IO13 I2S_DIN, IO8 SDA, IO9 SCL, IO11 SHDNZ, IO19/IO20 USB D−/D+, IO5 SD_CLK, IO4 SD_CMD, IO18 SD_D0, IO16 SD_D1, IO15 SD_D2, IO21 SD_D3, IO14 SD card detect, IO48 WS2812 data, IO0 BOOT (SW4), EN (SW3), RXD0/TXD0 → J3 UART, J6/J7 expansion (IO17, IO35–IO42). Note: on N8R8 (octal PSRAM) modules IO35–IO37 are used by PSRAM and must not be used as GPIO.

### 5.9 Firmware notes (firmware/README.md)
- Flash over native USB (USB‑Serial/JTAG on IO19/IO20); manual download mode: hold BOOT, tap EN, release BOOT. Arduino: enable "USB CDC On Boot", PSRAM = OPI. ESP‑IDF: console = USB Serial/JTAG.
- I2S in TDM **slave** mode, 16 slots × 16 bit, PCM short frame, BCLK inverted may be needed (bclk_inv = true); ESP‑IDF needs bclk_div ≥ 8 (internal MCLK 98.304 MHz from the 160 MHz PLL is marginal → fallback fs = 24 kHz). Mark all as "to verify".
- Run I2C at 100 kHz (or 400 kHz with the 2.2 kΩ pull‑ups); avoid I2C traffic (TMP112 polling) during audio capture.

### 5.10 Bring‑up checklist (bringup_checklist.md)
1. Visual: mic orientation/ports, ADC pin 1, Y1 pin 1, electrolytic polarity, diode/LED polarity.
2. Power (no ESP firmware): measure +5V, VSYS, +3V3, 3V3A at TP 5V1, TP3_3V3, 3V3A1 on 12 V and on USB‑only.
3. MCLK at TP MCLK1 = 24.576 MHz.
4. Flash blink/USB test; I2C scan must find 0x48, 0x4C, 0x4D, 0x4E, 0x4F.
5. Release SHDNZ, load register script; check MICBIAS ≈ 2.75 V on U1–U4_MICBIAS1 test points.
6. Scope BCLK (BCLK_SRC1, BCLK_Y0–Y3) = 12.288 MHz, FSYNC1 = 48 kHz, data on SD4/SD3/SD2/I2S_DIN1.
7. Capture TDM frames, verify 16 channels in the slot order of section 5.3; tap each mic to confirm mapping.
8. Run a known‑source localization test.

### 5.11 Known issues / TODO for Rev B (known_issues_and_todo.md)
- Y1 is a JLC "global sourcing" part; consider an LCSC‑stocked 3225 3.3 V XO for Rev B.
- JLC 3D model of IM73A135 has a different origin/orientation than the KiCad footprint → placements corrected manually in the JLC preview; verify ports over holes.
- WS2812B (D6) only powered from the adapter; 3.3 V data into 5 V LED is marginal.
- AP2112K (SOT‑23‑5) may run hot with heavy Wi‑Fi + SD writes; consider a 3.3 V buck in Rev B.
- I2C bus ≈480 mm long with 6 devices.
- IO35–IO37 unusable on N8R8 module.
- 12 vias of 0.2 mm in the ESP32 footprint pad (needs JLC 0.2 mm via option).
- Silkscreen: keep text out of mic‑port keep‑outs.
- Substitutions in the assembly BOM: D2 SS54FSH → PMEG4050EP; C107 330 µF → 470 µF/35 V (C3350); L2 → CYA1040‑47UH; J8 → DC‑005‑5A‑2.0; SW3/SW4 → PTS526 SP15.

### 5.12 Design review log (design_review_log.md) — summarize these decisions
- v1.0 problem: independent clocks / BCLK–FSYNC mismatch between ADCs → fixed by one TDM controller (U4) + LMK1C1104 BCLK fan‑out + FSYNC fly‑by.
- Single GND (no GNDA split).
- Mic pairs renamed to proper differential pairs (MKn_P/N, Ux_INnP/N).
- SHDNZ: removed pull‑up R19, kept 100 kΩ pull‑down R31.
- U11 (3V3A) input moved from +5V to VSYS so the analog rail works on USB power.
- Antenna keep‑out extended to inner layers.
- Stitching capacitors C97/C98 (+3V3↔GND) where clock lines cross the In1 plane edge.
- I2C pull‑ups changed 4.7 kΩ → 2.2 kΩ.
- Return‑path GND vias added next to clock/data vias.

---

## 6. hardware/fabrication/rev_A/README.md (order settings)
JLCPCB, 4 layers, 1.6 mm, FR‑4, stack‑up **JLC04161H‑7628**, outer copper 1 oz, inner 0.5 oz, impedance control: no requirement (widths already sized for this stack‑up), via covering: plugged, min via hole 0.2 mm, board outline tolerance ±0.2 mm, flying‑probe test, confirm production file: yes, remove mark. Assembly: bottom side only, 193 placements, BOM/CPL in `assembly/`. List the extended / global‑sourcing parts and the order remarks for mic and Y1 alignment.

---

## 7. Git and GitHub steps

```bash
cd <working folder>/ssl16-acoustic-camera
git init -b main
git lfs install            # if available
git add .
git status                 # check: no *.lck, *-backups, desktop.ini, fp-info-cache
git commit -m "Rev A: KiCad project, fabrication outputs and documentation"
gh auth status             # must show account shakursiam
gh repo create shakursiam/ssl16-acoustic-camera --private --source . --remote origin \
   --description "16-channel MEMS acoustic camera (sound source localization) – ESP32-S3 + 4x TLV320ADC5140 TDM – KiCad, Rev A" --push
git tag -a rev-A -m "Rev A – ordered from JLCPCB, Oct 2026"
git push origin rev-A
```
Then set repository topics: `kicad, pcb, esp32-s3, mems-microphone, beamforming, sound-source-localization, acoustic-camera, tdm, tlv320adc5140`.

---

## 8. Final checks and report back
1. Open the cloned repo in KiCad 10: project opens, schematic and PCB load, no missing symbols/footprints (library tables must use `${KIPRJMOD}` paths; fix `fp-lib-table`/`sym-lib-table` entries that point to absolute `H:\` paths and list what you changed).
2. All README/doc links work on GitHub; Mermaid diagram renders.
3. Repo is **private**.
4. Report: repo URL, list of files committed, any skipped/missing files, any kicad-cli commands that failed, and every `TODO:` you left.
