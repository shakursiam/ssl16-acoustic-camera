# SSL-16 PCB Stack-Up, Net Classes & Design Rules

## 1. PCB Stack-Up Specification (JLC04161H-7628)

The board is manufactured on the standard JLCPCB **JLC04161H-7628** 4-layer controlled impedance stack-up with a finished nominal thickness of **1.6 mm**:

| Layer Index | Layer Name | Copper Thickness | Dielectric Thickness | Material / Description | Dielectric Constant ($\varepsilon_r$) |
|---|---|---|---|---|---|
| — | **Top Silkscreen** | — | — | White Silkscreen | — |
| — | **Top Solder Mask**| — | $0.020\,\text{mm}$ | Green / Matte Black Mask | $\approx 3.8$ |
| **L1** | **F.Cu (Top)** | $0.035\,\text{mm}$ (1 oz) | — | Signal routing + GND copper flood | — |
| — | *Dielectric 1–2* | — | $0.2104\,\text{mm}$ | 7628 Prepreg (1 sheet) | $4.40$ |
| **L2** | **In1.Cu (Inner 1)**| $0.0152\,\text{mm}$ (0.5 oz) | — | Ground plane + Power copper islands (+3V3, +5V, +12V) | — |
| — | *Core 2–3* | — | $1.0650\,\text{mm}$ | FR-4 Core | $4.60$ |
| **L3** | **In2.Cu (Inner 2)**| $0.0152\,\text{mm}$ (0.5 oz) | — | **Solid unbroken Ground reference plane** | — |
| — | *Dielectric 3–4* | — | $0.2104\,\text{mm}$ | 7628 Prepreg (1 sheet) | $4.40$ |
| **L4** | **B.Cu (Bottom)** | $0.035\,\text{mm}$ (1 oz) | — | **All SMD components**, differential mic routing, GND flood | — |
| — | **Bottom Mask** | — | $0.020\,\text{mm}$ | Green / Matte Black Mask | $\approx 3.8$ |
| — | **Bottom Silk** | — | — | White Silkscreen | — |
| **Total** | | **$0.100\,\text{mm}$** | **$1.526\,\text{mm}$** | **Finished Thickness: ~1.60 mm** | |

---

## 2. Layer Utilization Strategy

- **Layer 1 (F.Cu - Top Face):**
  - Acts primarily as the acoustic faceplate.
  - Contains **NO components**.
  - Houses the 16 × 0.8 mm NPTH microphone acoustic entry holes with $5\,\text{mm}$ circular keep-outs.
  - Flooded with Ground copper to shield internal signal layers against external EMI.
- **Layer 2 (In1.Cu - Inner 1):**
  - Ground shield beneath top-layer traces.
  - Power distribution islands in the power supply section (+3V3, +5V, adapter input).
- **Layer 3 (In2.Cu - Inner 2):**
  - **100% Solid Ground Plane.** Zero signal cuts under high-speed traces.
  - Provides a low-impedance return current path for all Bottom-layer clock and data routes.
- **Layer 4 (B.Cu - Bottom Face):**
  - **Component Placement Layer:** All 193 SMD components reside on this layer.
  - High-speed TDM clock distribution (BCLK, FSYNC, SD2–SD4, I2S_DIN) and differential microphone pairs.
  - Flooded with GND copper with stitching vias connecting directly to In2.Cu.

---

## 3. Net Classes & Physical Routing Parameters

Calculations based on JLCPCB impedance calculator for JLC04161H-7628:

| Net Class | Target Impedance | Trace Width ($W$) | Clearance / Gap ($S$) | Member Nets | Design Notes |
|---|---|---|---|---|---|
| **50_ohm** | $50\,\Omega \pm 10\%$ (Single-Ended) | **0.320 mm** | **0.250 mm** | `BCLK*`, `FSYNC*`, `SD2`–`SD4`, `*SDOUT*`, `I2S_DIN`, `*MCLK*` | Coplanar waveguide with ground pour. Reference: `docs/images/50_ohm_impedance.png` |
| **USB_90R**| $90\,\Omega \pm 10\%$ (Differential) | **0.2703 mm** | **0.2032 mm** | `USB_D+`, `USB_D-` | Tightly coupled differential pair between `J2` and `U5` |
| **MIC_DIFF**| $100\,\Omega$ (Differential) | **0.200 mm** | **0.200 mm** | `*MK*_P/N`, `*_IN?P/N` | Tightly coupled analog differential pairs from microphones to ADCs |
| **MICBIAS** | DC Power | **0.250 mm** | **0.250 mm** | `U?_MICBIAS*` | Clean analog bias lines; decoupled at each microphone with $1\,\mu\text{F}$ |
| **POWER** | DC Power | **0.50–2.00 mm** | **0.250 mm** | `+12V`, `+5V`, `VSYS`, `+3V3`, `3V3A` | Wide polygons and fills sized for low DC resistance and thermal dissipation |
| **Default** | Standard Digital | **0.200 mm** | **0.200 mm** | All other logic signals (`IO*`, `SCL`, `SDA`, etc.) | General interconnect routing |

---

## 4. Signal Integrity & EMC Implementation

1. **Series Source Termination:**
   - Every digital driver output ($Y_1$, $U_4$, $U_{10}$, $U_1$–$U_3$) incorporates a **$33\,\Omega$ series resistor** ($R_{13}$–$R_{16}$, $R_{22}$–$R_{28}$) placed within $5\,\text{mm}$ of the driver pin.
2. **AC End Termination:**
   - FSYNC is terminated at ESP32 `IO7` using $R_{30} = 51\,\Omega$ in series with $C_{54} = 100\,\text{pF}$ to GND, absorbing transmission line reflections.
3. **Return-Path Ground Vias:**
   - Where high-speed clock or data traces transition between layers via vias, a dedicated Ground return via is placed immediately adjacent ($< 0.5\,\text{mm}$) to minimize return current loop area.
4. **Plane Edge Stitching Capacitors:**
   - Stitching capacitors $C_{97}$ and $C_{98}$ ($100\,\text{nF}$, +3V3 ↔ GND) are positioned where clock lines cross the boundary of the In1 power plane islands, maintaining continuous AC return path integrity.
5. **Thermal Relief & Via Array:**
   - TLV320ADC5140 exposed thermal pads (`U1`–`U4`) are bonded with **$3 \times 3$ (9 vias) arrays** of $0.3\,\text{mm}$ vias tied directly into the internal ground plane.
   - ESP32-S3 thermal pad features a **12-via array** of $0.2\,\text{mm}$ vias.

---

## 5. Keep-Out Zones & Custom DRC Rules

- **ESP32-S3 Antenna Keep-Out:**
  - A strict keep-out zone spanning all copper layers (F.Cu, In1.Cu, In2.Cu, B.Cu) is defined directly beneath the ESP32-S3 PCB trace antenna overhang. No copper or traces exist within this boundary.
- **Microphone Acoustic Keep-Out:**
  - $5.0\,\text{mm}$ diameter clearance around each 0.8 mm acoustic sound entry port on the top face.
- **Custom DRC Rules (`Beamfoarming_16x.kicad_dru`):**
  - Default clearances are strictly enforced across the board ($0.20\,\text{mm}$ track-to-track, $0.25\,\text{mm}$ track-to-pour).
  - Clearance constraints are selectively relaxed via custom rules only for ultra-fine pitch QFN/TSSOP footprints (`U1`–`U4`, `U10`, `J601`, `J2`) to prevent DFM errors during manufacturing.
