# SSL-16 System Architecture & Hardware Block Diagram

## 1. System Overview

The **SSL-16** is a 16-channel MEMS microphone acoustic camera board engineered for high-resolution sound source localization (target application: vehicle horn and directional traffic noise localization in dense urban environments such as Dhaka, Bangladesh).

```mermaid
flowchart TD
    subgraph AcousticArray ["16-Channel Acoustic Front-End (Sunflower Array R80)"]
        direction LR
        MIC_GRP1["MK2, MK7, MK10, MK15<br/>(4× IM73A135 Diff)"]
        MIC_GRP2["MK1, MK4, MK9, MK12<br/>(4× IM73A135 Diff)"]
        MIC_GRP3["MK3, MK6, MK11, MK14<br/>(4× IM73A135 Diff)"]
        MIC_GRP4["MK5, MK8, MK13, MK16<br/>(4× IM73A135 Diff)"]
    end

    subgraph ClockSource ["Master Clock Source"]
        Y1["Abracon 24.576 MHz XO<br/>(ASE-24.576MHZ-LC-T)"]
        R22["R22 (33 Ω)"]
        Y1 --> R22
    end

    subgraph ADCs ["Digitization & TDM Chain (4× TLV320ADC5140)"]
        U4["ADC-4 (U4, 0x4F)<br/><b>TDM Controller</b><br/>Slots 12–15"]
        U3["ADC-3 (U3, 0x4E)<br/>Target / Daisy In<br/>Slots 8–11"]
        U2["ADC-2 (U2, 0x4D)<br/>Target / Daisy In<br/>Slots 4–7"]
        U1["ADC-1 (U1, 0x4C)<br/>Target / Daisy In<br/>Slots 0–3"]
    end

    subgraph ClockDistribution ["Clock Fan-Out & Routing"]
        U10["LMK1C1104 (U10)<br/>1:4 LVCMOS Buffer"]
        R27["R27 (33 Ω)"]
        R13["R13 (33 Ω)"]
        R14["R14 (33 Ω)"]
        R15["R15 (33 Ω)"]
        R16["R16 (33 Ω)"]
        R28["R28 (33 Ω)"]
        TERM["R30 (51 Ω) + C54 (100 pF)<br/>AC Termination"]
    end

    subgraph Processing ["Embedded Controller & Storage"]
        U5["ESP32-S3-WROOM-1-N8R8 (U5)<br/>I2S/TDM Slave, Wi-Fi, BLE"]
        SD["microSD Card (J601)<br/>4-Bit SDMMC"]
        USB["USB-C Port (J2)<br/>Native USB-Serial/JTAG"]
        TMP["TMP112 (U9, 0x48)<br/>Thermal Sensor"]
        U5 --- SD
        U5 --- USB
    end

    %% Audio Connections
    MIC_GRP4 -->|4× Diff Pairs| U4
    MIC_GRP3 -->|4× Diff Pairs| U3
    MIC_GRP2 -->|4× Diff Pairs| U2
    MIC_GRP1 -->|4× Diff Pairs| U1

    %% Clock generation & fan-out
    R22 -->|MCLK (24.576 MHz)| U4
    U4 -->|BCLK (12.288 MHz)| R27 --> U10
    U10 -->|Y0| R13 --> U1
    U10 -->|Y1| R14 --> U2
    U10 -->|Y2| R15 --> U3
    U10 -->|Y3| R16 -->|IO6 (BCLK)| U5

    %% FSYNC Fly-by
    U4 -->|FSYNC (48 kHz)| R28 --> U3
    U3 --> U2
    U2 --> U1
    U1 -->|IO7 (FSYNC)| U5
    U5 --- TERM

    %% Data Daisy-Chain
    U4 -->|SDOUT via R26| U3
    U3 -->|SDOUT via R25| U2
    U2 -->|SDOUT via R23| U1
    U1 -->|SDOUT via R24 / I2S_DIN| U5

    %% Control Lines
    U5 -->|IO8 (SDA) / IO9 (SCL) [2.2 kΩ Pull-ups]| U1
    U5 -.->|I2C| U2
    U5 -.->|I2C| U3
    U5 -.->|I2C| U4
    U5 -.->|I2C| TMP
    U5 -->|IO11 (SHDNZ) [100 kΩ Pull-down]| U1
    U5 -.->|SHDNZ| U2
    U5 -.->|SHDNZ| U3
    U5 -.->|SHDNZ| U4
```

---

## 2. Key Architecture Principles

### 2.1 Single TDM Controller Architecture
In multi-channel audio designs, clock mismatch or relative phase drift between discrete ADCs causes frame corruption and phase incoherence, destroying beamforming resolution. 
- **The SSL-16 designates U4 (ADC-4) as the sole TDM Controller.**
- `U4` receives a low-jitter 24.576 MHz master clock from oscillator `Y1` on its `GPIO1` pin configured as `MCLK`.
- `U4` internally divides the clock to generate the synchronous **BCLK (12.288 MHz)** and **FSYNC (48 kHz)** signals.

### 2.2 Low-Skew Clock Fan-Out (LMK1C1104)
- Rather than driving all four ADCs and the ESP32 directly from `U4`'s internal pin driver, `U4`'s BCLK output feeds a dedicated 1:4 low-skew LVCMOS clock buffer (**TI LMK1C1104**, `U10`).
- The four buffered outputs ($Y_0, Y_1, Y_2, Y_3$) drive $U_1$, $U_2$, $U_3$, and the ESP32-S3 (`IO6`) respectively through individual $33\,\Omega$ series source damping resistors ($R_{13}, R_{14}, R_{15}, R_{16}$).
- Pin-to-pin skew through `U10` is $<30\,\text{ps}$, guaranteeing identical clock edges across all ADCs.

### 2.3 Fly-By FSYNC with End Termination
- FSYNC (48 kHz) originates at `U4` and routes in a single daisy/fly-by topology passing consecutively across $U_3$, $U_2$, $U_1$ and terminates at ESP32-S3 `IO7`.
- An AC end termination network ($R_{30} = 51\,\Omega$, $C_{54} = 100\,\text{pF}$) at the ESP32 input prevents transmission line ringing without adding DC loading.

### 2.4 Data Daisy-Chaining (TI SBAA383 Topology)
- Rather than consuming four separate data input pins on the MCU, all 16 audio channels travel across a single TDM data lane (`I2S_DIN` on `IO13`):
  $$\text{U4 (SDOUT)} \xrightarrow{R_{26}} \text{U3 (GPIO1)} \xrightarrow{R_{25}} \text{U2 (GPIO1)} \xrightarrow{R_{23}} \text{U1 (GPIO1)} \xrightarrow{R_{24}} \text{ESP32 (IO13)}$$
- Each ADC is programmed for slots 0–3. The internal hardware daisy-chain registers automatically shift upstream data packets by 4 slots, such that at the final output of `U1`:
  - Slots 0–3 contain `U1` (MK2, MK7, MK10, MK15)
  - Slots 4–7 contain `U2` (MK1, MK4, MK9, MK12)
  - Slots 8–11 contain `U3` (MK3, MK6, MK11, MK14)
  - Slots 12–15 contain `U4` (MK5, MK8, MK13, MK16)

### 2.5 I2C & Power Management
- A shared I2C bus (`IO9` SCL, `IO8` SDA) with $2.2\,\text{k}\Omega$ pull-up resistors connects all four ADCs, the TMP112 thermal sensor (`0x48`), and an external breakout header `J4`.
- A global active-low shutdown line `SHDNZ` (`IO11`) with a $100\,\text{k}\Omega$ pull-down resistor (`R31`) holds all four ADCs in low-power shutdown until firmware releases them.
