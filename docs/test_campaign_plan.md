# SSL-16 Localization Test Campaign — Lab Test Bench Plan

Nov 13, 2026 · @MD ABDUS SHAKUR SIAM

## 1. Goals and research questions

In one week, measure how accurately the SSL-16 board (16 MEMS mics, 157 mm planar spiral, SRP-PHAT) locates a known sound source, and record every run so the results go straight into a journal paper. Each experiment answers one research question with numbers, not impressions.

| ID | Research question | Experiment | Main metric |
| --- | --- | --- | --- |
| RQ1 | How accurate is the horizontal bearing across the field of view? | E1 | Bearing MAE, bias, RMSE vs bearing |
| RQ2 | How accurate is the vertical angle, and where does it break down? | E2 | Vertical-angle error vs angle |
| RQ3 | Does the array work over a full 360° when laid flat, with no mirror ambiguity? | E3 | Azimuth error vs azimuth, polar plot |
| RQ4 | From what distance does the far-field model hold? | E4 | Angular error vs distance (0.5–5 m) |
| RQ5 | How do source frequency and type change accuracy? | E5 | Error per tone, buzzer and horn recording |
| RQ6 | How does accuracy and detection fall as SNR drops? | E6 | Detection rate and error vs SNR |
| RQ7 | How much do room reflections hurt? | E7 | Error CDF per environment (lab, corridor, outdoor) |
| RQ8 | How much does per-channel calibration help? | E0 + reprocessing | Error before vs after calibration |
| RQ9 | Are results repeatable across days and across both boards? | E8 | Std of repeated runs; board 1 vs board 2 |
| RQ10 | Is it real-time? | E0 | Update rate, latency, packet drops |

**Metrics** (computed per test point over all detections, then summarised per experiment). The error is wrapped to ±180°:

```latex
e_i = \mathrm{wrap}_{180}(\hat\theta_i - \theta_{true}), \quad \mathrm{bias} = \frac{1}{N}\sum e_i, \quad \mathrm{MAE} = \frac{1}{N}\sum |e_i|, \quad \mathrm{RMSE} = \sqrt{\frac{1}{N}\sum e_i^2}
```

The 3-D angular error is the great-circle angle between the true and estimated unit vectors:

```latex
\Delta = \arccos\left(\mathbf{u}_{true} \cdot \hat{\mathbf{u}}\right)
```

Also report the 95th percentile of |e|, the standard deviation across the 3 repetitions (repeatability), and the detection rate (blocks with a detection ÷ blocks while the source is on).

**Working targets** (to confirm or revise after E1): bearing MAE ≤ 3° within ±60° at ≥ 1 m in the lab; detection rate ≥ 95% at SNR ≥ 10 dB; update rate ≥ 10 Hz.

## 2. Coordinate frame, setups and ground truth

Every source position is logged as x, y, z in metres in the **array frame**; all angles are derived from those numbers, so one data format serves both setups.

**Array frame.** Origin = centre of the mic spiral (0, 0 in the revC1 table). x and y lie in the board plane, along the +x / +y arrows of the mic layout drawing. z points out of the sound-hole face. The GUI's azimuth is measured in the x–y plane from +x, and its elevation is measured up from the board plane.

**Setup A — camera mode (board vertical, the main setup).** The board stands on a tripod with its face toward the test area, which is how a horn-detection unit would be mounted at a roadside.

- Board centre at 1.20 m above the floor.
- Seen from the sound side: +x to the right, +y up, z forward.
- Bearing θ (left–right, positive towards +x) and vertical angle φ (positive up), at range r and source height h:

```latex
x = r\sin\theta, \quad z = r\cos\theta, \quad y = h_{src} - h_{board}, \qquad \theta = \operatorname{atan2}(x, z), \quad \varphi = \arcsin(y/d)
```

**Setup B — table mode (board flat, face up).** Board on a stand at 1.00 m, face up and raised on standoffs. This tests the full 360° azimuth around the board.

```latex
x = r\cos\alpha, \quad y = r\sin\alpha, \quad z = h_{src} - h_{board}
```

**Measuring ground truth without a protractor.** Angles are set with a tape measure using chords, which is more accurate than a protractor at 1–2 m.

1. Hang a plumb bob from the board centre and mark the floor point O.
2. Snap a chalk line (or use a laser line) from O along the 0° direction: +z in Setup A, +x in Setup B. Mark a point R on it at radius r.
3. Each test point P sits at distance r from O and at chord length c from R:

```latex
c = 2r\sin(\theta/2)
```

4. Mark P with masking tape and write its ID on the tape. Measure the source height with a laser distance meter.
5. The source's acoustic centre is the buzzer's sound hole or the speaker's cone centre, not the case edge.

The chord table for r = 1.5 m and 2.0 m is in Section 3. Photograph every bench layout with the tape marks visible; the paper needs a setup figure.

![Bench geometry: Setup A arc and chord method, Setup B circle](images/bench_geometry.png)

In Setup A the board's face points at a 2 m arc and each source point is set by its chord from the 0° mark R; in Setup B the source moves around a 1.5 m circle with 0° on the board's +x axis.

## 3. Equipment and bench build

Everything below is cheap or already in a lab; collect it before Day 1 so no test day is lost to shopping.

| Item | Qty | Used for | Note |
| --- | --- | --- | --- |
| SSL-16 boards (Rev D) | 2 | Device under test | Board 2 only for E8 |
| Laptop with the GUI + USB-C cable | 1 | Capture and logging | Disable sleep; close other serial tools |
| Camera / light-stand tripods (≥ 1.8 m) | 2 | Board mount, source mount | Thin legs; reflections from bulky stands bias results |
| Board adapter plate (acrylic or 3D-printed) | 1 | Holds the board by its mounting holes | Must not cover any sound hole |
| Active piezo buzzers, 5 V (about 2.3, 2.8 and 4 kHz) | 3+ | Main sources | Measure each one's real frequency in E0 |
| Small powered speaker (Bluetooth or USB) | 1 | Tones, horn recording, noise | Note the model in the log |
| Second speaker | 1 | Interfering noise in E6 | Any speaker |
| Sound level meter (or a calibrated phone app) | 1 | SPL at the board | Report dB(A) and SNR |
| Laser distance meter | 1 | Range and heights | ±2 mm class |
| 5 m steel tape, masking tape, chalk line, plumb bob | 1 each | Floor marks, chords |  |
| Digital inclinometer (or phone level app) | 1 | Board plumb / level | Board must be within ±0.5° |
| Thermometer / hygrometer | 1 | Speed of sound | Log at the start of each session |
| 5 V power bank for buzzers | 1 | Source power | Keeps cables off the floor area |
| Phone camera | 1 | Setup photos for the paper |  |

**Bench build (Setup A):**

1. Choose the largest clear area in the lab: at least 3 m in front of the board and 1 m from walls on the sides.
2. Mount the board on tripod 1. Centre at 1.20 m. Use the inclinometer to make the face vertical and the x-axis level.
3. Mark O and the 0° line (Section 2). Mark points every 10° from −90° to +90° at r = 2.0 m using the chord table below.
4. Point the 0° line exactly along z: aim the laser distance meter from the board centre along the face normal, square to the face, and confirm it lands on the 0° line.
5. Put the source on tripod 2 at the board's height (1.20 m) with its sound hole facing the board.

**Bench build (Setup B):** board face up on a stand at 1.00 m, raised on standoffs. Mark 24 points every 15° around a 1.5 m circle. 0° is the +x direction of the board.

**Chord lengths for setting angles** (distance from the 0° mark R to the point; the same value works on both sides of the line):

| Angle (deg) | Chord at r = 1.5 m (cm) | Chord at r = 2.0 m (cm) |
| --- | --- | --- |
| 10 | 26.1 | 34.9 |
| 15 | 39.2 | 52.2 |
| 20 | 52.1 | 69.5 |
| 30 | 77.6 | 103.5 |
| 40 | 102.6 | 136.8 |
| 45 | 114.8 | 153.1 |
| 50 | 126.8 | 169.0 |
| 60 | 150.0 | 200.0 |
| 70 | 172.1 | 229.4 |
| 75 | 182.6 | 243.5 |
| 80 | 192.8 | 257.1 |
| 90 | 212.1 | 282.8 |
| 105 | 238.0 | 317.3 |
| 120 | 259.8 | 346.4 |
| 135 | 277.2 | 369.6 |
| 150 | 289.8 | 386.4 |
| 165 | 297.4 | 396.6 |
| 180 | 300.0 | 400.0 |

## 4. Experiment 0 — calibration and characterization

E0 runs once at the start of each test day in Setup A. It fixes the orientation signs before any data is taken, and it produces the calibration and system numbers the paper's "System characterization" table needs. Allow about 1.5 h on Day 1 and 20 min on later days (steps 1, 2 and 5 only).

| Step | What | How | Output for the paper |
| --- | --- | --- | --- |
| E0.1 | Environment | Log temperature, humidity and background level in dB(A). Pop a balloon (or clap) 2 m away and keep the raw recording. | Conditions table; RT60 of each room (computed later from the decay of the recording) |
| E0.2 | Noise floor | 30 s raw recording in silence | Per-channel noise in dBFS; spread between channels |
| E0.3 | Channel calibration | Speaker at θ = 0°, φ = 0°, r = 2 m. Play tones from 1 to 5 kHz in 500 Hz steps, 3 s each. At broadside every mic sees the same path, so any gain or phase difference is the hardware. | Per-channel gain (dB) and phase (µs) table; input for RQ8 |
| E0.4 | Source characterization | Each buzzer 0.3 m from the board, 5 s raw recording; SPL at 1 m with the sound level meter | Real frequency and harmonics of each source |
| E0.5 | Orientation check | Source at θ = +45°, then at φ = +30°. The estimate must land on the same side. If not, set flip x / flip y and repeat. | The final flip / rotate settings, logged once and never changed afterwards |
| E0.6 | Boresight offset | Source at θ = 0°, 3 × 10 s | Mounting yaw error. If it is more than 1°, re-align the board physically; do not hide it in software. |
| E0.7 | Real-time figures | 10 min continuous run with the source on | Update rate (Hz), packet gaps per minute, processing time per block, latency (window length + processing) |

**Rule:** no E1–E8 data is valid until E0.5 has passed that day. Write the flip / rotate values into the session log.

The GUI does not apply the E0.3 calibration live. RQ8 is answered offline: the same raw recordings are processed twice, with and without calibration. That is why every measurement saves raw audio (Section 8).

## 5. Test matrix

Eight experiments: each changes one thing and holds the rest fixed. Every point is measured 3 times × 5 s (10 s in E6), with raw audio saved. Together they take about 12 hours of bench time, which fits in four lab days plus a buffer day.

| ID | Setup | What varies | Levels | Held fixed | Points × reps | Time | Journal output |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E1 Bearing sweep | A | Bearing θ | −90° to +90°, 10° steps (19); extra buzzers at 0, ±30, ±60, ±90 | r = 2.0 m, φ = 0°, 2.8 kHz buzzer | 33 × 3 | 2 h | Error vs bearing (main result); MAE / RMSE table |
| E2 Vertical sweep | A | Vertical angle φ | −30, −15, 0, +15, +30, +40° (source at 0.33, 0.80, 1.20, 1.60, 2.07, 2.46 m) | Horizontal range 1.5 m; θ = 0°, ±45° | 18 × 3 | 1.5 h | Error vs φ; shows where the vertical angle breaks down |
| E3 360° sweep | B | Azimuth α | 0–345°, 15° steps at elevation 15°; 30° steps at 40° | r = 1.5 m, source 0.40 m / 1.26 m above the board | 36 × 3 | 2 h | Polar error plot; mirror / ambiguity check |
| E4 Distance | A | Range r | 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0 m (5.0 if the room allows) | θ = 0° and 45°; speaker tone 2.8 kHz with SPL at the board held constant (±1 dB, set with the SLM) | 16 × 3 | 1 h | Error vs range; near-field limit. Constant SPL separates the range effect from SNR. |
| E5 Frequency / source | A | Source | Speaker tones 1.0, 1.5, 2, 3, 4, 5 kHz; 3 buzzers; car-horn recording; white-noise burst | r = 2.0 m; θ = 0°, +30°, +60° | 33 × 3 | 1.5 h | Error vs frequency; the aperture limit at low frequency |
| E6 SNR | A | Noise level | In-band SNR +30, +20, +10, +5, 0, −5 dB; plus noise only (source off) | Source 2.8 kHz at θ = +30°, r = 2 m; pink-noise speaker at θ = −45°, r = 2 m | 7 × 3 (10 s each) | 1 h | Detection rate and error vs SNR; false-alarm rate |
| E7 Environment | A | Room | Lab (reuse E1), corridor, outdoor (roof or open ground) | θ = −60 to +60°, 30° steps; r = 2 m; 2.8 kHz buzzer | 10 × 3 (+ E1) | 2 h incl. moving | Error CDF per room, with each room's RT60 |
| E8 Repeatability | A | Day, board | (a) next-day re-mount: θ = 0, ±45, +90°; (b) board 2: θ = −60 to +60°, 30° steps + E0.2, E0.3 | Same marks, same source | 9 × 3 | 1 h | Repeatability (std) and board-to-board difference |

**Notes on the matrix:**

- **Band settings:** E5 needs the GUI band changed for the 1 kHz tone (low = 800 Hz) and the horn (low = 800 Hz). Write the band used into the log for every point.
- **Horn recording:** car horns have their fundamental near 400–500 Hz. At that frequency the 157 mm array cannot resolve direction well, so localization relies on the harmonics. E5 gives this as a measured result rather than an assumption.
- **SNR reference:** compute E6's SNR from the raw recordings (source-only and noise-only, in the analysis band), not from the sound level meter alone. Record SLM readings too, as a cross-check.
- **Optional E9** (only if a day is spare): two buzzers of different frequency switched on together at 60°, 40°, 20° and 10° separation. Each is located with its own band setting, which tests two-source separation by frequency.

## 6. Measurement protocol for each point

The same steps for every point keep the data comparable; with two people (one at the source, one at the laptop) a point takes about 1.5 minutes.

1. **Place the source** on its tape mark, sound hole facing the board centre. Check the height with the laser distance meter.
2. **Enter the position in the GUI** in the setup's own terms: Setup A takes range, bearing and height; Setup B takes range, azimuth and height. The GUI converts to x, y, z.
3. **Fill in the labels:** experiment ID, point ID, source name and band. The repetition number counts up by itself.
4. **Quiet the room:** no talking, no walking. Nobody stands in front of the board; the operator sits behind it, at least 1 m back. Doors closed and fans off, or logged if they can't be switched off.
5. **Source on,** wait 2 s, then press **Measure** (5 s). Repeat for reps 2 and 3 without touching anything.
6. **Check the row** the GUI adds. Redo the point once if detections are fewer than 70% of the blocks, or the spread is over 5°. Never delete a run: the redo is saved as a new run, and the first one is kept and flagged.
7. **Write events** in the notes field: a door slam, a passing vehicle, a fan switching on.
8. **Control point:** after every 10 points, re-measure the reference point (θ = 0° in Setup A, α = 0° in Setup B). A drift of more than 1° from the session start means something moved; stop and find out what.
9. **Photograph** each new layout, and the board mount at the start of each session.

**Point order.** Within an experiment, measure in a shuffled order rather than sweeping left to right. Drift over time (temperature, a tripod settling) then shows up as scatter instead of a false trend against angle. The GUI can print a shuffled order for each experiment.

**Per-session log** (one line at the top of the day's folder): date, people, room, temperature, humidity, background dB(A), board serial, firmware name, GUI version, flip / rotate settings from E0.5, and the boresight offset from E0.6.

## 7. Schedule

Five lab days plus one buffer day finish all eight experiments by Nov 21, 2026. Setup A stays built from Day 1 to the morning of Day 4, so the most delicate alignment is done only once.

| Day | Date | Setup | Work | Bench hours | Done when |
| --- | --- | --- | --- | --- | --- |
| 0 Prep | Nov 14, 2026 | — | Collect equipment; print the chord table and point lists; flash both boards; GUI demo run; dry-run one point end to end | 2 | One saved test run opens and plays back |
| 1 | Nov 15, 2026 | A | Build Setup A; E0 full; **E1** bearing sweep | 5 | E0.5 passed; 33 E1 points × 3 saved |
| 2 | Nov 16, 2026 | A | Re-mount check first (**E8a**); E0 short; **E2** vertical; **E4** distance | 4 | E8a, E2, E4 complete |
| 3 | Nov 17, 2026 | A | E0 short; **E5** frequency / source; **E6** SNR | 3.5 | E5, E6 complete; noise-only run saved |
| 4 | Nov 18, 2026 | A, then B | **E8b** board 2 (with its own E0.2, E0.3); rebuild as Setup B; **E3** 360° | 4 | E3 polar plot shows no mirrored points |
| 5 | Nov 19, 2026 | A (mobile) | **E7** corridor and outdoor, each with E0.1 and E0.5; optional E9 | 3 | Both rooms done, RT60 recordings saved |
| 6 Buffer | Nov 21, 2026 | — | Redo flagged points; full analysis run; draft figures | — | All figures in Section 9 generated |

**Every evening:** copy the day's folder to the shared drive and run the analysis script on it. This shows that day's error-vs-angle plot. A problem found the same evening costs one redo; found after the week, it costs the whole experiment.

## 8. Data management

Every run saves raw 16-channel audio plus its metadata. Any later analysis (calibration on/off, other algorithms such as delay-and-sum or MUSIC, a reviewer's request) can then be redone without going back to the lab. The whole week is about 600 runs and 1–2 GB.

**Folder layout** (the GUI creates it):

```
ssl16_campaign/
  2026-11-15_lab_board1/          one folder per session (date_room_board)
    session.json                  per-session log (Section 6)
    runs.csv                      one row per run: position, labels, summary result
    blocks.csv                    one row per processing block: time, az, el, SNR, detected
    E1/
      E1_P07_r1_142233.wav        16-channel int16 WAV, stream slot order
      E1_P07_r1_142233.json       metadata for that run
    photos/
```

**Run metadata** (the JSON next to each WAV, and the same fields in runs.csv):

| Field | Example | Note |
| --- | --- | --- |
| experiment, point, rep | E1, P07, 1 |  |
| setup | A | A = camera, B = table |
| r\_m, angle\_deg, h\_src\_m, h\_board\_m | 2.0, −30, 1.20, 1.20 | As entered |
| x\_m, y\_m, z\_m | −1.000, 0.000, 1.732 | Array frame, computed |
| true\_az, true\_el |  | Array-frame truth |
| source, band\_lo, band\_hi | buzzer\_2k8, 1500, 5000 |  |
| fs, n\_samples, slot\_order | 12000, 60000, M2 M7 … M16 |  |
| flip\_x, flip\_y, rot\_deg, temp\_c |  | Settings in force |
| est\_az, est\_el, std\_az, n\_detect, n\_blocks |  | GUI live result |
| board, firmware, gui\_version, operator, notes | board1, SSL16\_HDOA, 2.0 |  |

**Rules:**

- Never edit or delete raw files. A bad run gets `flag = bad` and a reason in runs.csv.
- Copy each session folder to the shared drive the same evening (two copies at all times).
- Keep the dataset in a form you can publish: the journal's data-availability statement can then point to a Zenodo or GitHub release of this folder.

**Software** (keep all three files in one folder):

| File | Role |
| --- | --- |
| ssl16\_buzzer\_gui.py (v2) | Live view and logger. Session dialog, position entry for Setups A and B, run labels, Measure (saves the WAV and metadata), Flag last bad, Shuffle order |
| ssl16\_core.py | Shared geometry, the three beamformers (SRP-PHAT, delay-and-sum, MUSIC), calibration, WAV I/O |
| ssl16\_analyze.py | Evening and final analysis: re-processes every WAV and writes summary.csv and the figures |

Evening check: `python ssl16_analyze.py ssl16_campaign/<today's session>`. Final run for the paper: `python ssl16_analyze.py "ssl16_campaign/*" --methods srp,das,music --calib <E0.3 broadside WAV>`.

## 9. Analysis plan and journal figures

The week's data supports a full experimental-results section: 11 figures and 6 tables, each tied to one experiment. All are generated by one analysis script from the saved raw files, so every number in the paper can be regenerated.

**Analysis steps:**

1. Load runs.csv and every WAV. Re-run the beamformer offline with fixed settings, so live-GUI tweaks cannot leak into the results.
2. Per point: pool the three reps and compute bias, MAE, RMSE, P95 and detection rate (Section 1).
3. Per experiment: plot each metric against the variable that experiment changes. Add 95% bootstrap confidence intervals to every MAE.
4. **RQ8:** repeat steps 1–3 with the E0.3 calibration applied and report the difference.
5. **Algorithm comparison:** on the same files, run conventional delay-and-sum and MUSIC alongside SRP-PHAT. Reviewers usually ask why SRP-PHAT; this table answers it.
6. **Theory overlay:** beamwidth ≈ λ/D for D = 157 mm, and the far-field distance below. These show where measured errors should and should not grow.

```latex
r_{ff} = \frac{2D^2}{\lambda} \approx 0.40\ \mathrm{m\ at\ 2.8\ kHz}
```

7. **Statistics:** Wilcoxon signed-rank test for calibrated vs uncalibrated, and for board 1 vs board 2 (paired by point). Report p-values and the median difference.

**Figures**

| No. | Content | Data |
| --- | --- | --- |
| F1 | System photo + hardware block diagram (mics → ADCs → TDM → ESP32-S3 → PC) | Design files |
| F2 | Mic layout and simulated beam pattern at 2.8 kHz | Geometry only |
| F3 | Test bench: photo and geometry drawing of Setups A and B | Photos, Section 2 |
| F4 | **Main result:** bearing error vs bearing, mean ± std, one line per buzzer | E1 |
| F5 | Vertical-angle error vs φ | E2 |
| F6 | Polar plot, estimated vs true azimuth over 360° | E3 |
| F7 | Error vs range, far-field limit marked | E4 |
| F8 | Error vs frequency, theoretical beamwidth on a second axis | E5 |
| F9 | Detection rate and error vs SNR (two panels), false-alarm rate noted | E6 |
| F10 | Error CDF per environment, RT60 in the legend | E7 |
| F11 | Example SRP-PHAT maps: clean, low-SNR, reverberant | E1, E6, E7 |

**Tables**

| No. | Content | Data |
| --- | --- | --- |
| T1 | System specification and real-time figures (fs, channels, update rate, latency, packet loss) | E0.7 |
| T2 | Test conditions per room (temperature, humidity, background dB(A), RT60) | E0.1, E7 |
| T3 | Accuracy summary per experiment: bias, MAE, RMSE, P95, detection rate | E1–E7 |
| T4 | Calibration effect and algorithm comparison (SRP-PHAT, delay-and-sum, MUSIC), same data | All |
| T5 | Repeatability across days and boards | E8 |
| T6 | Comparison with published low-cost arrays (aperture, mics, accuracy, cost) | Literature, to fill |

**Paper structure this supports:** Introduction → System design (F1, F2, T1) → Localization method → Experimental setup (F3, T2, Sections 2–6) → Results (F4–F11, T3–T5) → Discussion (limits: elevation near the board plane, low-frequency horn fundamentals, reverberation) → Conclusion.

## 10. Uncertainty and risks

The bench's own ground truth is good to about ±0.6° (1σ) at 2 m, so any measured bearing error clearly above 1° belongs to the array, not to the tape measure. This budget goes into the paper's setup section.

**Ground-truth uncertainty of the bearing** (root-sum-square of independent terms):

| Source of uncertainty | Assumed size | Effect at r = 2.0 m | Effect at r = 0.5 m |
| --- | --- | --- | --- |
| Floor mark position | ±5 mm | 0.14° | 0.57° |
| Source acoustic centre | ±10 mm | 0.29° | 1.15° |
| Board yaw alignment | ±0.5° | 0.50° | 0.50° |
| Array origin vs mount | ±3 mm | 0.09° | 0.34° |
| Plumb point O | ±3 mm | 0.09° | 0.34° |
| **Combined** |  | **0.61°** | **1.46°** |

Speed of sound: a 3 °C error in the temperature used gives up to 0.5° at θ = 60°. That is why temperature is logged every session and the logged value is used in the analysis.

**Risks**

| Risk | Effect | Mitigation |
| --- | --- | --- |
| Reflections from walls, table, tripods, people | Bias and scatter that look like array error | 1 m clearance at the sides; thin stands; operator behind the board; RT60 measured and reported |
| Lab noise (AC, fans, people, traffic) | Lower SNR, false detections | Test in quiet hours; log background dB(A) and events per run |
| Buzzer level or pitch drift as the battery drops | Changing SNR, wrong band | Power bank; check SPL and frequency at each E0 |
| Board mount shifts during the day | Slow drift in every result | Control point every 10 points (Section 6) |
| USB packet drops or laptop sleep | Gaps in data | Gap counter visible in the GUI; sleep disabled; drops logged per run |
| Wind and traffic outdoors (E7) | Noise unrelated to the room | Calm time of day; log wind; repeat if gusty |
| Front/back ambiguity of a flat array | A source behind the board is reported in front | Keep every source in front of the face (Setup A) or above the board (Setup B) |
| Running out of time | Missing experiments | Priority order below |

**Priority order if time runs short:** E0 → E1 → E6 → E3 → E4 → E2 → E5 → E8 → E7. E0, E1 and E6 alone already support a short conference paper: accuracy, robustness and system figures.
