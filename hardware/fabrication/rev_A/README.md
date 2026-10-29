# SSL-16 Hardware Fabrication & Assembly Notes (Rev A)

**Board Revision:** LAB PROTOTYPE · REV A · 2026-11  
**Manufacturer:** JLCPCB  
**PCB Dimensions:** 230 mm × 170 mm  
**Order Date:** October 2026  

---

## 1. PCB Fabrication Parameters

| Parameter | JLCPCB Setting / Value | Notes |
|---|---|---|
| **Layer Count** | 4 Layers | L1: F.Cu, L2: In1.Cu, L3: In2.Cu, L4: B.Cu |
| **Board Dimensions** | 230 mm × 170 mm | Rectangular with mounting holes and R80 mic aperture |
| **PCB Thickness** | 1.6 mm | Finished nominal thickness |
| **Base Material** | FR-4 (TG 150–170) | Standard high-reliability FR-4 |
| **Controlled Stack-up** | **JLC04161H-7628** | Outer copper: 1 oz (35 µm), Inner copper: 0.5 oz (15.2 µm) |
| **Impedance Control** | No requirement | Trace geometries pre-calculated specifically for JLC04161H-7628 |
| **Min Hole Size / Via** | 0.2 mm hole / 0.45 mm pad | 0.2 mm thermal vias used in ESP32-S3 exposed pad |
| **Via Covering** | Plugged (Tented / Solder Mask Plugged) | Ensures solder does not wick into thermal vias |
| **Outer Copper Weight** | 1 oz (35 µm) | Standard outer copper |
| **Inner Copper Weight** | 0.5 oz (15.2 µm) | Standard inner copper for 4-layer 7628 stack-up |
| **Silkscreen** | White | Keep text out of 5 mm mic-port keep-outs |
| **Solder Mask** | Green / Black / Matte Black | L1/L4 mask clearances verified |
| **Surface Finish** | ENIG (Electroless Nickel Immersion Gold) or LeadFree HASL | ENIG strongly recommended for bottom-port MEMS pads |
| **Outline Tolerance** | ±0.2 mm | Standard CNC routing |
| **Electrical Test** | Flying Probe Test | 100% netlist testing |
| **Confirm Production File** | Yes | Customer approval required prior to etching |
| **Remove Order Number** | Yes ("Specify a location" or "Remove mark") | Prevent fab marks inside RF or acoustic areas |

---

## 2. Layer Stack-up (JLC04161H-7628)

| Layer | Type | Material | Thickness | Copper Weight / εr |
|---|---|---|---|---|
| **L1 (F.Cu)** | Top Copper | Copper | 0.035 mm | 1 oz (35 µm) |
| *Dielectric 1-2* | Prepreg | 7628 × 1 | 0.2104 mm | εr ≈ 4.4 |
| **L2 (In1.Cu)** | Inner 1 | Copper | 0.0152 mm | 0.5 oz (15.2 µm) |
| *Core 2-3* | Core | FR-4 Core | 1.0650 mm | εr ≈ 4.6 |
| **L3 (In2.Cu)** | Inner 2 | Copper | 0.0152 mm | 0.5 oz (15.2 µm) |
| *Dielectric 3-4* | Prepreg | 7628 × 1 | 0.2104 mm | εr ≈ 4.4 |
| **L4 (B.Cu)** | Bottom Copper | Copper | 0.035 mm | 1 oz (35 µm) |
| **Total** | | | **~1.60 mm** | |

---

## 3. SMT Assembly Specifications

- **Assembly Type:** Single-sided SMT (Bottom side only, `B.Cu`).
- **Placement Count:** 193 SMD placements.
- **Top Side (`F.Cu`):** Purely acoustic front face; contains no components. Contains 16 × 0.8 mm NPTH acoustic sound entry ports and silkscreen array graphics.
- **Files Location:**
  - Pick & Place CPL: [`assembly/Beamfoarming_16x-all-pos.csv`](file:///h:/My%20Drive/Research_2026/Sound%20Source%20Localizaton/Project/System_Dev/ssl16-acoustic-camera/hardware/fabrication/rev_A/assembly/Beamfoarming_16x-all-pos.csv)
  - JLCPCB BOM: [`assembly/BOM_JLCPCB_Assembly_RevA.xlsx`](file:///h:/My%20Drive/Research_2026/Sound%20Source%20Localizaton/Project/System_Dev/ssl16-acoustic-camera/hardware/fabrication/rev_A/assembly/BOM_JLCPCB_Assembly_RevA.xlsx) and [`assembly/BOM_JLCPCB_Assembly_RevA.csv`](file:///h:/My%20Drive/Research_2026/Sound%20Source%20Localizaton/Project/System_Dev/ssl16-acoustic-camera/hardware/fabrication/rev_A/assembly/BOM_JLCPCB_Assembly_RevA.csv)
  - KiCad native BOM: [`assembly/KiCad_BoM.csv`](file:///h:/My%20Drive/Research_2026/Sound%20Source%20Localizaton/Project/System_Dev/ssl16-acoustic-camera/hardware/fabrication/rev_A/assembly/KiCad_BoM.csv)

---

## 4. Extended & Global-Sourcing Components

| Designator | Value / Part Description | Manufacturer Part Number | JLCPCB LCSC # | Library Type | Notes |
|---|---|---|---|---|---|
| **Y1** | 24.576 MHz 3.3V CMOS XO | ASE-24.576MHZ-LC-T | `C6159263` | Extended / Global Sourcing | Master Clock source for U4 ADC |
| **MK1–MK16** | Analog MEMS Mic (Diff) | IM73A135V01XTSA1 | `C3171831` | Extended | 16 placements; acoustic port alignment critical |
| **U1–U4** | 4-Ch Audio ADC (TDM) | TLV320ADC5140IRTWR | `C2876368` | Extended | QFN-24, thermal pad with 9 vias |
| **U5** | ESP32-S3 MCU Module | ESP32-S3-WROOM-1-N8R8 | `C2913201` | Extended | Octal PSRAM module |
| **U10** | 1:4 Clock Buffer | LMK1C1104PWR | `C1855734` | Extended | TSSOP-8, 12.288 MHz BCLK fan-out |
| **U7** | 5V 3A Buck Converter | XL2596S-5.0E1 | `C74190` | Extended | TO-263-5 power buck |
| **U8** | 3.3V 600mA LDO | AP2112K-3.3TRG1 | `C51118` | Extended | SOT-23-5 digital rail LDO |
| **U9** | Digital Temp Sensor | TMP112AIDRLR | `C28927` | Extended | SOT-563, I2C address 0x48 |
| **U11** | Low-Noise 3.3V LDO | TPS7A2033PDBVR | `C2862740` | Extended | SOT-23-5 analog rail (3V3A) |
| **U6** | ESD Protection Array | USBLC6-2SC6 | `C7519` | Extended | SOT-23-6 USB ESD protection |
| **Q1** | P-Ch MOSFET (-20V 4.5A) | DMP2045U-7 | `C459541` | Extended | SOT-23-3 ideal-diode power switcher |
| **D1** | Schottky Diode (30V 1A) | B5818WS | `C353565` | Extended | SOD-323 power OR-ing |
| **D2** | Schottky Diode (40V 5A) | PMEG4050EP,115 | `C96235` | Extended | SOD-128 buck catch diode (sub for SS54FSH) |
| **D6** | Addressable RGB LED | WS2812B-B/T | `C2761795` | Extended | 5050 RGB LED (+5V rail only) |
| **D601** | Green LED (0402) | LTST-C281TGKT-5A | `C364549` | Extended | 0402 SD card activity LED |
| **FB1** | Ferrite Bead 600R@100MHz| BLM15AG601SN1D | `C76884` | Extended | 0402 analog rail filter |
| **L2** | 47 µH 3A Power Inductor | CYA1040-47UH | `C6364681` | Extended | Shielded inductor for XL2596S |
| **J2** | USB-C 16-Pin Receptacle | USB4105-GF-A-060 | `C3025063` | Extended | Mid-mount USB-C receptacle |
| **J8** | 2.0 mm DC Barrel Jack | DC-005-5A-2.0 | `C381116` | Extended | 12V adapter power jack |
| **J601** | Push-Pull MicroSD Slot | Molex 1040310811 | `C585350` | Extended | 4-bit SDMMC card socket |
| **SW3, SW4** | Tactile Switch (SP15) | PTS526SP15SMTR2 LFS | `C2991193` | Extended | EN and BOOT buttons |
| **C106, C107**| 470 µF 35V Alum Polymer| RVT1V471M1010 (C3350) | `C3350` | Extended | 10×10 mm SMD caps (sub for 330 µF) |
| **R30** | 51 Ω 1% 0402 Resistor | 0402WGF510JTCE | `C25125` | Extended | FSYNC AC end termination |

---

## 5. Critical Assembly & Alignment Remarks

1. **Infineon IM73A135V01XTSA1 Microphone Orientation:**
   - The IM73A135 is a bottom-port LGA-5 package.
   - The JLCPCB component 3D preview model orientation was verified against the KiCad footprint during order setup.
   - **Requirement:** Ensure the acoustic port hole in the microphone package sits squarely and concentric with the 0.8 mm NPTH hole drilled through the PCB. Solder paste must not bridge or contaminate the acoustic sound entry port.
2. **Abracon ASE-24.576MHZ-LC-T Oscillator (Y1):**
   - Pin 1 (Tri-state / OE) must align with the designated dot/chamfered pad on the bottom silkscreen.
3. **ESP32-S3-WROOM-1-N8R8 Module (U5):**
   - Must be aligned with pin 1 index. The PCB has antenna copper keep-out spanning all 4 copper layers directly underneath the PCB trace antenna overhang.
