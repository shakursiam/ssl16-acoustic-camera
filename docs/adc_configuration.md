# SSL-16 TLV320ADC5140 Configuration & Register Map

> [!IMPORTANT]  
> **To be verified at bring-up.** The register values detailed below are derived from TI application note SBAA383 and the TLV320ADC5140 datasheet. They must be validated during initial hardware bring-up using an oscilloscope and I2S packet analyzer.

---

## 1. Hardware Address & Channel Allocation

The board hosts four TI TLV320ADC5140 four-channel audio ADCs (`U1`–`U4`). The hardware I2C address is configured using the strapping pins `ADDR1` and `ADDR0`:

| ADC Device | I2C Addr (7-bit) | ADDR1 Pin | ADDR0 Pin | Analog IN1 | Analog IN2 | Analog IN3 | Analog IN4 | Output TDM Slots | Role in Chain |
|---|---|---|---|---|---|---|---|---|---|
| **U1 (ADC-1)** | `0x4C` | GND | GND | MK2 | MK7 | MK10 | MK15 | Slots 0–3 | Target (Final out → ESP32) |
| **U2 (ADC-2)** | `0x4D` | GND | +3V3 | MK1 | MK4 | MK9 | MK12 | Slots 4–7 | Target (Daisy link) |
| **U3 (ADC-3)** | `0x4E` | +3V3 | GND | MK3 | MK6 | MK11 | MK14 | Slots 8–11 | Target (Daisy link) |
| **U4 (ADC-4)** | `0x4F` | +3V3 | +3V3 | MK5 | MK8 | MK13 | MK16 | Slots 12–15 | **Controller** (Generates clocks) |

### Acoustic Input Coupling & Microphone Bias
- Each analog microphone (`MKn`) outputs a differential signal pair (`OUT+`, `OUT−`).
- Signal coupling: `OUT+` → $1\,\mu\text{F}$ (0402 ceramic) → `INxP`, `OUT−` → $1\,\mu\text{F}$ → `INxN`.
- Power: Each microphone VDD is powered directly from its associated ADC's **MICBIAS** pin, decoupled by a local $1\,\mu\text{F}$ capacitor adjacent to each microphone footprint.

> [!CAUTION]  
> **MICBIAS Voltage Limit:** Register `BIAS_CFG` (`0x3B`) must be programmed to `0x00` ($\text{MICBIAS} = \text{VREF} \approx 2.75\,\text{V}$).  
> **NEVER set MICBIAS to AVDD (3.3 V):** The Infineon IM73A135 MEMS microphone has an **absolute maximum VDD rating of 3.0 V**. Applying 3.3 V will permanently damage or degrade the microphone array.

---

## 2. TDM Daisy-Chain Principle (TI SBAA383)

All four ADCs are configured identically for primary audio processing:
- Each ADC samples its 4 differential channels into local internal slots 0, 1, 2, and 3.
- In targets `U1`, `U2`, and `U3`, the daisy-chain engine is enabled (`ASI_CFG2 = 0x80`), and `GPIO1` is configured as the daisy-chain audio data input (`GPIO_CFG0 = 0xB0`).
- Upstream data arriving on `GPIO1` is shifted in time by 4 slots and merged with local data onto `SDOUT`:
  - `U4` outputs its 4 channels in slots 0–3 of its local stream.
  - `U3` receives `U4`'s data, shifts it into slots 4–7, and outputs its own 4 channels in slots 0–3.
  - `U2` receives `U3`'s data, shifts incoming slots 0–7 to slots 4–11, and outputs its own channels in slots 0–3.
  - `U1` receives `U2`'s data, shifts incoming slots 0–11 to slots 4–15, and outputs its own channels in slots 0–3.
  - **Result arriving at ESP32-S3 `IO13` (`I2S_DIN`):**
    - Slots 0–3: `U1` (MK2, MK7, MK10, MK15)
    - Slots 4–7: `U2` (MK1, MK4, MK9, MK12)
    - Slots 8–11: `U3` (MK3, MK6, MK11, MK14)
    - Slots 12–15: `U4` (MK5, MK8, MK13, MK16)

---

## 3. Power-Up & Initialization Sequence

1. **Power Stabilization:** Apply power (+12V adapter or USB-C). Ensure +5V, VSYS, +3V3, and 3V3A rails are stable.
2. **Hardware Reset Release:** Microcontroller asserts `GPIO11` (`SHDNZ`) **HIGH** (3.3 V). (All ADCs are held in low-power reset by default by pull-down resistor `R31`).
3. **Reference Wait:** Wait $\ge 1\,\text{ms}$ for internal reference voltage and charge pump ramp-up.
4. **Configure Targets First:** Send I2C configuration packets to `U1` (`0x4C`), `U2` (`0x4D`), and `U3` (`0x4E`).
5. **Configure Controller Last:** Send I2C configuration packet to `U4` (`0x4F`). As soon as `U4` powers up its ASI block, it begins outputting BCLK and FSYNC, latching all four devices into frame lock simultaneously.

---

## 4. Register Configuration Script

### 4.1 Common Initialization (All ADCs: U1, U2, U3, U4)

```c
// Page Selection: Page 0
i2c_write(addr, 0x00, 0x00);

// Sleep & Power: Wake up device, enable internal analog regulator
i2c_write(addr, 0x02, 0x81); // SLEEP_CFG: AREG_SELECT=1, WAKE_UP=1

// MICBIAS: 2.75V VREF mode (CRITICAL: DO NOT USE 3.3V)
i2c_write(addr, 0x3B, 0x00); // BIAS_CFG: MICBIAS = VREF (~2.75V)

// Audio Serial Interface Format: TDM mode, 16-bit word length
i2c_write(addr, 0x07, 0x01); // ASI_CFG0: ASI_FORMAT=TDM (0x00/0x01), ASI_WLEN=16-bit

// Channel Input Impedance: 10 kΩ for CH1–CH4
i2c_write(addr, 0x3C, 0x04); // CH1_CFG0: IN1 10 kΩ diff
i2c_write(addr, 0x41, 0x04); // CH2_CFG0: IN2 10 kΩ diff
i2c_write(addr, 0x46, 0x04); // CH3_CFG0: IN3 10 kΩ diff
i2c_write(addr, 0x4B, 0x04); // CH4_CFG0: IN4 10 kΩ diff

// Channel Slot Assignment: Default slots 0, 1, 2, 3
i2c_write(addr, 0x3D, 0x00); // CH1_CFG1: Slot 0
i2c_write(addr, 0x42, 0x01); // CH2_CFG1: Slot 1
i2c_write(addr, 0x47, 0x02); // CH3_CFG1: Slot 2
i2c_write(addr, 0x4C, 0x03); // CH4_CFG1: Slot 3
```

### 4.2 Target ADC Specific Settings (U1, U2, U3)

```c
// ASI Configuration 1:
// U1 (Final Stage to MCU):
i2c_write(0x4C, 0x08, 0xA1); // ASI_CFG1: TX_FILL=1, TX_LSB=0, TX_EDGE=1 (drive data on rising edge)
// U2 and U3:
i2c_write(0x4D, 0x08, 0x81); // ASI_CFG1: Normal TDM
i2c_write(0x4E, 0x08, 0x81); // ASI_CFG1: Normal TDM

// Enable Daisy-Chain Mode on Targets
i2c_write(target_addr, 0x09, 0x80); // ASI_CFG2: DAISY_EN=1

// Configure GPIO1 as Daisy-Chain Input
i2c_write(target_addr, 0x21, 0xB0); // GPIO_CFG0: GPIO1 = Daisy-Chain Input (GPI)

// Clock Master / Target: Target Mode (slaved to external BCLK & FSYNC)
i2c_write(target_addr, 0x13, 0x00); // MST_CFG0: Target mode

// Power Up Target Blocks (Perform last on U1, U2, U3)
i2c_write(target_addr, 0x75, 0xE0); // PWR_CFG: Power up MICBIAS, ADC channels, and PLL/ASI
```

### 4.3 Controller ADC Specific Settings (U4, 0x4F)

```c
// Configure GPIO1 as MCLK Input (24.576 MHz from Y1)
i2c_write(0x4F, 0x21, 0xA0); // GPIO_CFG0: GPIO1 = MCLK input

// ASI Configuration 1
i2c_write(0x4F, 0x08, 0x81); // ASI_CFG1: Normal TDM

// Configure U4 as Audio Clock Controller (Master Mode)
i2c_write(0x4F, 0x13, 0xA0); // MST_CFG0: MST_MODE=1 (Controller generates BCLK & FSYNC)
i2c_write(0x4F, 0x14, 0x48); // MST_CFG1: Auto-generate BCLK=12.288 MHz from 24.576 MHz MCLK
i2c_write(0x4F, 0x16, 0xD8); // MST_CFG3: FSYNC divider ratio for 48 kHz (256 BCLKs per frame)

// Power Up Controller (Execute last in bring-up sequence)
i2c_write(0x4F, 0x75, 0xC0); // PWR_CFG: Power up MICBIAS, ADCs, and Master ASI clock generators
```
