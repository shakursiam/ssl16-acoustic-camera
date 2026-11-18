"""Build docs/SSL16_Floor_Bench_Guide.docx (+ figures in docs/images/floor_bench/).

Run from the repo root:
    python tools/make_floor_bench_guide.py
Needs numpy, matplotlib, python-docx. Every number in the guide is computed here from the bench geometry.
"""
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle, Polygon, Arc, FancyArrowPatch
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "docs", "images", "floor_bench")
OUT = os.path.join(ROOT, "docs", "SSL16_Floor_Bench_Guide.docx")
os.makedirs(IMG, exist_ok=True)

# ------------------------------------------------------------------ geometry (single source of truth)
H_BOARD = 1.00                                   # array centre above the floor (m)
POINTS = [("F15_M60", 1.5, -60), ("F15_M30", 1.5, -30), ("F15_0", 1.5, 0), ("F15_P30", 1.5, 30),
          ("F15_P60", 1.5, 60), ("F20_M30", 2.0, -30), ("F20_0", 2.0, 0), ("F20_P30", 2.0, 30)]


def geo(r, th, h_src=0.0):
    x, z = r * math.sin(math.radians(th)), r * math.cos(math.radians(th))
    y = h_src - H_BOARD
    phi = math.degrees(math.asin(y / math.sqrt(r * r + y * y)))
    return x, z, phi


# colour-blind-safe palette (Okabe-Ito)
BLUE, ORANGE, GREEN, VERM, GREY, SKY = "#0072B2", "#E69F00", "#009E73", "#D55E00", "#555555", "#56B4E9"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})


def save(fig, name):
    p = os.path.join(IMG, name)
    fig.savefig(p, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return p


# ------------------------------------------------------------------ figures
def fig_workflow():
    fig, ax = plt.subplots(figsize=(9, 2.3)); ax.axis("off"); ax.set_xlim(0, 10); ax.set_ylim(0, 2.3)
    steps = [("1", "Upload firmware\nSSL16_Rec48 v1.2", BLUE), ("2", "Start GUI\nssl16_buzzer_gui.py", BLUE),
             ("3", "Build bench\n8 floor points", GREEN), ("4", "E0.5\norientation check", ORANGE),
             ("5", "Pilot runs\n8 points x 3", ORANGE), ("6", "Copy SD card\n& send folder", GREY)]
    w = 1.45
    for i, (n, t, c) in enumerate(steps):
        x0 = 0.1 + i * 1.65
        ax.add_patch(FancyBboxPatch((x0, 0.45), w, 1.3, boxstyle="round,pad=0.03,rounding_size=0.12",
                                    fc=c, ec="none", alpha=0.15))
        ax.add_patch(FancyBboxPatch((x0, 0.45), w, 1.3, boxstyle="round,pad=0.03,rounding_size=0.12",
                                    fc="none", ec=c, lw=1.5))
        ax.text(x0 + w / 2, 1.45, n, ha="center", va="center", fontsize=14, fontweight="bold", color=c)
        ax.text(x0 + w / 2, 0.9, t, ha="center", va="center", fontsize=7.3)
        if i < len(steps) - 1:
            ax.annotate("", xy=(x0 + w + 0.2, 1.1), xytext=(x0 + w + 0.02, 1.1),
                        arrowprops=dict(arrowstyle="-|>", color=GREY, lw=1.3))
    return save(fig, "fb_workflow.png")


def fig_side():
    r = 1.5; _, _, phi = geo(r, 0)
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.plot([-0.6, 2.25], [0, 0], color="k", lw=2)                               # floor
    for xx in [-0.55 + 0.12 * i for i in range(24)]:
        ax.plot([xx, xx - 0.07], [0, -0.06], color=GREY, lw=0.8)
    ax.plot([0, -0.22], [0.9, 0], color=GREY, lw=2); ax.plot([0, 0.22], [0.9, 0], color=GREY, lw=2)   # tripod
    ax.plot([0, 0], [0.9, 0.0], color=GREY, lw=1.2, ls=":")
    ax.add_patch(Rectangle((-0.03, H_BOARD - 0.085), 0.03, 0.17, fc=BLUE, ec="k"))                   # board (edge on)
    ax.text(-0.06, H_BOARD + 0.13, "SSL-16 board\n(vertical, sound-hole\nside faces the floor area)",
            ha="right", va="bottom", fontsize=8.5, color=BLUE)
    ax.plot(0, H_BOARD, "o", color=VERM, ms=6, zorder=5)
    ax.text(0.04, H_BOARD + 0.03, "array centre", fontsize=8.5, color=VERM)
    ax.add_patch(Rectangle((r - 0.05, 0), 0.10, 0.03, fc=ORANGE, ec="k"))                              # buzzer
    ax.text(r + 0.12, 0.06, "buzzer\n(on the floor)", ha="left", va="bottom", fontsize=8.5, color=ORANGE)
    ax.plot([0, r], [H_BOARD, 0.015], color=ORANGE, lw=1.5, ls="--")
    ax.plot([0, 0.9], [H_BOARD, H_BOARD], color=GREY, lw=0.8, ls=":")
    ax.add_patch(Arc((0, H_BOARD), 0.9, 0.9, theta1=phi, theta2=0, color=ORANGE, lw=1.3))
    ax.text(0.5, H_BOARD - 0.14, f"phi = {phi:.1f} deg\n(below the board)", fontsize=8.5, color=ORANGE)
    ax.annotate("", xy=(-0.42, H_BOARD), xytext=(-0.42, 0), arrowprops=dict(arrowstyle="<->", color="k"))
    ax.text(-0.45, H_BOARD / 2, "1.00 m", rotation=90, ha="right", va="center")
    ax.annotate("", xy=(r, -0.16), xytext=(0, -0.16), arrowprops=dict(arrowstyle="<->", color="k"))
    ax.text(r / 2, -0.2, "r = 1.50 m (or 2.00 m), measured on the floor from point O", ha="center", va="top")
    ax.text(0, -0.04, "O", ha="center", va="top", fontweight="bold")
    ax.text(-1.0, 0.45, "Operator stays\nBEHIND the board\n(at least 1 m)", fontsize=8.5, color=GREY, ha="center")
    ax.set_xlim(-1.35, 2.3); ax.set_ylim(-0.42, 1.65); ax.set_aspect("equal"); ax.axis("off")
    ax.set_title("Side view", fontsize=11, loc="left")
    return save(fig, "fb_side_view.png")


def fig_top():
    fig, ax = plt.subplots(figsize=(7.4, 6.4))
    # board at the top, facing DOWN the page: z grows downward (plotted as -z)
    ax.add_patch(Rectangle((-0.115, 0.02), 0.23, 0.04, fc=BLUE, ec="k"))
    ax.text(0.17, 0.05, "board (top edge seen from above)\nsound-hole side faces down this page",
            fontsize=8, color=BLUE, va="center")
    ax.plot(0, 0, "o", color=VERM, ms=6); ax.text(-0.16, -0.02, "O", ha="right", va="top", fontweight="bold")
    ax.plot([0, 0], [0, -2.25], color=GREY, lw=1, ls="--"); ax.text(0.04, -0.3, "0 deg line", fontsize=8, color=GREY)
    for R, ls in ((1.5, "-"), (2.0, ":")):
        t = [math.radians(a) for a in range(-70, 71)]
        ax.plot([R * math.sin(a) for a in t], [-R * math.cos(a) for a in t], color=SKY, lw=1, ls=ls)
        ax.text(R * math.sin(math.radians(72)), -R * math.cos(math.radians(72)), f"r = {R:.2f} m",
                fontsize=8, color=SKY, ha="left")
    for pid, R, th in POINTS:
        x, z, _ = geo(R, th)
        c = ORANGE if pid in ("F15_P30", "F15_M30") else GREEN
        ax.plot(x, -z, "o", ms=9, color=c, mec="k", zorder=5)
        ax.text(x, -z - 0.1, f"{pid}\n({x*100:+.0f}, {z*100:.0f}) cm", ha="center", va="top", fontsize=7.5)
    # how to measure one point: z first, then x
    x, z, _ = geo(1.5, 30)
    ax.annotate("", xy=(0, -z), xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color=VERM, lw=1.5))
    ax.annotate("", xy=(x, -z), xytext=(0, -z), arrowprops=dict(arrowstyle="-|>", color=VERM, lw=1.5))
    ax.text(-0.04, -z / 2, "1) z along\nthe 0 deg line", color=VERM, fontsize=8, ha="right")
    ax.text(x / 2, -z + 0.05, "2) x at 90 deg", color=VERM, fontsize=8, ha="center", va="bottom")
    ax.annotate("", xy=(1.0, -2.55), xytext=(-1.0, -2.55), arrowprops=dict(arrowstyle="-|>", color="k", lw=1.5))
    ax.text(0, -2.62, "+x  =  YOUR RIGHT when you stand in front of the board and face it\n"
                      "(stand at the bottom of this picture and look up the page)", ha="center", va="top", fontsize=8.5)
    ax.plot([], [], "o", color=ORANGE, mec="k", label="E0.5 orientation points")
    ax.plot([], [], "o", color=GREEN, mec="k", label="pilot points")
    ax.legend(loc="upper left", fontsize=8, frameon=False, bbox_to_anchor=(0.0, 0.93))
    ax.set_xlim(-2.05, 2.05); ax.set_ylim(-2.95, 0.25); ax.set_aspect("equal"); ax.axis("off")
    ax.set_title("Top view of the floor (board at the top)", fontsize=11, loc="left")
    return save(fig, "fb_top_view.png")


def fig_front():
    fig, ax = plt.subplots(figsize=(6, 3.6))
    ax.add_patch(Rectangle((0, 0), 2.3, 1.7, fc="#e8f1f8", ec=BLUE, lw=2))
    ax.text(1.15, 0.85, "sound-hole side of the board\n(the side the sound arrives at)", ha="center", va="center", color=BLUE)
    ax.add_patch(Rectangle((0.85, 1.62), 0.6, 0.16, fc=ORANGE, ec="k")); ax.text(1.15, 1.70, "UP", ha="center", va="center", fontweight="bold")
    ax.add_patch(Rectangle((2.22, 0.55), 0.16, 0.6, fc=ORANGE, ec="k")); ax.text(2.30, 0.85, "RIGHT", ha="center", va="center", rotation=90, fontweight="bold", fontsize=8)
    ax.annotate("", xy=(2.0, 0.3), xytext=(1.15, 0.3), arrowprops=dict(arrowstyle="-|>", color=VERM, lw=2)); ax.text(2.02, 0.3, "+x", color=VERM, va="center")
    ax.annotate("", xy=(0.14, 1.45), xytext=(0.14, 0.6), arrowprops=dict(arrowstyle="-|>", color=VERM, lw=2)); ax.text(0.14, 1.5, "+y", color=VERM, ha="center")
    ax.text(1.15, -0.15, "You are standing in front of the board, looking at it.  +z points from the board towards you.",
            ha="center", va="top", fontsize=8.5)
    ax.set_xlim(-0.2, 2.6); ax.set_ylim(-0.45, 1.9); ax.set_aspect("equal"); ax.axis("off")
    ax.set_title("Front view: tape labels on the board", fontsize=11, loc="left")
    return save(fig, "fb_board_front.png")


def fig_buzzer():
    fig, ax = plt.subplots(figsize=(6, 2.4))
    ax.plot([-0.2, 1.4], [0, 0], color="k", lw=2)
    a = math.radians(30); L, T = 0.22, 0.05
    p0 = (0.45, 0.0); d = (math.cos(a), math.sin(a)); nrm = (-math.sin(a), math.cos(a))
    p1 = (p0[0] + L * d[0], p0[1] + L * d[1])
    bx = p1[0] - 0.01                                                           # block under the raised end
    ax.add_patch(Rectangle((bx, 0), 0.12, p1[1], fc="#cccccc", ec="k"))
    ax.text(bx + 0.06, -0.03, "small block", ha="center", va="top", fontsize=8)
    quad = [p0, p1, (p1[0] + T * nrm[0], p1[1] + T * nrm[1]), (p0[0] + T * nrm[0], p0[1] + T * nrm[1])]
    ax.add_patch(Polygon(quad, closed=True, fc=ORANGE, ec="k"))
    hx, hy = p0[0] + 0.5 * L * d[0] + T * nrm[0], p0[1] + 0.5 * L * d[1] + T * nrm[1]
    ax.plot(hx, hy, "o", color="k", ms=4)
    tip = (hx + 0.45 * nrm[0], hy + 0.45 * nrm[1])
    ax.annotate("", xy=tip, xytext=(hx, hy), arrowprops=dict(arrowstyle="-|>", color=VERM, lw=1.5))
    ax.text(tip[0] - 0.02, tip[1] + 0.02, "towards the board", color=VERM, ha="right", fontsize=8.5)
    ax.text(0.85, 0.32, "Buzzer: sound hole (black dot) above the marked point,\nleaning on a block so the hole faces the board",
            fontsize=8.5, va="center")
    ax.set_xlim(-0.5, 2.3); ax.set_ylim(-0.12, 0.62); ax.set_aspect("equal"); ax.axis("off")
    return save(fig, "fb_buzzer.png")


def fig_e05_flow():
    fig, ax = plt.subplots(figsize=(8.5, 4.6)); ax.axis("off"); ax.set_xlim(0, 10); ax.set_ylim(0, 5.4)

    def box(x, y, w, h, t, c, bold=False):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.03,rounding_size=0.1", fc=c, ec="k", alpha=0.9))
        ax.text(x + w / 2, y + h / 2, t, ha="center", va="center", fontsize=8.5, fontweight="bold" if bold else "normal")

    def arr(x1, y1, x2, y2, t=""):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="-|>", color="k"))
        if t: ax.text((x1 + x2) / 2 + 0.08, (y1 + y2) / 2, t, fontsize=8, va="center")

    box(0.2, 4.3, 4.2, 0.9, "Settings: flip x OFF, flip y OFF, rotate 0\nMeasure F15_P30 and F15_M30 (3 x 5 s each)", "#dceefb")
    box(0.6, 2.85, 3.4, 0.9, "theta: + at F15_P30 and\n- at F15_M30 ?", "#fff1cc")
    box(0.6, 1.4, 3.4, 0.9, "phi negative at both\n(about -34 deg) ?", "#fff1cc")
    box(0.6, 0.0, 3.4, 0.85, "All within 10 deg of the table ?", "#fff1cc")
    box(5.6, 2.85, 3.6, 0.9, "Turn flip x ON\nand measure both again", "#f9d9c9")
    box(5.6, 1.4, 3.6, 0.9, "Turn flip y ON\nand measure both again", "#f9d9c9")
    box(5.6, 0.0, 1.7, 0.85, "PASS\nwrite settings", "#cdebdc", True)
    box(7.5, 0.0, 1.9, 0.85, "STOP\nsend the folder", "#e6e6e6", True)
    arr(2.3, 4.3, 2.3, 3.75)
    arr(2.3, 2.85, 2.3, 2.3, "yes"); arr(4.0, 3.3, 5.6, 3.3, "no")
    arr(2.3, 1.4, 2.3, 0.85, "yes"); arr(4.0, 1.85, 5.6, 1.85, "no")
    arr(4.0, 0.25, 5.6, 0.25, "yes")
    ax.annotate("", xy=(8.45, 0.85), xytext=(4.0, 0.62), arrowprops=dict(arrowstyle="-|>", color="k", connectionstyle="arc3,rad=-0.25"))
    ax.text(6.4, 1.05, "no", fontsize=8)
    ax.annotate("", xy=(4.4, 4.75), xytext=(9.2, 3.3), arrowprops=dict(arrowstyle="-|>", color=GREY, connectionstyle="arc3,rad=0.3", ls="--"))
    ax.annotate("", xy=(4.4, 4.6), xytext=(9.2, 1.85), arrowprops=dict(arrowstyle="-|>", color=GREY, connectionstyle="arc3,rad=0.35", ls="--"))
    ax.text(9.3, 4.4, "repeat", fontsize=8, color=GREY)
    return save(fig, "fb_e05_flow.png")


# ------------------------------------------------------------------ document helpers
def shade(cell, hex_fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd"); shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def table(doc, header, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(header)); t.style = "Table Grid"; t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]; c.text = ""; run = c.paragraphs[0].add_run(h); run.bold = True; shade(c, "D9E7F3")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = str(v)
    for r in t.rows:
        for i, c in enumerate(r.cells):
            for p in c.paragraphs:
                for run in p.runs: run.font.size = Pt(9.5)
            if widths: c.width = Cm(widths[i])
    doc.add_paragraph()
    return t


_num = {"n": 0}


def heading(doc, text, level):
    restart()
    return doc.add_heading(text, level)


def restart():
    _num["n"] = 0


def bullets(doc, items, style="List Bullet"):
    for it in items:
        if style == "List Number":                     # manual numbers: each list restarts at 1 after restart()
            _num["n"] += 1
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.9); p.paragraph_format.first_line_indent = Cm(-0.6)
            p.add_run(f"{_num['n']}.  ")
        else:
            p = doc.add_paragraph(style=style)
        if isinstance(it, tuple):
            p.add_run(it[0]).bold = True; p.add_run(it[1])
        else:
            p.add_run(it)


def note(doc, text, color="8A4B00"):
    p = doc.add_paragraph(); r = p.add_run(text); r.italic = True; r.font.color.rgb = RGBColor.from_string(color)


def code(doc, text):
    p = doc.add_paragraph(); r = p.add_run(text); r.font.name = "Consolas"; r.font.size = Pt(9)
    p.paragraph_format.left_indent = Cm(0.6)
    pPr = p._p.get_or_add_pPr(); shd = OxmlElement("w:shd"); shd.set(qn("w:val"), "clear"); shd.set(qn("w:fill"), "F2F2F2"); pPr.append(shd)


def picture(doc, path, width_cm, caption):
    doc.add_picture(path, width=Cm(width_cm)); doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph(caption); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for r in p.runs: r.italic = True; r.font.size = Pt(9)


# ------------------------------------------------------------------ build
def build():
    f_flow, f_side, f_top, f_front, f_buz, f_e05 = (fig_workflow(), fig_side(), fig_top(), fig_front(),
                                                     fig_buzzer(), fig_e05_flow())
    doc = Document()
    for s in doc.sections:
        s.left_margin = s.right_margin = Cm(2.0); s.top_margin = s.bottom_margin = Cm(1.8)
    doc.styles["Normal"].font.name = "Calibri"; doc.styles["Normal"].font.size = Pt(11)

    heading(doc, "SSL-16 Floor Bench: Lab Guide", 0)
    p = doc.add_paragraph(); p.add_run("Orientation check (E0.5) and pilot localization runs with buzzers on the floor").bold = True
    doc.add_paragraph("Version 1.0, 18 Nov 2026. HIVE Research Group, BUET. Internal lab document.")
    note(doc, "Status: the bench itself is a proposal (decision log #5). Whether these runs can be used as E1 data in the "
              "paper is Siam's decision. The firmware below passed the Day 0 recording checks on 17 Nov 2026. "
              "The campaign GUI was used with the board for the first time on 17 Nov 2026 and is still being checked.")

    heading(doc, "At a glance", 1)
    table(doc, ["What", "Use this", "Where"], [
        ["Firmware on the board", "SSL16_Rec48  (must show v1.2)", "firmware/arduino/SSL16_Rec48/SSL16_Rec48.ino"],
        ["Program on the PC", "Campaign GUI: ssl16_buzzer_gui.py", "software/python/ssl16_buzzer_gui.py"],
        ["Board height", "Array centre 1.00 m above the floor", "Section 3"],
        ["Sound source", "One buzzer at a time, on the floor", "Sections 3–4"],
        ["Points", "8 marked floor points (r = 1.5 m and 2.0 m)", "Section 3"],
        ["Time", "About 20 min to build, 45 min to measure", ""],
    ], widths=[3.6, 6.0, 7.4])
    picture(doc, f_flow, 16.5, "Figure 1. The whole session in six steps.")
    heading(doc, "Do NOT use these for this bench", 2)
    bullets(doc, [
        ("ssl16_recorder_gui.py  ", "(the 'SSL-16 WAV Recorder' window). It was only for the Day 0 recording tests. It has no known-position fields and no flip settings."),
        ("SSL16_Stream, SSL16_HDOA, SSL16_WavRecorder_v45  ", "firmware. They do not write the raw 48 kHz copy to the SD card."),
        ("The Arduino Serial Monitor  ", "while the GUI is running. Only one program can open the board's port."),
    ])

    heading(doc, "1. Things you need", 1)
    bullets(doc, ["SSL-16 board 1 on a tripod, USB-C cable to the PC, microSD card in the board",
                  "One buzzer (always the same one; write its name and frequency in the notes)",
                  "Tape measure (5 m), chalk or masking tape, a marker pen",
                  "Plumb line (a string with a small weight), a set square or a 3-4-5 triangle made of string",
                  "Thermometer (and a humidity meter / sound level meter if you have them)",
                  "A small block or book to lean the buzzer on"])

    heading(doc, "2. Software", 1)
    heading(doc, "2.1 Firmware: SSL16_Rec48 v1.2", 2)
    doc.add_paragraph("What it does: streams 16 channels at 12 kHz over USB for the live view, and at the same time writes the "
                      "raw 48 kHz audio of every run to the SD card. Upload it once; it stays on the board.")
    bullets(doc, ["Open firmware/arduino/SSL16_Rec48/SSL16_Rec48.ino in Arduino IDE 2 (File → Open). "
                  "Check that line 61 says SSL16_Rec48_v1.2. If it shows v1.0 or v1.1, close the tab and open the file again.",
                  "Tools menu settings:"], "List Number")
    table(doc, ["Setting", "Value"], [["Board", "ESP32S3 Dev Module"], ["USB CDC On Boot", "Enabled"],
                                      ["USB Mode", "Hardware CDC and JTAG"], ["PSRAM", "OPI PSRAM"],
                                      ["Flash Size", "8MB"], ["Upload Speed", "default; 115200 if the upload fails at 'Changing baud rate'"]],
          widths=[5, 8])
    bullets(doc, ["Put the board in download mode: hold BOOT, press and release EN, release BOOT.",
                  "Click Upload. When it says 'Hard resetting', press EN once. Without this the board stays silent.",
                  "Close the Arduino IDE Serial Monitor before starting the GUI."], "List Number")
    heading(doc, "2.2 PC program: campaign GUI", 2)
    doc.add_paragraph("Open PowerShell and run (change the Python path if your PC is different):")
    code(doc, 'cd "G:\\My Drive\\Research_2026\\SSL-16 Journal\\ssl16-acoustic-camera\\software\\python"\n'
              '& "C:\\Users\\HP\\AppData\\Local\\Programs\\Python\\Python313\\python.exe" ssl16_buzzer_gui.py')
    doc.add_paragraph("First time on a new PC, install the packages once:")
    code(doc, "python -m pip install numpy scipy matplotlib pyserial")

    heading(doc, "3. Build the bench", 1)
    picture(doc, f_side, 15.5, "Figure 2. Side view. The buzzer is on the floor, so the sound comes from about 34° below the board.")
    bullets(doc, [
        "Mount the board vertically on the tripod. The array centre (middle of the board) must be 1.00 m above the floor. "
        "The sound-hole side faces the open floor area.",
        "Choose the board's top edge and put a tape label UP on it. Stand in front of the board, facing it, and put a tape "
        "label RIGHT on the edge at your right hand (Figure 3). Take a photo. Always mount the board like this photo.",
        "Hang the plumb line from the array centre and mark point O on the floor directly below it.",
        "From O, draw the 0° line on the floor, straight forward and at 90° to the board face.",
        "Mark the 8 points of Table 1. For each point: measure z along the 0° line first, then measure x at 90° from the "
        "line (Figure 4). Positive x is to your right when you face the board. Label each mark with its point ID.",
    ], "List Number")
    picture(doc, f_front, 11.5, "Figure 3. Front view: where the UP and RIGHT labels go, and the +x / +y directions.")
    picture(doc, f_top, 15.0, "Figure 4. Top view of the floor with the 8 points. Orange points are used for the orientation check.")

    rows = []
    for pid, r, th in POINTS:
        x, z, phi = geo(r, th)
        rows.append([pid, f"{x*100:+.1f}", f"{z*100:.1f}", f"{r:.2f}", f"{th:+d}" if th else "0", f"{phi:.1f}"])
    doc.add_paragraph().add_run("Table 1. Floor points. The last four columns are what you type into the GUI and what it should show.").bold = True
    t = table(doc, ["Point ID", "x (cm)", "z (cm)", "GUI range r (m)", "GUI bearing θ (°)", "Expected φ (°)"], rows,
              widths=[2.6, 2.2, 2.2, 3.0, 3.2, 3.0])
    for i, (pid, _, _) in enumerate(POINTS, 1):
        if pid in ("F15_P30", "F15_M30"):
            for c in t.rows[i].cells: shade(c, "FCE8C8")
    _, _, phi3 = geo(1.5, 0, 0.03)
    bullets(doc, [("src h: ", "the height of the buzzer's sound hole above the floor. Measure it once (for example 0.02 m) "
                               "and use the same value for every point."),
                  ("board h: ", "always 1.00."),
                  ("Accuracy of marking: ", "1 cm of error moves the angle by only about 0.4° at 1.5 m, so a tape measure is enough. "
                                            f"Expected φ is for src h = 0; with 0.03 m it is {phi3:.1f}°.")])

    heading(doc, "4. Placing the buzzer", 1)
    picture(doc, f_buz, 11, "Figure 5. Lean the buzzer on a small block so that its hole faces the board.")
    bullets(doc, ["The buzzer's sound hole sits on the marked point.",
                  "Only one buzzer is on at a time. Use the same buzzer for every point.",
                  "Nothing between the buzzer and the board. No bags or boxes within 0.5 m of that path.",
                  "During a measurement: nobody talks or walks; the operator stays behind the board; fans off if possible "
                  "(if not, write it in the notes)."])

    heading(doc, "5. Set up the GUI", 1)
    heading(doc, "5.1 Connection & session", 2)
    bullets(doc, ["Press Refresh and choose the board's port: 'USB Serial Device' (COM3 on the HP lab PC). "
                  "Ports named 'Standard Serial over Bluetooth' are NOT the board. Leave Demo unticked.",
                  "Press Session… and fill it in, then press Start new session:"], "List Number")
    table(doc, ["Field", "What to type"], [
        ["base", "A folder OUTSIDE the git repository, e.g. G:\\My Drive\\Research_2026\\SSL-16 Journal\\ssl16_campaign"],
        ["room", "lab"], ["board", "board1"], ["operator", "your name"],
        ["humidity / background_dba", "from the meters, or leave empty"],
        ["firmware", "SSL16_Rec48_v1.2"],
        ["notes", "floor bench; board centre 1.00 m; buzzer name and frequency; src h; anything unusual"],
    ], widths=[4.5, 12.5])
    bullets(doc, ["Press Settings… and set:"], "List Number")
    table(doc, ["Setting", "Value"], [["flip x", "OFF (unticked) — until the orientation check says otherwise"],
                                      ["flip y", "OFF (unticked) — until the orientation check says otherwise"],
                                      ["rotate (deg)", "0"], ["air temp (C)", "the thermometer reading"],
                                      ["band low / band high (Hz)", "1500 / 5000"], ["detect SNR (dB)", "12"]], widths=[5, 12])
    bullets(doc, ["Press Connect. The status must turn green and show 'SSL6 12000 Hz | packets … | gaps 0'."], "List Number")
    heading(doc, "5.2 For every point", 2)
    table(doc, ["GUI panel", "Field", "Value"], [
        ["2. Known source position", "A camera", "selected"],
        ["", "range r, bearing θ", "from Table 1"],
        ["", "src h / board h", "your measured hole height / 1.00"],
        ["", "Set position", "press it; check the green line shows the θ and φ of Table 1"],
        ["3. Run labels", "exp", "E0 for the orientation check, E1 for pilot runs"],
        ["", "point", "the Point ID, e.g. F15_P30"],
        ["", "source", "the buzzer's name"],
        ["4. Measure", "s", "5"],
        ["", "Measure", "turn the buzzer on, wait 2 s, press Measure; do it 3 times per point"],
    ], widths=[4.2, 4.0, 8.8])

    heading(doc, "6. Orientation check (E0.5) — do this first", 1)
    doc.add_paragraph("The software takes the microphone positions from the PCB drawing. Because the microphones are on the "
                      "back of the board and the board can be mounted turned or upside down, the software's left/right or "
                      "up/down can be mirrored. This check finds that with two points and fixes it once.")
    picture(doc, f_e05, 15.5, "Figure 6. Orientation check: what to do with the result.")
    bullets(doc, [("F15_P30 (your right): ", "θ must be positive (about +30°)."),
                  ("F15_M30 (your left): ", "θ must be negative (about −30°)."),
                  ("Both points: ", "φ must be negative (about −34°)."),
                  ("Pass: ", "signs correct and every value within 10° of Table 1."),
                  ("If θ is reversed: ", "flip x ON and measure both again. If φ is positive: flip y ON and measure both again."),
                  ("If it still fails ", "(more than 20° off with every setting): stop and send the session folder. Do not try settings by guessing.")])
    note(doc, "After it passes, write flip x, flip y and rotate in the session notes. Never change them again for this "
              "board and mount. No pilot or E1 data is valid until this check has passed that day.")

    heading(doc, "7. Pilot runs", 1)
    bullets(doc, ["exp = E1 (or the name Siam chooses). All 8 points, 3 × 5 s each.",
                  "Press Shuffle order and measure the points in that random order, not left to right.",
                  "Measure F15_0 again after every 4 points (control point). If it moves by more than 1° from its first value, "
                  "stop and find what moved (board, tripod, buzzer).",
                  "If the GUI shows a warning after Measure (SD not confirmed, SD too slow, I2S overflow, low detections, "
                  "large spread): press Flag last bad and measure that point again."], "List Number")

    heading(doc, "8. End of the session", 1)
    bullets(doc, ["Close the GUI. Check the board LED is not blinking red (no recording running) before unplugging.",
                  "Copy everything in the SD card's /ssl16/ folder into the session folder, in a sub-folder named sd_raw. "
                  "Do not rename any file. Do not delete files from the card until the copy is checked.",
                  "Back up the whole session folder to a second place.",
                  "Send the session folder for checking (integrity, overflow count, accuracy per point)."], "List Number")

    heading(doc, "9. Checklist (print this page)", 1)
    for item in ["Firmware shows SSL16_Rec48_v1.2 in the GUI", "Board centre at 1.00 m, vertical, UP / RIGHT labels, photo taken",
                 "Point O and the 0° line marked; 8 points marked and labelled", "src h measured: ______ m   Air temp: ______ °C",
                 "Session started, base folder outside the repository", "Settings: flip x OFF, flip y OFF, rotate 0, band 1500–5000",
                 "Orientation check PASSED   flip x: ____  flip y: ____  rotate: ____",
                 "Pilot: 8 points × 3, shuffled order, control point every 4 points",
                 "No unflagged warnings", "SD /ssl16/ copied to sd_raw, backup made, folder sent"]:
        p = doc.add_paragraph(); p.add_run("☐  " + item)

    heading(doc, "10. Limits of this bench", 1)
    bullets(doc, ["All points are 27–34° below the board, so the horizontal angle (θ) and the vertical angle (φ) are always "
                  "tested together. The campaign plan's E1 puts the source at board height; this bench is different.",
                  "With a 2.5 kHz buzzer the array's main beam is about 50° wide (wavelength ÷ aperture), so room reflections "
                  "can spread the estimates. A 4 kHz buzzer narrows this to about 31°.",
                  "A flat array cannot tell front from back. All points are in front of the sound-hole side.",
                  "Open issue (17 Nov 2026): one campaign-GUI run showed I2S overflows (lost audio). Every run's .txt on the SD "
                  "card reports i2s_overflows_during_run; runs where it is not 0 are not valid data."])

    doc.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    build()
