# SSL-16 Rev A Known Issues, Design Observations & Rev B Roadmap

This document catalogues hardware errata, layout nuances, fabrication substitutions, and architectural optimizations identified during the Rev A tape-out for implementation in **Revision B**.

---

## 1. Known Hardware & Component Observations (Rev A)

### 1.1 Y1 Master Crystal Oscillator Sourcing
- **Issue:** The Abracon ASE-24.576MHZ-LC-T (`Y1`) is classified as a **Global Sourcing** component in JLCPCB’s library rather than standard/in-stock basic or extended inventory. This adds pre-order lead time (typically 3–7 business days).
- **Rev B Action:** Select a standard, in-stock LCSC 3225 3.3V CMOS 24.576 MHz crystal oscillator (e.g., from Yangxing Tech or SCTF) to streamline automated assembly.

### 1.2 JLCPCB IM73A135 3D Model Alignment
- **Issue:** The default JLCPCB component database 3D model and rotation origin for the Infineon IM73A135V01XTSA1 (`MK1`–`MK16`) does not match the KiCad footprint origin.
- **Rev A Resolution:** Rotations and coordinate offsets were manually adjusted and locked in the JLCPCB DFM web viewer prior to order sign-off.
- **Rev B Action:** Update KiCad footprint 3D model origin and rotation offset so the exported CPL coordinates natively match JLCPCB automated pick-and-place centroids without manual intervention.

### 1.3 WS2812B Power & Logic Level Margin
- **Issue 1 (Power Rail):** The WS2812B addressable RGB LED (`D6`) is powered directly from the `+5V` buck rail. Consequently, `D6` illuminates **only** when powered via the 12 V DC barrel jack (`J8`) and remains unpowered under USB-only operation.
- **Issue 2 (Logic Levels):** The WS2812B operates at $V_{\text{DD}} = 5.0\,\text{V}$ ($V_{\text{IH(min)}} = 0.7 \times V_{\text{DD}} = 3.5\,\text{V}$). Driving its data pin directly from ESP32 $3.3\,\text{V}$ logic (`GPIO48`) leaves a negative theoretical margin of $0.2\,\text{V}$. While most WS2812B units function at room temperature, it is marginally out of specification.
- **Rev B Action:** Power the status LED from a rail active on both USB and adapter, and add a single-gate 74LVC1T45 or diode-based level translator between `GPIO48` and `DIN`.

### 1.4 AP2112K LDO Thermal Dissipation
- **Issue:** The primary 3.3V digital rail (`+3V3`) is regulated by an AP2112K-3.3 (`U8`) in a SOT-23-5 package ($R_{\theta\text{JA}} \approx 250^\circ\text{C/W}$). Under heavy Wi-Fi transmissions ($I_{\text{peak}} \approx 350\,\text{mA}$) combined with continuous 4-bit SDMMC writes and clock buffering ($I_{\text{total}} \approx 450\,\text{mA}$), package dissipation reaches $P_D \approx (5.0\,\text{V} - 3.3\,\text{V}) \times 0.45\,\text{A} \approx 0.76\,\text{W}$. This will cause thermal throttling or elevated package temperature.
- **Rev B Action:** Replace `U8` with a compact synchronous step-down buck converter (e.g., TI TPS62088 or MPS MP2143 in QFN/SOT-563) to achieve $>90\%$ conversion efficiency and zero thermal buildup.

### 1.5 I2C Bus Length & Routing
- **Issue:** The shared I2C bus routes sequentially across all four ADCs spread across the $230 \times 170\,\text{mm}$ PCB, resulting in an aggregate trace length of approximately **480 mm**.
- **Mitigation in Rev A:** Pull-up resistors $R_{17}$ and $R_{18}$ were stiffened from $4.7\,\text{k}\Omega$ to **$2.2\,\text{k}\Omega$**, ensuring sharp rise times across the bus capacitance ($C_{\text{bus}} \approx 50\,\text{pF}$).
- **Rev B Recommendation:** Keep I2C bus speed at 100 kHz standard mode during bring-up.

### 1.6 Unusable GPIOs on N8R8 Module (IO35–IO37)
- **Issue:** ESP32-S3 `IO35`, `IO36`, and `IO37` are routed to expansion headers `J6` and `J7`. However, on modules with Octal PSRAM (N8R8), these three pins are internally committed to the OPI PSRAM die.
- **Rev B Action:** Remove `IO35`–`IO37` from the external expansion headers to prevent inadvertent shorting or firmware misconfiguration.

### 1.7 ESP32 Exposed Thermal Pad Vias (0.2 mm)
- **Issue:** The ground thermal pad of `U5` incorporates 12 vias of diameter $0.2\,\text{mm}$.
- **Rev A Fabrication Impact:** Requires JLCPCB’s $\le 0.2\,\text{mm}$ minimum via drill option with plugged vias.
- **Rev B Action:** Increase via diameter to $0.3\,\text{mm}$ with $0.6\,\text{mm}$ annular ring to allow standard low-cost PCB capability tiers.

### 1.8 Top Silkscreen Mic Keep-Out Integrity
- **Issue:** In prototype silkscreen iterations, decorative silkscreen borders or text approached within $1\,\text{mm}$ of the acoustic entry ports.
- **Rev A Resolution:** A strict 5 mm diameter keep-out rule was applied to ensure clean, flat acoustic surfaces.

---

## 2. Assembly BOM Substitutions Log

During the JLCPCB SMT order setup for Rev A, the following component substitutions were validated and applied to match real-time SMT feeder availability:

| RefDes | Original KiCad Part | Final Assembled Part | JLCPCB Part # | Rationale / Verification |
|---|---|---|---|---|
| **D2** | SS54FSH (SOD-123FL) | **PMEG4050EP,115** (SOD-128) | `C96235` | 40V, 5A Schottky diode with lower forward voltage drop ($V_F \approx 0.42\,\text{V}$) for improved buck converter efficiency. |
| **C107** | 330 µF / 35V Polymer | **470 µF / 35V Polymer (RVT1V471M1010)** | `C3350` | SMT stock optimization; unified with C106 ($470\,\mu\text{F}$), lowering bill-of-materials line count and increasing ripple capacity. |
| **L2** | Generic 47 µH Inductor | **CYA1040-47UH** | `C6364681` | Shielded high-current SMD power inductor ($I_{\text{sat}} \ge 3.5\,\text{A}$) with minimal magnetic fringing. |
| **J8** | Generic Barrel Jack | **DC-005-5A-2.0** | `C381116` | Standard 2.0 mm center-pin THT barrel jack rated for 5A. |
| **SW3, SW4** | PTS526 SM15 | **PTS526SP15SMTR2 LFS** | `C2991193` | High-cycle tactile switch with exact pad and actuator profile match. |
