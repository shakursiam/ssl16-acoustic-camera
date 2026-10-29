# SSL-16 ESP32-S3 Pinout & Interface Mapping

## 1. ESP32-S3 Pin Mapping Table

The SSL-16 board utilizes an **ESP32-S3-WROOM-1-N8R8** module (`U5`), equipped with 8 MB embedded Octal Flash and 8 MB embedded Octal PSRAM.

| ESP32 Pin / GPIO | Net Name | Direction | Connected Peripheral | Schematic Ref | Functional Description & Constraints |
|---|---|---|---|---|---|
| **GPIO0** | `BOOT` | Input (Pull-up) | Tactile Switch `SW4` | Button SW4 | Strapping pin: sampled at boot. Hold low during reset to enter ROM bootloader. |
| **EN (CHIP_PU)**| `EN` | Input (RC delay) | Tactile Switch `SW3` | Button SW3 | Module reset line; pulled up with $10\,\text{k}\Omega$ (`R1`) and $1\,\mu\text{F}$ capacitor. |
| **GPIO4** | `SD_CMD` | Bidirectional | MicroSD Socket | `J601` Pin 3 | 4-bit SDMMC Command line; pulled up with $10\,\text{k}\Omega$ (`R604`). |
| **GPIO5** | `SD_CLK` | Output | MicroSD Socket | `J601` Pin 5 | 4-bit SDMMC Clock line. |
| **GPIO6** | `BCLK_Y3` | Input | LMK1C1104 Buffer `U10` | `U10` Pin 8 ($Y_3$) | **I2S Bit Clock (BCLK)**: 12.288 MHz clock received from buffer $Y_3$ via $R_{16}=33\,\Omega$. |
| **GPIO7** | `FSYNC` | Input | TDM FSYNC Bus | `U4` / `U10` / Term | **I2S Frame Sync (FSYNC / WS)**: 48 kHz short-frame pulse. AC terminated with $R_{30}+C_{54}$. |
| **GPIO8** | `SDA` | Bidirectional (OD) | I2C Data Bus | `U1`–`U4`, `U9`, `J4` | I2C Data line with $2.2\,\text{k}\Omega$ pull-up resistor `R18`. |
| **GPIO9** | `SCL` | Output (OD) | I2C Clock Bus | `U1`–`U4`, `U9`, `J4` | I2C Clock line with $2.2\,\text{k}\Omega$ pull-up resistor `R17`. |
| **GPIO11** | `SHDNZ` | Output | TLV320ADC5140 `SHDNZ` | `U1`–`U4` Pin 2 | **Global Hardware Shutdown**: Active-low. Pulled down with $100\,\text{k}\Omega$ (`R31`). |
| **GPIO13** | `I2S_DIN` | Input | Target ADC `U1` SDOUT | `U1` Pin 19 | **I2S / TDM Audio Data In**: Carries all 16 audio slots from `U1` via $R_{24}=33\,\Omega$. |
| **GPIO14** | `SD_CD` | Input | MicroSD Card Detect | `J601` Pin 9/10 | Active-low card detect switch; pulled up with $10\,\text{k}\Omega$ (`R602`). |
| **GPIO15** | `SD_D2` | Bidirectional | MicroSD Socket | `J601` Pin 1 | SDMMC Data 2 line; pulled up with $10\,\text{k}\Omega$ (`R606`). |
| **GPIO16** | `SD_D1` | Bidirectional | MicroSD Socket | `J601` Pin 8 | SDMMC Data 1 line; pulled up with $10\,\text{k}\Omega$ (`R605`). |
| **GPIO17** | `IO17` | Bidirectional | Expansion Header | `J6` Pin 7 / `J7` | General-purpose expansion IO. |
| **GPIO18** | `SD_D0` | Bidirectional | MicroSD Socket & LED | `J601` Pin 7 | SDMMC Data 0 line; drives SD activity LED `D601` through $R_{601}=2\,\text{k}\Omega$. |
| **GPIO19** | `USB_D-` | Bidirectional | USB-C Receptacle `J2` | `U6` / `J2` Pin A7/B7| Native USB Full-Speed Differential D− line (USB-Serial/JTAG controller). |
| **GPIO20** | `USB_D+` | Bidirectional | USB-C Receptacle `J2` | `U6` / `J2` Pin A6/B6| Native USB Full-Speed Differential D+ line (USB-Serial/JTAG controller). |
| **GPIO21** | `SD_D3` | Bidirectional | MicroSD Socket | `J601` Pin 2 | SDMMC Data 3 line (CS in SPI mode); pulled up with $10\,\text{k}\Omega$ (`R607`). |
| **GPIO35** | `IO35` | **RESERVED** | Octal PSRAM / Header | `J6` / `J7` | **DO NOT USE:** Internally bonded to Octal PSRAM in N8R8 module. |
| **GPIO36** | `IO36` | **RESERVED** | Octal PSRAM / Header | `J6` / `J7` | **DO NOT USE:** Internally bonded to Octal PSRAM in N8R8 module. |
| **GPIO37** | `IO37` | **RESERVED** | Octal PSRAM / Header | `J6` / `J7` | **DO NOT USE:** Internally bonded to Octal PSRAM in N8R8 module. |
| **GPIO38** | `IO38` | Bidirectional | Expansion Header | `J6` / `J7` | User expansion GPIO / SPI. |
| **GPIO39** | `IO39` | Bidirectional | Expansion Header | `J6` / `J7` | User expansion GPIO / SPI. |
| **GPIO40** | `IO40` | Bidirectional | Expansion Header | `J6` / `J7` | User expansion GPIO / SPI. |
| **GPIO41** | `IO41` | Bidirectional | Expansion Header | `J6` / `J7` | User expansion GPIO / SPI. |
| **GPIO42** | `IO42` | Bidirectional | Expansion Header | `J6` / `J7` | User expansion GPIO / SPI. |
| **GPIO43** | `U0TXD` | Output | UART Header `J3` | `J3` Pin 2 | ESP32-S3 Hardware UART0 TX (Console output). |
| **GPIO44** | `U0RXD` | Input | UART Header `J3` | `J3` Pin 3 | ESP32-S3 Hardware UART0 RX (Console input). |
| **GPIO48** | `WS2812_DIN` | Output | RGB LED `D6` | `D6` Pin 4 (DIN) | Addressable RGB LED control signal (+5V rail dependent). |

---

## 2. Critical Caution: Octal PSRAM Pin Conflict (IO35–IO37)

> [!CAUTION]  
> **Octal PSRAM Conflict:**  
> The module installed on Rev A is the **ESP32-S3-WROOM-1-N8R8**, which integrates **Octal SPI PSRAM**.  
> In all ESP32-S3 modules utilizing octal PSRAM (OPI), **GPIO35, GPIO36, and GPIO37 are internally bonded directly to the high-speed PSRAM die**.  
> Although these signals are routed out to expansion headers `J6` and `J7` on the PCB, **THEY MUST NEVER BE DRIVEN OR CONFIGURED IN FIRMWARE AS GENERAL-PURPOSE GPIOs**. Attempting to configure or externally pull GPIO35–37 will crash the memory bus, cause immediate system kernel panics, or corrupt audio buffers.

---

## 3. Peripheral Connector Pinouts

### UART Console Header (J3)
| Pin Number | Signal Name | Description |
|---|---|---|
| Pin 1 | `+3V3` | 3.3 V Power output |
| Pin 2 | `U0TXD` (GPIO43) | UART0 Transmit |
| Pin 3 | `U0RXD` (GPIO44) | UART0 Receive |
| Pin 4 | `GND` | System Ground |

### I2C Auxiliary Breakout Header (J4)
| Pin Number | Signal Name | Description |
|---|---|---|
| Pin 1 | `+3V3` | 3.3 V Power output |
| Pin 2 | `SCL` (GPIO9) | I2C Clock ($2.2\,\text{k}\Omega$ pull-up) |
| Pin 3 | `SDA` (GPIO8) | I2C Data ($2.2\,\text{k}\Omega$ pull-up) |
| Pin 4 | `GND` | System Ground |
