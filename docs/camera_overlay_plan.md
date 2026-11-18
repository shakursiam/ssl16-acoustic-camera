# Acoustic camera: SSL-16 heatmap on a phone video

Status, 18 Nov 2026: the code is written and **tested on synthetic data only** (`tests/test_video_overlay.py`,
`tests/test_cam_calib.py`). It has not yet been run on a real phone video. The method is a proposal
(decision log #6).

## 1. Idea

There is no cable or radio link between the phone and the board. Both of them hear the same sound file,
`tests/camera_test/ssl16_test_sequence.wav`. The file starts and ends with the same sync block: 3 chirps
(500 Hz → 5 kHz, 50 ms each, 1 s apart).

```
 speaker ──► ssl16_test_sequence.wav ─┬─► phone microphone ─► phone video (.mp4, audio + frames)
                                      └─► SSL-16 (16 mics)  ─► <run>.wav (SD, 48 kHz) / <run>_pc.wav (USB, 12 kHz)

 ssl16_video_overlay.py:
   1. find the 6 sync chirps in the phone audio and in the SSL-16 file
   2. fit  t_ssl = a + b · t_phone            (a = offset, b = clock ratio, i.e. drift)
   3. run SRP-PHAT on the SSL-16 file, one map every 85 ms (170 ms window)
   4. for each video frame at time t_phone: take the map at t_ssl, project it into the image, paint it
```

## 2. Files

| File | What it does |
|---|---|
| `software/python/ssl16_video_overlay.py` | Sync, localisation, overlay video, results CSV, sync report |
| `software/python/ssl16_cam_calib.py` | Phone camera calibration from a checkerboard video → `camera.json` |
| `tests/camera_test/ssl16_test_sequence.wav` (+ `_markers.csv`, `make_test_wav.py`) | The sound file played in every run |
| `tests/test_video_overlay.py` | Synthetic end-to-end test (offset, 50 ppm drift, marker position) |
| `tests/test_cam_calib.py` | Synthetic checkerboard calibration; projection checked against OpenCV |

Install once: `python -m pip install -r software/python/requirements.txt`. This adds PyAV, Pillow and
OpenCV (OpenCV is used only for the calibration).

## 3. Changes from the "Option A" guideline

The guideline in `tests/camera_test/` is correct in principle. The points below update it to the current
firmware and software, and to what the synthetic tests showed.

1. **Firmware: `SSL16_Rec48` v1.2** (not WavRecorder_v4 / Stream_v3). Record with the recorder GUI with
   **both** boxes ticked: the SD card gets the raw 48 kHz file and the PC gets the 12 kHz file. The script reads
   either one. It takes the channel order from the `.txt` next to the WAV, so the PC file (mic order) and
   the SD file (slot order) both work. Prefer the SD file for analysis: it is raw and loses no samples over USB.
2. **One sound file per run** (`ssl16_test_sequence.wav`) instead of separate chirp / test files.
3. **Each chirp is matched on its own.** A 2-second, 3-chirp template stops matching when the clocks differ by
   tens of ppm (50 ppm = 0.6 samples per second at 12 kHz, which turns a 5 kHz component almost upside down
   within 2 s). The script finds each chirp separately, checks the 1 s spacing (±5 ms), and fits offset and
   drift to all 6 chirp times by least squares.
4. **Detection gate for broadband sounds.** The locator's own SNR measures how tonal the spectrum is, which suits
   buzzers. Noise, speech and horns score low on it. In the synthetic test only 2 of 187 blocks passed it. The overlay
   therefore uses `--gate level` by default: the in-band level (1.5–5 kHz) must be at least 10 dB above the
   recording's own noise floor. `--gate tonal` restores the old rule for buzzers.
5. **The orientation settings from E0.5 must be given** (`--flip-x`, `--flip-y`, `--rot`) or the map is mirrored.
6. **Mirror between array and image.** +x of the array is your right when you face the board. The phone looks
   the other way (towards the scene), so a source on +x appears on the **left** of the image. The code handles
   this; a test checks it.
7. **Frame times come from the video's own timestamps** (PyAV), so variable frame rate is handled. `ffprobe` is
   not needed.

## 4. One-time setup

### 4.1 Mount
- Board vertical (Setup A). Phone clamped rigidly **directly above** the board, centred left-right, screen
  parallel to the board face, landscape, main 1× lens.
- Measure the lens position relative to the array centre in the **array frame** (metres):
  `dx` = to your right when you face the board, `dy` = up, `dz` = towards the scene. Example: lens 10 cm above
  the centre and 1 cm behind the board face → `--lens-offset 0 0.10 -0.01`.
- The speaker must be inside the camera view.

### 4.2 Camera settings (same for calibration and runs)
1080p, 30 or 60 fps, **stabilisation off**, focus and exposure locked, HDR off, no filters, audio zoom /
wind-noise reduction off, airplane mode.

### 4.3 Camera calibration (choose one)
- **Accurate:** print a checkerboard (for example 10 × 7 squares of 25 mm = 9 × 6 inner corners) and stick it on a flat board.
  Record 30 s, moving it to all parts of the image and tilting it. Then:
  `python ssl16_cam_calib.py checker.mp4 --cols 9 --rows 6 --square-mm 25 --out camera.json`
  Accept it if `rms` < 1 px and coverage ≥ 75 %. Use it with `--calib camera.json`.
- **Quick (no distortion correction):** put the phone a measured distance D from a wall and mark the left and
  right edges of the view on the wall (width Wv). Then `hfov = 2·atan(Wv / 2D)`, and use `--hfov <deg>`.
  Good near the image centre; less accurate near the edges.

## 5. Every run

1. Put the speaker at the run position; write the true position (r, θ, φ) in the run log.
2. Start the phone video.
3. Start the SSL-16 recording (recorder GUI, run name e.g. `CAM_P01`, SD + PC ticked).
4. Say the run name aloud ("Camera run P01, 30 degrees right, 2 metres").
5. Play `ssl16_test_sequence.wav` once (76 s).
6. When it ends: stop the board, then stop the phone. The board recording must lie inside the video.
7. After the session: copy the videos and rename each to its run name (`CAM_P01.mp4`); copy the SD files.

## 6. Processing

Run in `software/python` (paths shortened):

```powershell
# 1) sync check only (fast): prints offset, drift and the checks, writes CAM_P01_overlay_sync.json
python ssl16_video_overlay.py CAM_P01.mp4 CAM_P01.wav --sync-only --markers ..\..\tests\camera_test\ssl16_test_sequence_markers.csv

# 2) overlay video
python ssl16_video_overlay.py CAM_P01.mp4 CAM_P01.wav --calib camera.json --lens-offset 0 0.10 -0.01 `
    --range 2.0 --temp 27 --markers ..\..\tests\camera_test\ssl16_test_sequence_markers.csv `
    --truth-theta 30 --truth-phi 0 --out CAM_P01_overlay.mp4
#   add --flip-x / --flip-y / --rot as found in E0.5
```

Outputs:
- `CAM_P01_overlay.mp4`: the video with the heatmap, a cross at the estimated direction, the times, the
  segment name and θ / φ. The phone audio is copied unchanged.
- `CAM_P01_overlay_results.csv`: one row per 85 ms: times (SSL, phone, sequence), segment, az / el, θ / φ, SNR,
  level, detected flag and the pixel (u, v).
- `CAM_P01_overlay_sync.json`: chirp times in both files, a, b, drift (ppm), residual, checks, and a summary per
  segment (detection rate, median θ / φ, and MAE when `--truth-*` is given).

Useful options: `--dyn-db 3` (the heatmap shows the top 3 dB of the map; smaller = tighter blob),
`--band 1500 5000`, `--method srp|das|music`, `--gate level|tonal`, `--min-level-db 10`, `--heat-step 8`
(heatmap computed every 8 px), `--smooth-s 0.12`, `--cam-ypr` (small camera rotation corrections, degrees).

## 7. Checks (the script prints and stores them)

| Check | Pass |
|---|---|
| Sync block found in each file | block score ≥ 3 × the best score anywhere else |
| Start → end interval | equals 70.05 s within 0.2 % in both files |
| Chirp fit | worst residual of the 6 chirps < 2 ms |
| Drift | \|b − 1\| ≤ 200 ppm |
| Visual (by eye) | the cross sits on the speaker; it appears when each sound starts, not a few frames early or late |

If the cross is on the speaker at the right time but shifted by a constant amount: re-measure the lens offset,
then correct the remaining offset with `--cam-ypr`. If it is right in one part of the run and drifts later,
a sync point is wrong (check the JSON).

## 8. What was verified, and what was not

Verified on synthetic data (18 Nov 2026):
- The sync template matches the real `ssl16_test_sequence.wav` (correlation > 0.999). Both sync blocks are found
  at 2.000 s and 72.050 s, and the block score ratio is about 9.
- Simulated run (source at θ 17.5°, φ 8.6°, 2 m; SSL clock 50 ppm fast and starting 1.5 s after the phone;
  12 kHz; AAC phone audio): offset found as −1.5000 s, drift +49.9 ppm, chirp residual 0.01 ms; median
  estimate θ 17.6°, φ 8.6°; the cross lands on the source dot in the video.
- The camera model projects exactly like OpenCV (with distortion). The calibration script recovers fx, fy within 2 %
  from a synthetic checkerboard video.

Not yet verified: a real phone (noise suppression, AAC delay, rotation metadata), the real board recording,
real room reflections. The first real run should be checked with `--sync-only` and by eye before more are recorded.

## 9. Limits to state if this is shown in the paper

- The blob is wide. At 1.5–5 kHz a 157 mm aperture has a main lobe of tens of degrees, so the heatmap shows
  where the energy comes from, not a sharp point. The cross (the peak) is the estimate.
- The car / bus horn fundamentals (300–510 Hz) are below the band. They are localised from their harmonics.
- The parallax correction uses one assumed distance (`--range`). A source far from that distance is drawn
  slightly off when the lens is far from the array centre (10 cm at 2 m ≈ 3°).
- A flat array cannot tell front from back; only the front half-space is drawn.
- The overlay is a visual aid. Accuracy numbers for the paper still come from runs with measured ground truth
  (`results.csv` with `--truth-theta/--truth-phi`), not from the picture.
