# SSL-16 Rev A — Board Bring-up & Test Plan

Nov 8, 2026 · @MD ABDUS SHAKUR SIAM

## Before you start

Bring up one board, one phase at a time. Do not start a phase until the one before it passes. The order goes from cheap and safe checks to expensive ones: look, measure resistance, apply current-limited power, then firmware, clocks, ADCs, audio.

**Equipment**

| Item | Used for |
| --- | --- |
| Bench supply with current limit, 0–15 V | First power-up on 12 V (J8) |
| USB-C cable + a USB power meter (or a USB supply with current readout) | First power-up on USB, flashing |
| 12 V / ≥1 A adapter | Normal operation, WS2812 |
| Multimeter (resistance, diode, DC V) | Phases 1–2 |
| Oscilloscope ≥100 MHz, 10× probes with a short ground spring | Clocks, FSYNC, ripple |
| Logic analyser ≥24 MS/s (optional) | I2C, TDM framing |
| Magnifier / microscope, good light | Visual inspection |
| Soldering iron, hot-air, flux, wick | Rework |
| Thermocouple or IR thermometer (or a finger test) | U7, U8, U11 temperature |
| Phone tone-generator app or a small speaker | Acoustic tests |
| microSD card (FAT32) | SD test |

**Rules**

- ESD strap on. The MEMS mics and the ADC inputs are ESD sensitive.
- All parts sit on the bottom side. Rest the board on standoffs or the mounting holes, never on the parts or the mic ports.
- Never blow on, wash or use compressed air into the mic ports. No IPA into the ports.
- First power always goes through a current limit: about 150 mA on USB, about 300 mA on 12 V.
- Never set MICBIAS to AVDD. The mic absolute max is 3.0 V. Keep BIAS\_CFG = 0x00 (≈2.75 V).
- Write down every measurement in the Results log at the end.

**Stop rules — remove power at once and investigate if:**

1. Current jumps to the limit, or rises steadily.
2. Any rail reads more than 5% off its target.
3. Any part becomes too hot to touch within 10 s, or smells.
4. A rail reads 0 V where it should be live.

What each phase proves:

| Phase | Proves |
| --- | --- |
| 0 Visual | Assembly is correct |
| 1 Resistance | No shorts on any rail |
| 2 Power-up | Regulators and power path work |
| 3 ESP32 + I2C | MCU, USB, I2C bus and all 5 I2C devices |
| 4 Clocks | XO, LMK1C1104 buffer, BCLK/FSYNC distribution |
| 5 ADC config | Register script, MICBIAS |
| 6 TDM | Data chain U4→U3→U2→U1→ESP, slot map |
| 7 Acoustic | Mic health, matching, localization |
| 8 Peripherals | SD, LEDs, TMP112, WS2812, buttons, UART |

## Phase 0 — Visual and assembly inspection

Pass = every item below ticked. Compare against the assembly drawing (bottom view, mirrored) and the JLC placement preview. Work under magnification.

**Orientation and pin 1**

- [ ] U1–U4 TLV320ADC5140 (QFN): pin-1 dot matches the silkscreen mark
- [ ] U5 ESP32-S3-WROOM-1: antenna end over the board edge / keep-out, no copper under it
- [ ] U10 LMK1C1104: pin 1 correct
- [ ] Y1 24.576 MHz XO: pin-1 corner correct (wrong rotation = no clock, or VDD on the output)
- [ ] U7 XL2596S, U8 AP2112K, U11 TPS7A2033, U9 TMP112: orientation correct
- [ ] Q1 DMP2045U (P-FET): rotation correct
- [ ] D1 (power-path diode): cathode band towards VSYS
- [ ] D2–D6 LEDs and D601 / USBLC6: polarity correct
- [ ] D5 colour is the one you ordered (white C2290 was flagged; C2287 / C72038 expected)
- [ ] Polarised caps (bulk 470 µF etc.): polarity correct

**Microphones MK1–MK16 (most important)**

- [ ] Each mic sound port sits centred over its 0.8 mm hole — shine a torch through the hole from the other side; you should see light through every port
- [ ] No solder, flux or paste in or around any port
- [ ] All 16 mics flat, no tilt, no tombstoning
- [ ] Mic orientation matches the footprint (the JLC 3D model origin differed from KiCad, so check pin 1 of every mic against the datasheet)

**Solder quality**

- [ ] QFN parts (U1–U4, U10): no bridges along the sides; exposed pad soldered (slight lift = weak thermal / GND)
- [ ] ESP32 module castellations: no bridges, all wetted
- [ ] USB-C connector J2: shield tabs soldered, no bridges on the fine pins (D+/D−, CC)
- [ ] J8 12 V jack and through-hole parts soldered properly
- [ ] No solder balls, no missing parts against the BOM (compare the count: 193 placements)

**Board**

- [ ] No cracks, scratches through copper, or burnt marks
- [ ] Mounting holes clear

Take clear photos of both sides now. They help a lot when debugging later.

## Phase 1 — Unpowered resistance checks

Pass = no rail below about 50 Ω to GND and no two rails shorted to each other. Board unpowered, nothing plugged in. Black probe on TP\_GND1 or TP\_GND2.

On rails with big capacitors, the reading starts low and climbs as the caps charge. Wait 5 s and read the settled value. Then swap the probes and use diode mode as a second check.

| Rail | Test point | Expect to GND | Red flag |
| --- | --- | --- | --- |
| 12 V input (ADAPTER) | 12V1 | kΩ to MΩ | < 100 Ω |
| VBUS | VBUS1 | kΩ (USBLC6 + caps) | < 100 Ω |
| +5V | 5V1 | kΩ (WS2812, regulator output) | < 50 Ω |
| VSYS | (D1 cathode / U8 input) | kΩ | < 50 Ω |
| +3V3 | TP3\_3V3 | hundreds of Ω to kΩ (ESP32, ADC IOVDD) | < 20 Ω |
| 3V3A | 3V3A1 | kΩ (ADC AVDD) | < 50 Ω |
| U1–U4 MICBIAS | U1\_MICBIAS1 … U4\_MICBIAS1 | kΩ (4 mics each) | < 100 Ω |

Also check these pairs. Each must read open or at least kΩ:

- [ ] +3V3 ↔ 3V3A (separate rails; low Ω here means a bridge)
- [ ] +5V ↔ +3V3
- [ ] 12V1 ↔ 5V1
- [ ] VBUS ↔ +5V (Q1 in the path; must not be a dead short)
- [ ] SDA ↔ SCL, and each one to +3V3: about 2.2 kΩ (R17 / R18 pull-ups)
- [ ] TP\_SHDN1 to GND: about 100 kΩ (R31)
- [ ] TP2\_EN1 and TP2\_BOOT1 to +3V3: the pull-up value (≈10 kΩ)

If a rail is shorted, do not power it. Find it by injecting about 100 mA at 0.5 V from the bench supply into the rail and feeling for the warm part, or with a thermal camera.

## Phase 2 — First power-up

Pass = all rails within ±3% on both USB and 12 V, idle current under about 150 mA, and no hot parts. Power from USB first: it skips the buck (U7) and is the lower-risk path. Then test 12 V alone, then both together.

**Step 2a — USB only (J8 unplugged)**

1. Use a current-limited USB source, or a USB meter on a laptop port. Watch the current as you plug in.
2. Expect under about 100 mA. A blank or fresh ESP32 and the ADCs in shutdown (SHDNZ low) draw little.
3. Measure:

| Point | Expect | Note |
| --- | --- | --- |
| VBUS1 | 4.8–5.2 V | From the host |
| 5V1 (+5V) | ≈ 0 V (under 1 V) | Buck is off; WS2812 is unpowered |
| VSYS | ≈ VBUS minus a small drop (≈4.8–4.9 V) | Through Q1 (P-FET on, gate pulled low by R5) |
| TP3\_3V3 (+3V3, U8) | 3.25–3.35 V | AP2112K |
| 3V3A1 (3V3A, U11) | 3.25–3.35 V | TPS7A2033, from VSYS |

4. After 1 minute, touch-test U8, U11 and the ESP32. Warm is fine; too hot to hold is not.

**Step 2b — 12 V only (USB unplugged)**

1. Bench supply at 12.0 V, current limit 300 mA. Connect to J8. Check the polarity of the plug first.
2. Expect the input current to be well under 100 mA at 12 V (the buck converts down).
3. Measure:

| Point | Expect | Note |
| --- | --- | --- |
| 12V1 | 12.0 V | Input |
| 5V1 (+5V) | 4.9–5.1 V | XL2596S output |
| VSYS | ≈ +5V minus the D1 drop (≈4.6–4.8 V) | Q1 must now be off |
| TP3\_3V3 | 3.25–3.35 V |  |
| 3V3A1 | 3.25–3.35 V |  |
| VBUS1 | ≈ 0 V | Must NOT be back-fed. If you see ≈5 V here, Q1 or D1 is wrong and could push current into a PC |

4. Scope +5V with a short ground spring: ripple should be under about 50 mV p-p. Scope 3V3A: under about 10 mV p-p.
5. After 2 minutes, check the temperature of U7 (inductor and IC), U8 and U11.

**Step 2c — Both connected**

1. 12 V on, then plug USB in. Then unplug 12 V with USB still in.
2. The rails must stay up and the ESP32 must not reset during the switch-over. (A brief dip is OK if no reset happens. Check it on the scope with a trigger on +3V3.)

**Step 2d — ADC rails with SHDNZ forced high (optional but useful)**

Tie TP\_SHDN1 to +3V3 through a 1 kΩ resistor for a few seconds. The four ADCs come out of shutdown. The current should rise only by a few mA (they still need register writes to start). Remove the jumper after.

## Phase 3 — ESP32 flashing and I2C scan

Pass = a sketch uploads over USB, the serial monitor prints, and the I2C scan finds exactly 0x48, 0x4C, 0x4D, 0x4E and 0x4F.

**Step 3a — Enumerate and flash**

1. Plug in USB. The PC should show a USB JTAG/serial debug unit (Espressif VID 303A). If not, enter download mode: hold BOOT (SW4), tap EN (SW3), release BOOT.
2. Arduino IDE settings: board ESP32S3 Dev Module, USB CDC On Boot = Enabled, PSRAM = OPI PSRAM, Flash size = 8 MB, USB Mode = Hardware CDC and JTAG.
3. Upload a blink sketch on IO48 (status LED). Pass = LED blinks and Serial prints.
4. Print `ESP.getPsramSize()`. Expect about 8 MB. If 0, the PSRAM setting is wrong.
5. Do not use IO35–IO37 for anything; the N8R8 PSRAM uses them.

**Step 3b — I2C scan**

The ADCs answer on I2C only when SHDNZ (IO11) is high. Drive it high first and wait 10 ms. Start at 100 kHz because the bus is about 480 mm long.

```cpp
#include <Wire.h>
void setup() {
  Serial.begin(115200); delay(1500);
  pinMode(11, OUTPUT); digitalWrite(11, HIGH); delay(10);  // SHDNZ high
  Wire.begin(8, 9, 100000);                                 // SDA IO8, SCL IO9
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) Serial.printf("found 0x%02X\n", a);
  }
}
void loop() {}
```

| Address | Device | If missing |
| --- | --- | --- |
| 0x48 | U9 TMP112 | Check U9 solder and ADD0 strap |
| 0x4C | U1 ADC | Check U1 ADDR straps, SHDNZ at the pin, AVDD/IOVDD at U1 |
| 0x4D | U2 ADC | Same, at U2 |
| 0x4E | U3 ADC | Same, at U3 |
| 0x4F | U4 ADC | Same, at U4 |

If nothing is found: scope SDA and SCL. Both must idle at 3.3 V. Rise time should be under 1 µs at 100 kHz with 2.2 kΩ. If all five appear, repeat at 400 kHz and note whether it still works.

Quick register sanity read: read register 0x00 (PAGE\_CFG) on each ADC. It should return 0x00.

## Phase 4 — Clock checks

Pass = MCLK 24.576 MHz at power-on; after U4 is configured, BCLK 12.288 MHz on all five BCLK nets and FSYNC 48 kHz, with clean, single-crossing edges at the far ends.

Use a 10× probe with the short ground spring at the test point's nearest GND. A long ground clip adds fake ringing at 12 MHz.

**Step 4a — MCLK (no configuration needed)**

Y1 runs as soon as +3V3 is up. Probe MCLK1 (at U4 GPIO1, after R22 33 Ω).

- Expect 24.576 MHz, 0 to 3.3 V, duty cycle about 50%.
- Frequency error under ±50 ppm (±1.2 kHz). A scope counter is fine for this.
- No MCLK: check Y1 rotation, its supply and its enable pin.

**Step 4b — BCLK and FSYNC (after U4 registers are written)**

U4 is the TDM controller; nothing toggles until it is configured. Run the register script in Phase 5 (U4 lines at minimum), then probe:

| Test point | Net path | Expect |
| --- | --- | --- |
| BCLK\_SRC1 | U4 BCLK → R27 → LMK CLKIN | 12.288 MHz |
| BCLK\_Y0 | LMK Y0 → R13 → U1 | 12.288 MHz |
| BCLK\_Y1 | LMK Y1 → R14 → U2 | 12.288 MHz |
| BCLK\_Y2 | LMK Y2 → R15 → U3 | 12.288 MHz |
| BCLK\_Y3 | LMK Y3 → R16 → ESP IO6 | 12.288 MHz |
| FSYNC1 | U4 → R28 → U3, U2, U1 → IO7 | 48.000 kHz, pulse 1 BCLK wide (TDM) |

For each, check:

- [ ] Frequency correct
- [ ] Overshoot / undershoot under about 0.5 V beyond the rails
- [ ] Edges are monotonic through the 0.8–2.0 V region (no step or double crossing — a double crossing gives double clocking)
- [ ] FSYNC at the IO7 end (after R30 51 Ω + C54 100 pF) is clean; the trace is about 375 mm long, so this is the worst case
- [ ] Skew between BCLK\_Y0 and BCLK\_Y3: a few ns at most

If BCLK\_SRC is present but a Y output is missing, check U10 supply, OE pin and solder. If BCLK\_SRC itself is missing, U4 is not in controller mode: re-read registers 0x13, 0x14, 0x16 and 0x21 on 0x4F.

## Phase 5 — ADC configuration and MICBIAS

Pass = every register reads back as written, all four ADCs report active, the targets detect 48 kHz / 256, and MICBIAS is 2.75 V (±5%) on all four test points.

The values below are from the design notes. Check each one against the TLV320ADC5140 datasheet register map before the first write, and fix the table here if you change anything.

**Step 5a — Wake-up (all four ADCs)**

1. SHDNZ (IO11) high, wait 10 ms.
2. Write 0x02 SLEEP\_CFG = 0x81 (wake, internal AREG). Wait 1 ms.

**Step 5b — Register script**

| Reg | Name | U1 (0x4C) | U2 (0x4D) | U3 (0x4E) | U4 (0x4F) |
| --- | --- | --- | --- | --- | --- |
| 0x07 | ASI\_CFG0 (TDM, 16-bit) | 0x01 | 0x01 | 0x01 | 0x01 |
| 0x08 | ASI\_CFG1 | 0xA1 | 0x81 | 0x81 | 0x81 |
| 0x09 | ASI\_CFG2 (daisy) | 0x80 | 0x80 | 0x80 | — |
| 0x13 | MST\_CFG0 | 0x00 (target) | 0x00 | 0x00 | 0xA0 (controller) |
| 0x14 | MST\_CFG1 (48 kHz, BCLK = 256 fs) | — | — | — | 0x48 |
| 0x16 | CLK\_SRC | — | — | — | 0xD8 |
| 0x21 | GPIO1\_CFG | 0xB0 (daisy in) | 0xB0 | 0xB0 | 0xA0 (MCLK in) |
| 0x3B | BIAS\_CFG (MICBIAS ≈ 2.75 V) | 0x00 | 0x00 | 0x00 | 0x00 |
| 0x3C / 0x41 / 0x46 / 0x4B | CH1–CH4 CH\_CFG0 | 0x04 | 0x04 | 0x04 | 0x04 |
| 0x74 | IN\_CH\_EN (CH1–4) | 0xF0 | 0xF0 | 0xF0 | 0xF0 |

**Step 5c — Power-up (write last)**

1. U4: 0x75 PWR\_CFG = 0xC0 (MICBIAS + ADC on). Clocks start now — Phase 4b checks happen here.
2. U1, U2, U3: 0x75 = 0xE0.
3. Wait 10 ms.

**Step 5d — Read back**

- [ ] Every register in 5b reads back as written (print a table over serial)
- [ ] 0x15 ASI\_STS on U1–U3 = 0x48 (target sees 48 kHz and 256 ratio). Any other value means BCLK or FSYNC is wrong at that device
- [ ] 0x76 DEV\_STS0 = 0xF0 (4 channels powered) on all four
- [ ] 0x77 DEV\_STS1 shows active mode on all four

**Step 5e — MICBIAS**

| Test point | Expect | Measured |
| --- | --- | --- |
| U1\_MICBIAS1 | 2.61–2.89 V |  |
| U2\_MICBIAS1 | 2.61–2.89 V |  |
| U3\_MICBIAS1 | 2.61–2.89 V |  |
| U4\_MICBIAS1 | 2.61–2.89 V |  |

Anything near 3.3 V: power down at once — BIAS\_CFG is wrong and the mics are at risk (absolute max 3.0 V). Also measure the total supply current now; each mic draws a few hundred µA, so 16 mics add only a few mA.

## Phase 6 — TDM capture and channel mapping

Pass = the ESP32 receives 16 live slots at 48 kHz without errors, and a tap test on each mic moves only its expected slot.

**Step 6a — Probe the data chain**

With all ADCs active, each data net should show bursts every FSYNC period. The burst gets longer at each hop because each device adds its 4 slots (64 bits).

| Test point | From → to | Carries slots |
| --- | --- | --- |
| SD4 | U4 → U3 | U4 only (4 slots) |
| SD3 | U3 → U2 | U3 + U4 (8 slots) |
| SD2 | U2 → U1 | U2 + U3 + U4 (12 slots) |
| I2S\_DIN1 | U1 → ESP IO13 | all 16 slots (256 bits = full frame) |

A logic analyser decoding TDM (BCLK, FSYNC, data) makes this easy. If a hop shows nothing, check that device's 0x09 / 0x21 daisy settings and GPIO1 solder.

**Step 6b — ESP32 I2S in TDM target mode**

Settings: I2S target (slave), TDM Philips/DSP format to match FSYNC, 16 slots × 16 bit, BCLK = IO6, WS = IO7, DIN = IO13, sample rate 48 kHz.

- If the data looks shifted by one bit or noisy, invert BCLK (`bclk_inv`) or change the FSYNC format (short pulse vs. 50% duty).
- ESP32-S3 target mode needs an internal clock at least 8× BCLK (bclk\_div ≥ 8). If 12.288 MHz BCLK fails, fall back to fs = 24 kHz (BCLK 6.144 MHz): set U4 0x14 to the 24 kHz code.
- Stream raw frames over USB CDC to a PC script, or print per-slot RMS once a second.

**Step 6c — Slot map (tap test)**

In a quiet room, gently scratch a fingertip next to one mic port at a time (do not touch the port). The slot whose RMS jumps 20 dB or more is that mic. Tick each one:

| Slot | Expected mic | ADC / input | OK |
| --- | --- | --- | --- |
| 0 | MK2 | U1 IN1 |  |
| 1 | MK7 | U1 IN2 |  |
| 2 | MK10 | U1 IN3 |  |
| 3 | MK15 | U1 IN4 |  |
| 4 | MK1 | U2 IN1 |  |
| 5 | MK4 | U2 IN2 |  |
| 6 | MK9 | U2 IN3 |  |
| 7 | MK12 | U2 IN4 |  |
| 8 | MK3 | U3 IN1 |  |
| 9 | MK6 | U3 IN2 |  |
| 10 | MK11 | U3 IN3 |  |
| 11 | MK14 | U3 IN4 |  |
| 12 | MK5 | U4 IN1 |  |
| 13 | MK8 | U4 IN2 |  |
| 14 | MK13 | U4 IN3 |  |
| 15 | MK16 | U4 IN4 |  |

If the map differs, fix the lookup table in firmware rather than the board. Record the real map here; the beamformer needs it matched to the rev C1 coordinates (revC1.csv).

Also check: a dead slot that reads a constant (0 or full scale) points to a bad mic solder joint, a missing 1 µF coupling cap, or an OUT− / INxN open.

## Phase 7 — Acoustic tests

Pass = all 16 channels have a similar noise floor, gains within ±1 dB after calibration, and a known source is located within a few degrees across the 1.5–6 kHz horn band.

Record 10 s WAV files (16 channels, 48 kHz) over USB for every test. Do the analysis on a PC (Python / numpy). Keep the board still and note its orientation for every recording.

**Step 7a — Noise floor (quiet room)**

1. Record 10 s with no source.
2. Per channel, compute the RMS in dBFS and an FFT.
3. Expect all 16 within about 3 dB of each other. One channel much higher = a bad joint or a noisy mic. Spurs at 12.288 MHz aliases, 48 kHz harmonics or the buck switching frequency point to coupling from clocks or U7.
4. Repeat on 12 V power and compare with USB power. A big rise on 12 V means the buck noise reaches 3V3A or MICBIAS.

**Step 7b — Gain matching**

1. Place a small speaker about 1 m away, on axis (broadside) to the array, playing a 1 kHz tone at moderate level.
2. Per channel, measure the tone level in dB.
3. Compute the correction for each channel against the mean. Store it in firmware.
4. Pass: every channel within ±1 dB after correction. A channel off by more than 3 dB before correction needs a closer look (blocked port, solder in the hole).

**Step 7c — Phase / delay matching**

1. Same set-up, source far away and broadside, so all mics see the same phase.
2. Play a sweep or tones at 1.5, 3 and 6 kHz.
3. Cross-correlate each channel with a reference channel. The lag should be about 0 samples.
4. Store any residual phase per channel. Any channel near 180° out has its OUT+ / OUT− pair swapped or its sign is flipped in firmware.

**Step 7d — Localization test**

1. Mark angles on the floor around the board (for example −60°, −30°, 0°, +30°, +60°) at 2–3 m.
2. Play a recorded car-horn sound (or a 2–4 kHz tone burst) from each mark.
3. Run the beamformer (delay-and-sum or SRP-PHAT) with the rev C1 mic coordinates and the slot map from Phase 6.
4. Record the estimated angle against the true angle in the Results log.
5. Repeat with a second source playing, and outdoors, if time allows.

Mirror-image errors (left/right swapped) usually mean the coordinate frame is flipped — the mics are on the bottom side, so the view from the sound side is mirrored relative to the KiCad top view.

## Phase 8 — Peripherals

Pass = every item below ticked. These can run in any order once Phase 3 passes. They do not depend on the audio path.

| Peripheral | Pins / address | Test | Pass |
| --- | --- | --- | --- |
| microSD (SD\_MMC, 4-bit) | CLK IO5, CMD IO4, D0 IO18, D1 IO16, D2 IO15, D3 IO21 | `SD_MMC.setPins(5, 4, 18, 16, 15, 21)`, mount, write a 1 MB file, read it back, compare | Data matches; note the write speed |
| SD card detect | IO14 | Read IO14 with card in and out | Level changes |
| Status LED | IO48 | Blink (done in Phase 3) | Blinks |
| Power LEDs (D2–D5) | Rails | Look on USB, then on 12 V | Each lights on its rail; D5 colour as ordered |
| TMP112 (U9) | I2C 0x48 | Read register 0x00, temperature = (raw >> 4) × 0.0625 °C | Reads room temperature ±2 °C; rises when you warm it with a finger |
| WS2812 (D6) | Its data GPIO (see schematic) | Set red, green, blue, white in turn | **12 V adapter only** — it runs on +5V, which is off on USB power |
| EN button (SW3) | EN | Press | ESP32 resets, serial reconnects |
| BOOT button (SW4) | IO0 | Hold BOOT, tap EN | Enters download mode |
| UART header (J3) | ESP UART0 | USB-UART adapter (3.3 V levels), 115200 baud | Boot log appears |
| USB ESD (D601 / USBLC6) | D+, D− | Plug / unplug 20 times | Re-enumerates every time |

For the WS2812 at full white, each LED pulls up to about 60 mA from +5V. Check that +5V stays above 4.8 V.

## Troubleshooting

Look up the symptom first, then check the likely causes in the order given.

| Symptom | Likely cause | Check / fix |
| --- | --- | --- |
| Current hits the limit at power-on | Short on a rail; reversed part | Phase 1 again; check D1, Q1, polarised caps, U8 / U11 rotation |
| +3V3 OK on USB, nothing on 12 V | U7 buck dead or wrong; J8 polarity | Check 12V1 at U7 input, U7 enable pin, inductor solder |
| VBUS1 shows ≈5 V with only 12 V connected | Q1 wrong or reversed (back-feed) | Stop. Check Q1 orientation and R5 |
| AP2112 (U8) hot | High 3V3 load or a short downstream | Measure 3V3 current; ESP32 + Wi-Fi peaks can reach 300–500 mA |
| PC does not see USB | D+/D− swapped, USBLC6 wrong, CC resistors missing | Check J2 solder, the D601 pin 1-6 / 3-4 mapping, 5.1 kΩ on CC1/CC2 |
| Upload fails | Not in download mode | Hold BOOT, tap EN; use USB CDC On Boot = Enabled |
| ESP32 boot-loops | Brown-out, PSRAM setting | Scope +3V3 during boot; set OPI PSRAM |
| I2C finds nothing | SHDNZ low (ADCs), bus stuck | IO11 high first; SDA/SCL idle at 3.3 V; R17/R18 present |
| I2C finds some ADCs, not all | Address strap or solder on that ADC | Check ADDR pins and QFN joints of the missing one |
| I2C errors at 400 kHz | Long bus (≈480 mm) | Stay at 100 kHz |
| No MCLK | Y1 rotation, Y1 supply | Pin 1 of Y1; 3.3 V on its VDD |
| No BCLK / FSYNC | U4 not in controller mode | Re-read U4 0x13, 0x14, 0x16, 0x21, 0x75 |
| BCLK on BCLK\_SRC, not on a Y output | U10 supply, OE, solder | Check U10 pins |
| ASI\_STS (0x15) wrong on a target | Bad BCLK / FSYNC at that ADC | Scope at that ADC; ringing or double edges |
| Frame data shifted or garbled | BCLK edge or FSYNC format | Try `bclk_inv`; short pulse vs 50% FSYNC; fall back to 24 kHz |
| Some 4-slot group missing | Daisy chain break | Probe SD2 / SD3 / SD4; 0x09 and 0x21 on that ADC |
| One slot dead or constant | Mic, coupling cap or input pin | Re-flow the mic; check 1 µF cap; MICBIAS at that ADC |
| One channel noisy | Solder in port, damaged mic | Inspect port; swap test |
| Channel 180° out | OUT+ / OUT− swapped | Flip the sign in firmware |
| MICBIAS ≈ 3.3 V | BIAS\_CFG wrong | Power down now; set 0x3B = 0x00 |
| Tones at the buck frequency in audio | U7 noise on 3V3A / MICBIAS | Compare USB vs 12 V; add filtering on the next rev |
| Localization mirrored | Coordinate frame flipped (mics on bottom) | Mirror x in the beamformer |
| SD mount fails | Pin map, card format | `setPins` order; FAT32; try 1-bit mode |
| WS2812 dark | On USB only | Use 12 V; check its data pin |

## Results log

Fill in one column per board (two boards were assembled). Write the measured value, not just pass/fail.

| Check | Target | Board 1 | Board 2 |
| --- | --- | --- | --- |
| Phase 0 visual | All ticked |  |  |
| R +5V to GND | > 50 Ω |  |  |
| R VSYS to GND | > 50 Ω |  |  |
| R +3V3 to GND | > 20 Ω |  |  |
| R 3V3A to GND | > 50 Ω |  |  |
| USB idle current | < 100 mA |  |  |
| VSYS (USB) | ≈ 4.8–4.9 V |  |  |
| +3V3 (USB) | 3.25–3.35 V |  |  |
| 3V3A (USB) | 3.25–3.35 V |  |  |
| 12 V input current | < 100 mA |  |  |
| +5V (12 V) | 4.9–5.1 V |  |  |
| VBUS1 with 12 V only | ≈ 0 V |  |  |
| +5V ripple | < 50 mV p-p |  |  |
| U7 / U8 / U11 temperature after 2 min | Warm, not hot |  |  |
| USB enumerates, sketch uploads | Yes |  |  |
| PSRAM size | ≈ 8 MB |  |  |
| I2C scan | 0x48, 0x4C–0x4F |  |  |
| MCLK | 24.576 MHz |  |  |
| BCLK\_SRC / Y0 / Y1 / Y2 / Y3 | 12.288 MHz |  |  |
| FSYNC | 48 kHz |  |  |
| ASI\_STS U1 / U2 / U3 | 0x48 |  |  |
| MICBIAS U1 / U2 / U3 / U4 | 2.61–2.89 V |  |  |
| 16 slots live | Yes |  |  |
| Slot map matches Phase 6 table | Yes / note changes |  |  |
| Noise floor spread | < 3 dB |  |  |
| Gain spread before correction | Note |  |  |
| Localization error at 0° / ±30° / ±60° | Note degrees |  |  |
| SD read/write | Pass |  |  |
| TMP112 reading | Room ±2 °C |  |  |
| WS2812 (12 V) | All colours |  |  |
| Buttons, UART J3 | Pass |  |  |

Issues found and fixes for the next revision:

- [ ] (add here)
