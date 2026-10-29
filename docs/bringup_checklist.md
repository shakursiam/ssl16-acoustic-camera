# SSL-16 Hardware Bring-Up & Verification Checklist

This document provides the mandatory step-by-step procedure for safely bringing up the **SSL-16 Rev A** prototype boards upon arrival from JLCPCB.

---

## Stage 1: Optical & Physical Inspection (Prior to Power-Up)

- [ ] **1.1 Microphone Port Inspection:**  
  Inspect the top side of the PCB under a stereo microscope. Confirm that all 16 × 0.8 mm acoustic sound holes are completely unobstructed and that no solder paste or flux has contaminated the acoustic ports of `MK1`–`MK16`.
- [ ] **1.2 IC Pin 1 Orientation:**  
  - `U1`–`U4` (TLV320ADC5140): Confirm dot on QFN package aligns with pin 1 marker on PCB silkscreen.
  - `U5` (ESP32-S3-WROOM-1): Confirm module orientation.
  - `U10` (LMK1C1104): Confirm TSSOP pin 1 alignment.
  - `Y1` (Abracon 24.576 MHz XO): Confirm chamfered/dot pad matches Pin 1 pad.
- [ ] **1.3 Polarized Component Orientation:**  
  - Electrolytic polymer capacitors `C106`, `C107` (470 µF): Confirm cathode indicator band matches silkscreen.
  - Diodes `D1` (B5818WS), `D2` (PMEG4050EP), and LEDs `D3`, `D4`, `D5`, `D601`: Confirm cathode line matches silkscreen.
- [ ] **1.4 Cold Resistance Checks:**  
  Measure impedance with a digital multimeter between Ground (`GND`) and all main rails:
  - `+12V` to `GND`: $> 10\,\text{k}\Omega$
  - `+5V` to `GND`: $> 5\,\text{k}\Omega$
  - `VSYS` to `GND`: $> 5\,\text{k}\Omega$
  - `+3V3` to `GND`: $> 1\,\text{k}\Omega$
  - `3V3A` to `GND`: $> 1\,\text{k}\Omega$

---

## Stage 2: Power Rails Verification (Blank MCU / No Firmware)

- [ ] **2.1 USB-Only Power Verification:**  
  Plug in USB-C cable `J2` from a current-limited bench supply or protected USB port.
  - Measure `VBUS`: Verify $4.95\text{–}5.10\,\text{V}$.
  - Measure `VSYS`: Verify $\approx 4.90\text{–}5.05\,\text{V}$ (confirm $Q_1$ is ON with minimal drop).
  - Measure `+5V`: Confirm $0\,\text{V}$ ($D_1$ blocks backfeed).
  - Measure `+3V3` at test point `TP3_3V3`: Verify $3.30\,\text{V} \pm 2\%$.
  - Measure `3V3A` at test point `3V3A1`: Verify $3.30\,\text{V} \pm 1\%$.
- [ ] **2.2 12 V Adapter Power Verification:**  
  Disconnect USB. Plug in 12 V DC adapter into `J8`.
  - Measure `+5V` at test point `5V1`: Verify $5.00\,\text{V} \pm 3\%$.
  - Measure `VSYS`: Verify $\approx 4.65\text{–}4.75\,\text{V}$ (Schottky drop through $D_1$).
  - Confirm $Q_1$ is OFF: Measure gate of $Q_1$ is at $5.0\,\text{V}$.
  - Measure `+3V3` and `3V3A`: Verify both remain stable at $3.30\,\text{V}$.
  - Confirm addressable RGB LED `D6` receives 5V.

---

## Stage 3: Master Clock Oscillator (MCLK) Verification

- [ ] **3.1 Y1 Output Check:**  
  Connect a high-impedance 10:1 passive scope probe or active probe to test point `MCLK1` (or pin 4 of `Y1`):
  - Frequency: **$24.576\,\text{MHz} \pm 25\,\text{ppm}$**.
  - Logic Levels: $V_{\text{OH}} \ge 2.9\,\text{V}$, $V_{\text{OL}} \le 0.3\,\text{V}$.
  - Waveform: Clean 3.3V CMOS square wave with $< 3\,\text{ns}$ rise/fall time, no excessive overshoot.
  - Check signal arrival at `U4` pin 14 (`GPIO1`).

---

## Stage 4: Microcontroller Flashing & I2C Bus Enumeration

- [ ] **4.1 Native USB Flashing:**  
  Connect USB-C to PC. Hold `BOOT` (`SW4`), tap `EN` (`SW3`), release `BOOT`. Confirm ESP32-S3 ROM bootloader enumerates in Device Manager / `lsusb` as `USB JTAG/serial debug unit`.
- [ ] **4.2 Basic Firmware Flash:**  
  Flash a minimal test firmware sketch over native USB. Confirm Serial Monitor output at 115200 baud.
- [ ] **4.3 I2C Bus Scan:**  
  Run an I2C scanner sketch at 100 kHz on `SDA=GPIO8`, `SCL=GPIO9`.  
  **Expected Detected Addresses (5 total):**
  - [ ] `0x48`: TMP112 Temperature Sensor (`U9`)
  - [ ] `0x4C`: TLV320ADC5140 ADC-1 (`U1`, Target)
  - [ ] `0x4D`: TLV320ADC5140 ADC-2 (`U2`, Target)
  - [ ] `0x4E`: TLV320ADC5140 ADC-3 (`U3`, Target)
  - [ ] `0x4F`: TLV320ADC5140 ADC-4 (`U4`, Controller)

---

## Stage 5: ADC Power Release & Microphone Bias Check

- [ ] **5.1 SHDNZ Release:**  
  Drive `GPIO11` (`SHDNZ`) **HIGH** (3.3V) in firmware. Verify `SHDNZ` pin on all four ADCs rises to $3.3\,\text{V}$.
- [ ] **5.2 Load Register Scripts:**  
  Send common initialization script (`BIAS_CFG = 0x00`).
- [ ] **5.3 MICBIAS Voltage Verification:**  
  Probe test points `U1_MICBIAS1`, `U2_MICBIAS1`, `U3_MICBIAS1`, `U4_MICBIAS1`:
  - Verify all 4 points measure **$\approx 2.75\,\text{V}$** (internal VREF).
  - **CRITICAL:** Ensure voltage never exceeds **3.0 V** at any microphone pad.

---

## Stage 6: Digital Audio Clock & TDM Bus Validation

- [ ] **6.1 BCLK Verification:**  
  Configure `U4` in Controller mode. Probe `BCLK_SRC1` (source out of `U4`) and buffer outputs `BCLK_Y0`, `BCLK_Y1`, `BCLK_Y2`, `BCLK_Y3`:
  - Frequency: **$12.288\,\text{MHz}$** (50% duty cycle).
  - Verify all 4 buffer outputs are synchronous with $< 1\,\text{ns}$ skew.
- [ ] **6.2 FSYNC Verification:**  
  Probe `FSYNC1` (at `U4`) and at ESP32 `IO7`:
  - Frequency: **$48.0\,\text{kHz}$**.
  - Pulse width: Exactly **1 BCLK period** ($81.4\,\text{ns}$).
  - Verify clean edge transitions without reflection ringing at `IO7`.
- [ ] **6.3 Data Daisy-Chain Probing:**  
  Observe data output lines on an oscilloscope:
  - Probe `SD4` (`U4` SDOUT → `U3`): Slots 0–3 active.
  - Probe `SD3` (`U3` SDOUT → `U2`): Slots 0–7 active.
  - Probe `SD2` (`U2` SDOUT → `U1`): Slots 0–11 active.
  - Probe `I2S_DIN1` (`U1` SDOUT → ESP32 `IO13`): All 16 slots populated.

---

## Stage 7: 16-Channel Audio Capture & Physical Mapping Verification

- [ ] **7.1 DMA Buffer Capture:**  
  Initialize ESP32 I2S DMA in TDM slave mode. Stream raw frames into RAM / microSD.
- [ ] **7.2 Microphone Tap Test (Channel Mapping):**  
  While monitoring real-time channel RMS levels or plotting waveforms:
  - Gently tap acoustic port `MK1`: Confirm impulse appears in **Slot 4**.
  - Tap `MK2`: Confirm impulse in **Slot 0**.
  - Repeat for all 16 microphones to confirm 100% adherence to the mapping table in `docs/adc_configuration.md`.

---

## Stage 8: Sound Source Localization Test

- [ ] **8.1 Stationary Calibration Tone:**  
  Place an acoustic speaker emitting a $3.0\,\text{kHz}$ sine tone at broadside ($0^\circ, 0^\circ$) at 1 meter distance.
- [ ] **8.2 Delay-and-Sum Beamforming:**  
  Execute offline or real-time SRP-PHAT beamforming algorithm. Verify calculated acoustic map peak centers at $(0^\circ, 0^\circ)$.
- [ ] **8.3 Azimuth Sweep:**  
  Move sound source from $-60^\circ$ to $+60^\circ$ azimuth. Verify localized angle tracks the physical target without spatial ambiguity.
