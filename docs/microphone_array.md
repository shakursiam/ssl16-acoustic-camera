# SSL-16 Sunflower Microphone Array Geometry & Specifications

## 1. Array Design & Acoustic Performance

The **SSL-16** microphone array employs a 16-element **Vogel (Sunflower) spiral** geometry constrained within an **80 mm aperture radius** ($R = 80\,\text{mm}$, total aperture diameter $D = 160\,\text{mm}$).

### Acoustic Bandwidth
- **Lower Operating Bound ($\sim 1.5\,\text{kHz}$):** Sound wavelengths below $1.5\,\text{kHz}$ ($\lambda \ge 22.8\,\text{cm}$) exceed the physical aperture diameter ($16\,\text{cm}$), resulting in a broad main lobe and negligible spatial resolution.
- **Upper Operating Bound ($\sim 6.0\,\text{kHz}$):** The aperiodic Vogel spiral geometry breaks spatial lattice periodicity, suppressing coherent spatial grating lobes and dispersing aliasing energy into a low, pseudo-random sidelobe floor across the visible region up to $6.0\,\text{kHz}$ ($\lambda \approx 5.7\,\text{cm}$).
- **Usable Beamforming Band:** **1.5 kHz to 6.0 kHz** (ideal for urban vehicle horn acoustic localization, which predominantly concentrates energy between 2.0 kHz and 4.5 kHz).

---

## 2. Array Coordinate Table

All coordinates are specified in millimeters ($\text{mm}$) relative to the physical center of the array ($x = 0, y = 0$).  
**Coordinate Frame:** View looking onto the **top (front) face** of the PCB:
- $+X$: $0^\circ$ (pointing right)
- $+Y$: $90^\circ$ (pointing top)
- Physical PCB hole positions match these coordinates to within **$< 0.01\,\text{mm}$**.

| Mic ID | Schematic Ref | X Position (mm) | Y Position (mm) | Radius $r$ (mm) | Angle $\theta$ (deg) | ADC Device | ADC Channel | TDM Slot |
|---|---|---|---|---|---|---|---|---|
| **M1** | `MK1` | $9.877$ | $1.564$ | $10.00$ | $8.99^\circ$ | **U2** | IN1 | **Slot 4** |
| **M2** | `MK2` | $-16.122$ | $10.668$ | $19.33$ | $146.49^\circ$ | **U1** | IN1 | **Slot 0** |
| **M3** | `MK3` | $6.361$ | $-25.483$ | $26.27$ | $-75.97^\circ$ | **U3** | IN1 | **Slot 8** |
| **M4** | `MK4` | $15.325$ | $28.252$ | $32.14$ | $61.53^\circ$ | **U2** | IN2 | **Slot 5** |
| **M5** | `MK5` | $-35.329$ | $-12.187$ | $37.37$ | $-160.97^\circ$ | **U4** | IN1 | **Slot 12** |
| **M6** | `MK6` | $38.669$ | $-16.782$ | $42.15$ | $-23.46^\circ$ | **U3** | IN2 | **Slot 9** |
| **M7** | `MK7` | $-18.989$ | $42.553$ | $46.59$ | $114.04^\circ$ | **U1** | IN2 | **Slot 1** |
| **M8** | `MK8` | $-16.064$ | $-48.167$ | $50.77$ | $-108.43^\circ$ | **U4** | IN2 | **Slot 13** |
| **M9** | `MK9` | $47.843$ | $26.590$ | $54.73$ | $29.06^\circ$ | **U2** | IN3 | **Slot 6** |
| **M10** | `MK10` | $-56.913$ | $13.588$ | $58.51$ | $166.57^\circ$ | **U1** | IN3 | **Slot 2** |
| **M11** | `MK11` | $34.817$ | $-51.463$ | $62.14$ | $-55.92^\circ$ | **U3** | IN3 | **Slot 10** |
| **M12** | `MK12` | $9.600$ | $64.914$ | $65.62$ | $81.59^\circ$ | **U2** | IN4 | **Slot 7** |
| **M13** | `MK13` | $-53.540$ | $-43.504$ | $68.99$ | $-140.91^\circ$ | **U4** | IN3 | **Slot 14** |
| **M14** | `MK14` | $72.120$ | $-4.280$ | $72.25$ | $-3.40^\circ$ | **U3** | IN4 | **Slot 11** |
| **M15** | `MK15` | $-52.491$ | $54.144$ | $75.41$ | $134.11^\circ$ | **U1** | IN4 | **Slot 3** |
| **M16** | `MK16` | $2.219$ | $-78.459$ | $78.49$ | $-88.38^\circ$ | **U4** | IN4 | **Slot 15** |

---

## 3. Acoustic Port Implementation & PCB Stack-Up

1. **Acoustic Port Geometry:**
   - Each microphone uses a **0.80 mm Non-Plated Through Hole (NPTH)** drilled entirely through the 1.6 mm PCB substrate.
   - Solder mask is removed around the hole on the bottom layer to allow an unbroken ring of solder paste to form an airtight acoustic gasket around the microphone sound port.
2. **Top Face (Acoustic Window):**
   - A **5.0 mm circular keep-out zone** surrounds each 0.8 mm acoustic hole on the top copper (`F.Cu`), top silkscreen (`F.Silkscreen`), and solder mask (`F.Mask`).
   - Copper pours and silkscreen lettering are excluded from this circle to prevent acoustic diffraction, turbulence, or dust trapping.
3. **Microphone Package:**
   - **Infineon IM73A135V01XTSA1**: High-performance differential analog MEMS microphone in a $4.00 \times 3.00 \times 1.20\,\text{mm}$ LGA-5 package.
   - **AOP (Acoustic Overload Point):** $135\,\text{dB SPL}$ (prevents clipping in close proximity to loud sirens and commercial vehicle air horns).
   - **SNR:** $73\,\text{dB(A)}$ with ultra-flat low-frequency extension.
