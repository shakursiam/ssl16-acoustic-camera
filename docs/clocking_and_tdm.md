# SSL-16 Clocking & TDM Bus Architecture

## 1. Clock Generation Architecture

High-precision sound source localization requires zero phase jitter and identical sampling instants across all 16 acoustic channels. The SSL-16 achieves this by deriving all digital audio timing from a single low-jitter master crystal oscillator.

| Clock Signal | Frequency | Source | Destination | Transmission Line & Termination |
|---|---|---|---|---|
| **MCLK** | 24.576 MHz | Y1 (Abracon ASE-24.576MHZ-LC-T) | U4 (`GPIO1` / MCLK) | 50 Ω coplanar, $R_{22} = 33\,\Omega$ source |
| **BCLK_SRC** | 12.288 MHz | U4 (`BCLK` pin, Controller) | U10 (`CLKIN`, LMK1C1104) | 50 Ω coplanar, $R_{27} = 33\,\Omega$ source |
| **BCLK_Y0** | 12.288 MHz | U10 (Pin 4, $Y_0$) | U1 (`BCLK`) | 50 Ω coplanar, $R_{13} = 33\,\Omega$ source |
| **BCLK_Y1** | 12.288 MHz | U10 (Pin 5, $Y_1$) | U2 (`BCLK`) | 50 Ω coplanar, $R_{14} = 33\,\Omega$ source |
| **BCLK_Y2** | 12.288 MHz | U10 (Pin 7, $Y_2$) | U3 (`BCLK`) | 50 Ω coplanar, $R_{15} = 33\,\Omega$ source |
| **BCLK_Y3** | 12.288 MHz | U10 (Pin 8, $Y_3$) | ESP32-S3 (`GPIO6`) | 50 Ω coplanar, $R_{16} = 33\,\Omega$ source |
| **FSYNC** | 48.0 kHz | U4 (`FSYNC` pin, Controller) | Fly-by: U3 → U2 → U1 → ESP32 (`GPIO7`) | 50 Ω coplanar, $R_{28} = 33\,\Omega$ source, $R_{30} = 51\,\Omega + C_{54} = 100\,\text{pF}$ AC end term |

---

## 2. Clock Tree & Distribution Diagram

```
[ Y1: 24.576 MHz XO ]
         │
      (R22: 33 Ω)
         ▼
[ U4 (ADC-4) GPIO1: MCLK ] ──(Generates internal dividers)
         │
   ┌─────┴────────────────────────────────┐
   │ BCLK (12.288 MHz)                    │ FSYNC (48 kHz)
(R27: 33 Ω)                            (R28: 33 Ω)
   │                                      │
   ▼                                      ▼ (Fly-by topology)
[ U10: LMK1C1104 Buffer ]                [ U3 FSYNC ]
   ├── Y0 ──(R13: 33 Ω)──> [ U1 BCLK ]    │
   ├── Y1 ──(R14: 33 Ω)──> [ U2 BCLK ]   [ U2 FSYNC ]
   ├── Y2 ──(R15: 33 Ω)──> [ U3 BCLK ]    │
   └── Y3 ──(R16: 33 Ω)──> [ ESP32 IO6 ] [ U1 FSYNC ]
                                          │
                                         [ ESP32 IO7 ]
                                          │
                                       [ AC Term: R30 (51 Ω) + C54 (100 pF) ]
```

---

## 3. TDM Frame Format & Slot Timing

- **Sampling Frequency ($f_s$):** $48\,\text{kHz}$
- **Slots per Frame:** 16 slots
- **Bits per Slot:** 16 bits
- **Total Bits per Frame:** $16 \times 16 = 256\,\text{bits}$
- **Bit Clock Rate:**
  $$\text{BCLK} = f_s \times 256 = 48{,}000 \times 256 = 12.288\,\text{MHz}$$
- **BCLK Period ($T_{\text{bclk}}$):**
  $$T_{\text{bclk}} = \frac{1}{12.288\,\text{MHz}} \approx 81.38\,\text{ns}$$
- **Duty Cycle:** 50% nominal ($40.69\,\text{ns}$ high, $40.69\,\text{ns}$ low).
- **Frame Sync (FSYNC):** PCM Short Frame mode. FSYNC pulses high for exactly 1 BCLK period ($81.38\,\text{ns}$) at the start of each frame coinciding with the MSB of Slot 0 (with standard 1-bit delay).

---

## 4. Transmission Line & Timing Margin Analysis

### 4.1 Transmission Line Characteristics
- All clock and high-speed data lines belong to net class `50_ohm` on the PCB.
- Trace width: **0.32 mm** with **0.25 mm** ground-pour clearance over the 0.21 mm prepreg dielectric, yielding an exact characteristic impedance $Z_0 \approx 50\,\Omega$ on JLCPCB stack-up JLC04161H-7628.
- Propagation delay in FR-4 ($v_p \approx 150\,\text{mm/ns}$):
  $$t_{pd} \approx 6.67\,\text{ps/mm}$$

### 4.2 Skew & Length Matching
- The maximum trace length variation between the longest clock trace (to ESP32) and the shortest (to U3) is less than **120 mm**.
- Worst-case routing propagation skew:
  $$\Delta t_{\text{skew}} < 120\,\text{mm} \times 6.67\,\text{ps/mm} \approx 0.80\,\text{ns}$$
- LMK1C1104 buffer output-to-output skew: $t_{\text{skew(o)}} \le 30\,\text{ps}$.
- Total cumulative clock skew: $< 1.0\,\text{ns}$.
- **Timing Margin:** Given $T_{\text{bclk}} = 81.38\,\text{ns}$, the available setup/hold window is approximately **40 ns**. With a total trace skew of $< 1\,\text{ns}$, the timing margin exceeds 39 ns. **Tight serpentine length matching is completely unnecessary.**

### 4.3 Termination Strategy
- **Series Damping ($33\,\Omega$):** The output impedance of the TLV320ADC5140 and LMK1C1104 drivers is $\sim 15\text{–}20\,\Omega$. Placing a $33\,\Omega$ resistor at each source results in a total source impedance of $\sim 50\,\Omega$, cleanly absorbing reflections from the high-impedance CMOS receivers.
- **AC End Termination ($51\,\Omega + 100\,\text{pF}$):** FSYNC routes to 4 receiving loads along a 180 mm fly-by trace. At the final receiver (ESP32 `IO7`), $R_{30} = 51\,\Omega$ in series with $C_{54} = 100\,\text{pF}$ to GND clamps high-frequency overshoot and ringing without placing a static DC load on `U4`.
