# Floor bench (quick setup): board at 1.00 m, buzzers on the floor

A small bench that needs only a tape measure, chalk/tape and a plumb line. It is used for the E0.5
orientation check and for pilot accuracy runs. Status: **proposed** (decision log #5). Whether its
data can stand in for the E1 protocol of `test_campaign_plan.md` is Siam's decision.

## 1. Build (about 20 minutes)

1. Board vertical (Setup A), **array centre 1.00 m above the floor**, sound-hole face towards the open floor.
   Labels UP and RIGHT on the board (see E0.5 in the lab guide). Photo of the front.
2. Plumb line from the array centre → mark **O** on the floor.
3. From O, chalk/tape the **0° line** straight forward, perpendicular to the board face (3-4-5 triangle or a set square).
4. Mark the points below. Measure **z along the 0° line**, then **x at a right angle** from it.
   **+x = your right side when you stand in front of the board and face it.**
5. Put a tape label with the point ID on each mark.

| Point ID | x (cm) | z (cm) | GUI: r (m) | GUI: θ (°) | Expected φ (°) |
|---|---|---|---|---|---|
| `F15_M60` | −129.9 | 75.0 | 1.50 | −60 | −33.7 |
| `F15_M30` | −75.0 | 129.9 | 1.50 | −30 | −33.7 |
| `F15_0` | 0.0 | 150.0 | 1.50 | 0 | −33.7 |
| `F15_P30` | +75.0 | 129.9 | 1.50 | +30 | −33.7 |
| `F15_P60` | +129.9 | 75.0 | 1.50 | +60 | −33.7 |
| `F20_M30` | −100.0 | 173.2 | 2.00 | −30 | −26.6 |
| `F20_0` | 0.0 | 200.0 | 2.00 | 0 | −26.6 |
| `F20_P30` | +100.0 | 173.2 | 2.00 | +30 | −26.6 |

GUI fields for every point: **src h = height of the buzzer's sound hole above the floor** (measure it once,
e.g. 0.02), **board h = 1.00**. φ above is for src h = 0; with 0.03 m it is about 0.8° smaller in magnitude.
A placement error of 1 cm moves θ by about 0.4° at 1.5 m and 0.3° at 2.0 m.

## 2. Buzzer placement

- Sound hole **at the marked point**, facing the board (tilt it against a small block if it normally points up). Same buzzer for all points.
- Nothing between the buzzer and the board; no bags or boxes within 0.5 m of the path.
- Only **one** buzzer on at a time.

## 3. Procedure

1. Campaign GUI (`ssl16_buzzer_gui.py`), port COM3, session base `...\SSL-16 Journal\ssl16_campaign`.
   Settings: flip x / flip y off, rotate 0, band 1500–5000 Hz, real air temperature.
2. **Orientation check (E0.5)**, exp `E0`: `F15_P30` and `F15_M30`, 3 × 5 s each.
   - Pass: θ positive at `F15_P30` and negative at `F15_M30`, φ negative at both, each within 10° of the table.
   - θ signs reversed → flip x on and repeat. φ positive → flip y on and repeat.
   - Write the final flip_x / flip_y / rot in the session notes; never change them afterwards.
3. **Pilot runs**, exp `E1` (or a name Siam chooses): all 8 points, **3 × 5 s each, in shuffled order** (Shuffle order button).
   Measure `F15_0` again after every 4 points as the control point (it must stay within 1° of its first value).
4. After every Measure: if the GUI warns about SD / I2S overflow / detections, press **Flag last bad** and redo the point.
5. End of session: copy the SD card's `/ssl16/` into the session folder as `sd_raw\` (do not rename), then send the folder for checking.

About 45 minutes for the 8 points.

## 4. Limits to keep in mind

- All points are about 27–34° below the array centre, so θ and φ are always tested together; this is not the
  "source at board height" geometry of E1 in the campaign plan.
- A buzzer at 2.5 kHz gives a main lobe of about λ/D ≈ 50°; reflections in a small room spread the estimates.
  A 4 kHz buzzer narrows this to about 31°.
- The planar array cannot tell front from back; all points are in front of the sound-hole face.
