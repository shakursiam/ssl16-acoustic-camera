# SSL-16 Lab Guide (English): Step-by-Step Experiments E0 to E8

This guide is for use at the bench. It tells you what to do, in what order, and when to stop. The longer explanations, the full chord table and the uncertainty budget are in [test_campaign_plan.md](test_campaign_plan.md). The Bangla version of this guide is [lab_guide_bn.md](lab_guide_bn.md).

**Deadline:** the lab is available until 22 November. If time runs short, do the experiments in this order: E0 → E1 → E6 → E3 → E4 → E2 → E5 → E8 → E7.

**Three rules you must never break**

1. Never edit, rename or delete a WAV, JSON or `runs.csv` file. If a run is bad, press **Flag last bad** in the GUI, write the reason, and measure again.
2. No E1–E8 data is valid on a given day until E0.5 (the orientation check) has passed that day.
3. At the end of each day, copy the whole session folder and the SD card files to two places (Google Drive and one more backup).

---

## 0. What each file is for

| File | Purpose |
|---|---|
| `firmware/arduino/SSL16_SelfTest` | Checks the board (I2C, ADCs, TDM). Already passed on board 1. |
| `firmware/arduino/SSL16_SDTest` | Measures the SD card speed. **Not run yet.** |
| `firmware/arduino/SSL16_WavRecorder_v45` | Your working recorder (12 kHz). Kept as a backup, not changed. |
| `firmware/arduino/SSL16_Rec48` | **New.** Raw 48 kHz to the SD card, 12 kHz over USB as before. **Not compiled or run on the board yet**; check it with the Day 0 steps below. |
| `software/python/ssl16_recorder_gui.py` | Simple recorder GUI. Shows a level bar for each of the 16 microphones. Used for the tap test. |
| `software/python/ssl16_buzzer_gui.py` | The main campaign logger. Pressing **Measure** saves a 12 kHz WAV and metadata on the PC, and tells the board to write a 48 kHz file with the same name to the SD card. |
| `software/python/ssl16_analyze.py` | The evening analysis. |

**Why there are two audio files per run:** USB (full speed) cannot carry 16 channels at 48 kHz (1.54 MB/s), so USB carries 12 kHz. Raw 48 kHz can only be written to the SD card. The 48 kHz SD file is the data for the paper. The 12 kHz PC file is for the live view and as a backup.

---

## 1. Day 0: preparation (before going to the lab, about 2 hours)

### 1.1 Software

Open PowerShell and run:

```powershell
cd "G:\My Drive\Research_2026\SSL-16 Journal\ssl16-acoustic-camera"
git checkout feat/test-campaign-handoff
& "C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe" -m pip install -r software\python\requirements.txt
```

Arduino IDE settings (the same for every sketch): Board = *ESP32S3 Dev Module*, *USB CDC On Boot = Enabled*, *USB Mode = Hardware CDC and JTAG*, *PSRAM = OPI PSRAM*, *Flash Size = 8MB*.

If an upload fails with "No serial data received": **hold BOOT → tap EN once → release BOOT**, upload, then press EN. Close the Arduino Serial Monitor before you start any Python program.

### 1.2 SD card test (required)

1. Format the card as FAT32 and put it in the board.
2. Upload `SSL16_SDTest` and open the Serial Monitor.
3. Write down the **write speed**.
   - **Above 1.6 MB/s:** 48 kHz recording will work.
   - Below that: try another card (Class 10 / U1 or better). If no card is fast enough, tell me the number. The campaign will then use the 12 kHz recorder, and the paper will say so.

### 1.3 Check the new firmware `SSL16_Rec48`

1. Open `firmware/arduino/SSL16_Rec48/SSL16_Rec48.ino` and press **Verify**.
   - **If there is a compile error, do not upload.** Send me the full error text. You can keep working with `SSL16_WavRecorder_v45` in the meantime.
2. If it compiles, upload it and press EN. A blinking green LED means it is streaming.
3. Start the recorder GUI:
   ```powershell
   cd software\python
   & "C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe" ssl16_recorder_gui.py
   ```
   Connect to COM19. Check that the 16 bars move and that the status shows `sd=ok`.
4. Record a **30-second** test run (name it `test48`), then stop it. A blinking red LED means it is recording.
5. Look at three numbers in the status line. All three must stay at **0**: `ring_drop`, `sd_err`, `i2s_ovf`.
6. Take the card out and copy `/ssl16/test48.wav`, `test48.txt` and `test48_temp.csv` to the PC. `test48.txt` should contain `fs_hz=48000`, `samples_per_channel` close to 1,440,000 (30 seconds), `ring_dropped_blocks=0` and `i2s_overflows_during_run=0`.
7. **Give me these three files** (put them in a `day0_test/` folder inside the Journal folder). I will check the channels, the sample count, clipping and the channel order. Do not start real measurements until this check passes.

If `ring_drop` is not zero, the card is too slow. If `i2s_ovf` is not zero, there is a firmware problem; tell me.

### 1.4 Tap test (checks the slot map; not done yet)

Purpose: confirm that each microphone really arrives on its own channel. Claim C1 of the paper depends on this.

1. Keep the recorder GUI open (the bars are in the order M1…M16). Keep the room quiet.
2. On the sound-hole side of the board, scratch lightly with a fingernail or pen tip right next to the M1 hole. Do not cover the hole and do not put anything into it.
3. The M1 bar should jump the most. Nearby microphones may move a little, but M1 must be the highest.
4. Repeat for M2 to M16. Write on paper: "scratched Mn → highest bar Mk".
5. Record one run during the whole test (name it `taptest`) and say each number aloud ("M one", "M two", …) so it can be checked later from the file.

**Pass:** n = k for all 16. If any one does not match, stop and send me the table. If the microphone table is wrong, every angle will be wrong.

To find each microphone on the board, use the table in [microphone_array.md](microphone_array.md) (M1 is near the centre; M16 is the outermost one, towards the bottom).

### 1.5 Equipment

2 boards, laptop and USB-C cable, 2 tripods, a board mounting plate (must not cover any sound hole), 3 buzzers (about 2.3, 2.8 and 4 kHz), 2 small speakers, sound level meter (SLM), laser distance meter, 5 m steel tape, masking tape, chalk line, plumb bob, inclinometer, thermometer/hygrometer, power bank, a tested SD card and card reader, phone camera.

---

## 2. Building Setup A (camera mode, board vertical)

1. Choose the clearest area in the lab: at least 3 m in front of the board, and 1 m from the walls on both sides.
2. Mount the board on a tripod. **The board centre is 1.20 m above the floor.** Use the inclinometer to make the face vertical (±0.5°) and the x-axis level.
3. Hang the plumb bob from the board centre and mark point **O** on the floor.
4. Snap a chalk line from O, square to the board face. This is the 0° line. Mark point **R** on it, **2.00 m** from O.
5. Each angle point P is 2.00 m from O **and** at chord distance c = 2r·sin(θ/2) from R. For r = 2.0 m:

   | θ | 10° | 20° | 30° | 40° | 50° | 60° | 70° | 80° | 90° |
   |---|---|---|---|---|---|---|---|---|---|
   | chord (cm) | 34.9 | 69.5 | 103.5 | 136.8 | 169.0 | 200.0 | 229.4 | 257.1 | 282.8 |

   The same values apply on both sides of the line. Put masking tape on each point and write its ID (for example `P+30`, `P-30`).
6. Put the source (buzzer) on the second tripod at 1.20 m, with its sound hole facing the board centre.
7. **Take photos:** the whole bench with the tape marks visible, and the board mount. These are needed for Fig. 4 of the paper.

**Which side is +θ:** the points on the board's +x side are +θ. Which physical side is +x will be confirmed with sound in E0.5. Do not assume it beforehand.

---

## 3. Running the campaign GUI (the same for every experiment)

```powershell
cd "G:\My Drive\Research_2026\SSL-16 Journal\ssl16-acoustic-camera\software\python"
& "C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe" ssl16_buzzer_gui.py
```

1. **Session dialog:** set the base folder to `G:\My Drive\Research_2026\SSL-16 Journal\ssl16_campaign` (outside the repo, so audio does not go into git). Fill in room, board (`board1`), operator, humidity, background dB(A) and firmware (`SSL16_Rec48`).
2. **Connect** → COM19. You should see green text like `SSL6 12000 Hz | packets … | gaps 0`.
3. **Settings:** enter the thermometer reading as the temperature. Set flip x / flip y only during E0.5, and never change them afterwards.
4. For each point: enter setup (A/B), range, angle, source height and board height → enter the experiment ID, point ID and source name → switch the source on and wait 2 seconds → press **Measure**. Do this 3 times at the same point (the repetition number counts up by itself).
5. If a warning appears after Measure, read it:
   - "detections only …%" or "spread …°": measure the point once more.
   - "USB gaps": check the USB cable and port.
   - **"board did NOT confirm the SD recording"**, **"SD too slow"** or **"I2S overflow"**: the 48 kHz file of this run cannot be trusted. Press **Flag last bad**, fix the cause, and measure again.
6. While measuring: nobody talks or walks. The operator stays behind the board, at least 1 m back. Doors closed and fans off (if a fan cannot be switched off, write that in the notes).
7. **After every 10 points**, measure the control point (θ = 0°) again. If it has moved more than 1° from its value at the start of the day, stop and find out what moved.
8. Do not measure the points in left-to-right order. Use **Shuffle order** and measure them in the shuffled order.

**At the end of the day:**

1. Close the GUI (stop any recording first). Before removing power from the board, make sure the LED is not blinking red.
2. Copy every file in the SD card's `/ssl16/` folder into a folder named `sd_raw\` inside the session folder. **Do not rename anything.** Do not erase the card until you have checked the copy.
3. Back up the whole session folder to a second place.
4. Tell me "today's session is copied". I will run the integrity check and the coverage table and tell you which points need to be redone.

---

## 4. E0: calibration and characterization (start of every day, Setup A)

About 1.5 hours on the first day. On later days do only E0.1, E0.2 and E0.5 (about 20 minutes). In the GUI, set experiment = `E0` and use the point IDs below.

| Step | Point ID | What to do | Pass / note |
|---|---|---|---|
| E0.1 Environment | `ENV` | Write the temperature, humidity and background dB(A) into the session. Pop a balloon (or clap loudly) 2 m from the board and Measure for 10 seconds. | The room's RT60 is computed from this recording. |
| E0.2 Noise floor | `NOISE` | All sources off, room silent, Measure for **30 seconds**. | Earlier result: all channels between −72 and −78 dBFS. |
| E0.3 Channel calibration | `CAL_1000` … `CAL_5000` | Speaker at θ = 0°, height 1.20 m, r = 2 m. Play tones from 1000 to 5000 Hz in 500 Hz steps and Measure each for 3 seconds. | No clipping. Keep the level bars between −20 and −40 dBFS. |
| E0.4 Sources | `SRC_<name>` | Each buzzer 0.3 m from the board, Measure for 5 seconds. Measure the SPL at 1 m with the SLM and write it in the notes. | Gives the real frequency of each buzzer. |
| **E0.5 Orientation** | `ORI_T45`, `ORI_P30` | (a) Source at the θ = +45° point, height 1.20 m. (b) Source at θ = 0°, r = 1.5 m, height 2.07 m (φ ≈ +30°). | See below. |
| E0.6 Boresight | `BORE` | Source at θ = 0°, 3 × 10 seconds. | If the mean θ is outside ±1°, turn the board to fix it. Do not correct it in software. |
| E0.7 Real-time | `RT10` | Source on, 10 minutes continuous. Write down the GUI's packet and gap counts at the start and at the end. | First day only. |

**How to pass E0.5 (not done yet, so it is the most important step on the first day):**

1. Put the source at the +45° point. Look at θ in the GUI's estimate.
   - About **+45°**: correct.
   - About **−45°**: toggle **flip x** in Settings and measure again.
2. Put the source high (φ ≈ +30°). Look at φ in the GUI.
   - **Positive**: correct. If it is negative, toggle **flip y** and measure again.
3. When both are correct, write the final flip x / flip y / rot values in the session notes. **Do not change them again for the whole campaign.**
4. If θ or φ is far from 45° / 30° (for example, wrong by more than 20°) and the flips do not fix it: stop, and give me the tap-test result and these two runs.

**Extra work for analysis A2 (must be done before the lab closes):**

- Put a reference thermometer next to the board. Write down its reading and the `temp` value from the GUI/status at the same moment, at least twice a day.
- Measure 5 points of E1 (θ = 0, ±30, ±60°) at two clearly different room temperatures (for example about 22 °C with the AC on, and about 30 °C with the AC off). Use experiment ID `A2`.
- Write down the humidity each time. Humidity also changes the speed of sound slightly.

---

## 5. E1: bearing sweep (the main result, Setup A, about 2 hours)

- **Fixed:** r = 2.0 m, source height 1.20 m (φ = 0°), 2.8 kHz buzzer.
- **Varies:** θ from −90° to +90° in 10° steps (19 points). Point IDs: `P-90` … `P+90`.
- **Extra:** the other two buzzers at θ = 0, ±30, ±60, ±90° (7 × 2 = 14 points). Give each buzzer its own source name.
- Each point 3 × 5 seconds, in shuffled order, with the control point after every 10 points.

**Done when:** 33 points × 3 = 99 runs are saved and none of them has an SD warning.

---

## 6. E6: SNR (Setup A, about 1 hour)

- **Source:** 2.8 kHz buzzer at θ = +30°, r = 2 m.
- **Noise:** pink noise from the second speaker at θ = −45°, r = 2 m.
- **Steps:**
  1. Source only, Measure 10 seconds (point `SRC_ONLY`).
  2. Noise only, 10 seconds at each noise level (points `N_ONLY_L1`, …). The real in-band SNR is computed from these.
  3. Both together. Raise the noise volume to give SNR of roughly +30, +20, +10, +5, 0 and −5 dB. Each level 3 × 10 seconds (points `SNR+30`, …).
- Write the SLM reading in the notes at every level. Mark the positions of the speaker's volume knob, so the `N_ONLY` runs and the mixed runs use the same level.

---

## 7. E3: 360° sweep (Setup B, board lying flat, about 2 hours)

1. Put the board face up on a stand, raised on standoffs, at a **height of 1.00 m**. Level it with the inclinometer.
2. Mark O with the plumb bob. Draw the 0° line **along the board's +x direction** and mark R on it at 1.5 m.
3. Mark 24 points every 15° on a circle of radius 1.5 m. Chords (cm) for r = 1.5 m: 15° → 39.2, 30° → 77.6, 45° → 114.8, 60° → 150.0, 75° → 182.6, 90° → 212.1, 105° → 238.0, 120° → 259.8, 135° → 277.2, 150° → 289.8, 165° → 297.4, 180° → 300.0.
4. **This is a new setup, so repeat E0.5:** put the source at α = +45° and at α = +135° and check that the estimate lands on the same side.
5. Measure 24 points at elevation 15° (source 0.40 m above the board, which is 1.40 m above the floor), and 12 points every 30° at elevation 40° (1.26 m above the board, which is 2.26 m above the floor). In the GUI, set setup = B.
6. The source must always be **above** the board, never below it.

---

## 8. E4: distance (Setup A, about 1 hour)

- r = 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0 m (and 5.0 m if the room allows). θ = 0° and 45°.
- Source: 2.8 kHz tone from the speaker. **At each distance, hold the SLM near the board and adjust the speaker volume so the SPL at the board stays the same (±1 dB).** Write the SPL in the notes.
- Chord for the 45° points: c = 2r·sin(22.5°) = 0.765 × r.
- Measure each distance with the laser meter and enter the real value in the GUI.

---

## 9. E2: vertical sweep (Setup A, about 1.5 hours)

- Horizontal range 1.5 m; θ = 0°, +45°, −45°.
- Source heights: 0.33, 0.80, 1.20, 1.60, 2.07, 2.46 m (φ = −30, −15, 0, +15, +30, +40°).
- Measure the height with the laser meter each time and enter the real value in the GUI. If the tripod is unsteady at the high points, write that in the notes.

---

## 10. E5: frequency and source type (Setup A, about 1.5 hours)

- r = 2.0 m; θ = 0°, +30°, +60°.
- Sources: speaker tones at 1.0, 1.5, 2, 3, 4 and 5 kHz; the three buzzers; a car-horn recording; a white-noise burst.
- For the 1 kHz tone and the horn, set the low edge of the GUI band to 800 Hz, and **set it back to 1500 Hz afterwards**. The GUI saves the band used for every run.

---

## 11. E8: repeatability (Setup A, about 1 hour)

- **E8a (next day):** take the board off the tripod, mount it again and redo the alignment. Measure θ = 0, ±45, +90°.
- **E8b (board 2):** on board 2, run `SSL16_SelfTest` first, then `SSL16_Rec48`. Set board = `board2` in the session. Do its own E0.2, E0.3 and E0.5, then measure θ from −60° to +60° in 30° steps.

---

## 12. E7: environment (about 2 hours)

- A corridor and an open place (roof or field). Start a new session for each (with a different room name).
- In each place, do E0.1 (balloon) and E0.5 first, then θ from −60° to +60° in 30° steps, r = 2 m, 2.8 kHz buzzer.
- Do not measure outdoors when it is windy. Write the wind conditions in the notes.

---

## 13. What to tell me each day

1. Which experiments were done today, and the name of the session folder.
2. Temperature, humidity, and the reference thermometer reading against the board's `temp`.
3. The final flip values from E0.5 (first day).
4. Any warnings or unusual events.

I will then run the integrity check, the coverage table and that day's error-vs-angle plot, and tell you which points to redo the next day.
