# SSL-16 Hardware Design Review & Engineering Change Log

This document records the architectural improvements, signal integrity fixes, and layout revisions resolved between preliminary design iterations and the final tape-out of **Rev A**.

---

## 1. Summary of Critical Architectural Decisions

### 1.1 Resolution of Multi-ADC Clock Synchronization & Drift (v1.0 Issue)
- **v1.0 Problem:** In early conceptual schematics, ADCs relied on independent clock sources or daisy-chained bit clocks. Due to internal PLL jitter and propagation delay accumulation through cascaded ICs, BCLK and FSYNC phase edges drifted relative to one another, causing intermittent bit slips, frame desynchronization, and loss of phase coherence required for beamforming.
- **Rev A Architectural Solution:**
  1. Designated **U4 (ADC-4)** as the single master **TDM Clock Controller** for the entire board, driven by an external Abracon $24.576\,\text{MHz}$ low-jitter crystal oscillator (`Y1`).
  2. Implemented a dedicated 1:4 low-skew LVCMOS clock fan-out buffer (**TI LMK1C1104**, `U10`) to distribute BCLK simultaneously to $U_1$, $U_2$, $U_3$, and the ESP32-S3 (`IO6`) with $< 30\,\text{ps}$ pin-to-pin skew.
  3. Routed FSYNC in a fly-by bus topology with $R_{30} = 51\,\Omega + C_{54} = 100\,\text{pF}$ AC end termination.

### 1.2 Ground Plane Unification (Removal of Split Analog Ground)
- **v1.0 Issue:** Earlier drafts considered splitting the Ground plane into AGND and DGND joined by a single ferrite bead or net tie.
- **Engineering Review Decision:** A split plane would force the high-speed return currents of digital clock lines (BCLK at $12.288\,\text{MHz}$, data lines) to take massive loop detours around the split, resulting in severe RF radiation and EMI.
- **Rev A Implementation:** Adopted a single, solid, unbroken Ground plane across Layer 3 (`In2.Cu`) beneath all signal routing, relying on physical spatial segregation between the sensitive microphone array and the noisy MCU/switching buck converter.

### 1.3 Differential Net Renaming & Tightly Coupled Routing
- **v1.0 Issue:** Microphone analog tracks had arbitrary single-ended net names, preventing EDA differential impedance and clearance rules from being applied.
- **Rev A Fix:** Systematically renamed all analog microphone routes to formal differential pairs (`MKn_P` / `MKn_N`, `Ux_INnP` / `Ux_INnN`). Sized as tightly coupled $100\,\Omega$ differential coplanar waveguide pairs ($0.2\,\text{mm}$ width, $0.2\,\text{mm}$ gap).

### 1.4 Hardware Shutdown Line (SHDNZ) Stabilization
- **v1.0 Issue:** Earlier schematic contained a pull-up resistor ($R_{19}$) to 3.3V on the active-low `SHDNZ` net, which inadvertently woke up the ADCs before the microcontroller finished booting and before power rails had fully stabilized.
- **Rev A Fix:** Removed pull-up $R_{19}$. Retained a solid $100\,\text{k}\Omega$ pull-down resistor ($R_{31}$) to Ground. All ADCs now remain completely quiescent in low-power shutdown until firmware explicitly asserts `GPIO11` HIGH.

### 1.5 Analog Rail (3V3A) Sourcing from VSYS for USB Operation
- **v1.0 Issue:** The input to the clean analog LDO (`U11`, TPS7A2033) was initially tied to the `+5V` rail coming out of the XL2596S buck converter. Under USB-only operation, `+5V` was inactive, leaving the ADCs with no analog power (AVDD = 0V) and rendering USB development impossible.
- **Rev A Fix:** Moved the input of `U11` from `+5V` to **`VSYS`** (the diode/MOSFET OR-ed system rail). As a result, clean $3.3\,\text{V}$ analog power (`3V3A`) is present whether running from the 12 V wall adapter or from USB-C.

### 1.6 Multilayer Antenna Keep-Out Zone
- **v1.0 Issue:** Ground pour existed on internal layers beneath the ESP32-S3 PCB trace antenna.
- **Rev A Fix:** Extended the antenna keep-out boundary to all 4 copper layers (`F.Cu`, `In1.Cu`, `In2.Cu`, `B.Cu`). Guaranteed zero copper beneath the antenna overhang to preserve RF antenna impedance and 2.4 GHz Wi-Fi radiation efficiency.

### 1.7 Return-Path Ground Stitching Vias
- **Review Finding:** Digital signals transitioning between top and bottom routing layers via vias can create high-impedance discontinuities in the return path.
- **Rev A Implementation:** Added Ground vias immediately adjacent ($< 0.5\,\text{mm}$) to every high-speed clock (BCLK, FSYNC) and data (SD2–SD4, I2S_DIN) via transition, maintaining a continuous low-inductance return loop.

### 1.8 Plane Edge Stitching Capacitors (C97 / C98)
- **Review Finding:** Clock and data traces cross the boundary of the `In1.Cu` power plane islands where the underlying reference changes from GND to +3V3 copper.
- **Rev A Implementation:** Placed high-frequency ceramic stitching capacitors $C_{97}$ and $C_{98}$ ($100\,\text{nF}$ 0402, +3V3 ↔ GND) directly at the plane boundary crossing points, providing an AC short circuit for return currents.

### 1.9 I2C Bus Pull-Up Resistor Optimization
- **Review Finding:** Across a $480\,\text{mm}$ bus length connecting 6 capacitive loads (4 ADCs, TMP112, MCU), $4.7\,\text{k}\Omega$ pull-up resistors resulted in an estimated RC time constant exceeding $250\,\text{ns}$, creating sluggish edges at 400 kHz.
- **Rev A Fix:** Reduced pull-up resistors $R_{17}$ and $R_{18}$ from $4.7\,\text{k}\Omega$ to **$2.2\,\text{k}\Omega$**, ensuring crisp $t_{\text{rise}} < 120\,\text{ns}$ without exceeding the open-drain sink current specification.
