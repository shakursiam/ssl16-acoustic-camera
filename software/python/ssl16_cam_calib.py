"""
ssl16_cam_calib.py — phone camera intrinsics from a checkerboard video (for ssl16_video_overlay.py --calib).

Record ~30 s of a printed checkerboard with the SAME phone, lens (1x), resolution and settings as the real
runs (stabilisation off, focus locked). Move the board to every part of the image and tilt it.

    python ssl16_cam_calib.py checker.mp4 --cols 9 --rows 6 --square-mm 25 --out camera.json

--cols / --rows are the INNER corners (a board of 10 x 7 squares has 9 x 6 inner corners).
Writes camera.json: width, height, fx, fy, cx, cy, dist [k1 k2 p1 p2 k3], rms_px, n_views, hfov_deg.
A good calibration has rms_px below about 1 px and 15 or more views spread over the whole image.
Needs: numpy, av (PyAV), opencv-python (or opencv-python-headless).
"""
import argparse
import json
import math
import sys

import numpy as np


def frames_gray(path, every):
    import av
    with av.open(path) as c:
        st = c.streams.video[0]
        st.thread_type = "AUTO"
        for i, f in enumerate(c.decode(st)):
            if i % every == 0:
                yield f.to_ndarray(format="gray")


def calibrate(path, cols, rows, square_mm, every=10, max_views=60, verbose=True):
    import cv2
    objp = np.zeros((rows * cols, 3), np.float32)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * square_mm / 1000.0
    obj, img, size = [], [], None
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-3)
    flags = cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE
    tried = 0
    for g in frames_gray(path, every):
        tried += 1
        size = (g.shape[1], g.shape[0])
        ok, corners = cv2.findChessboardCorners(g, (cols, rows), flags)
        if not ok:
            continue
        corners = cv2.cornerSubPix(g, corners, (11, 11), (-1, -1), crit)
        obj.append(objp); img.append(corners)
    if len(obj) > max_views:                                      # keep views spread over the whole video
        keep = np.linspace(0, len(obj) - 1, max_views).round().astype(int)
        obj = [obj[i] for i in keep]; img = [img[i] for i in keep]
    if verbose:
        print(f"frames tried {tried}, checkerboard found in {len(obj)}")
    if len(obj) < 8:
        raise RuntimeError("too few checkerboard views (need >= 8; aim for 15+)")
    rms, K, dist, _, _ = cv2.calibrateCamera(obj, img, size, None, None)
    w, h = size
    out = dict(width=w, height=h, fx=float(K[0, 0]), fy=float(K[1, 1]), cx=float(K[0, 2]), cy=float(K[1, 2]),
               dist=[float(v) for v in dist.ravel()[:5]], rms_px=float(rms), n_views=len(obj),
               hfov_deg=float(2 * math.degrees(math.atan(w / (2 * K[0, 0])))), source=path)
    # coverage: fraction of a 4 x 4 grid of image cells that hold at least one detected corner
    pts = np.concatenate([c.reshape(-1, 2) for c in img])
    cells = {(int(4 * x / w), int(4 * y / h)) for x, y in pts}
    out["coverage_4x4"] = len(cells) / 16.0
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--cols", type=int, default=9); ap.add_argument("--rows", type=int, default=6)
    ap.add_argument("--square-mm", type=float, default=25.0)
    ap.add_argument("--every", type=int, default=10, help="use every N-th frame")
    ap.add_argument("--out", default="camera.json")
    a = ap.parse_args(argv)
    c = calibrate(a.video, a.cols, a.rows, a.square_mm, a.every)
    json.dump(c, open(a.out, "w"), indent=1)
    print(f"fx {c['fx']:.1f}  fy {c['fy']:.1f}  cx {c['cx']:.1f}  cy {c['cy']:.1f}  hfov {c['hfov_deg']:.1f} deg")
    print(f"dist {np.round(c['dist'], 4).tolist()}  rms {c['rms_px']:.3f} px  views {c['n_views']}  coverage {c['coverage_4x4']:.0%}")
    if c["rms_px"] > 1.0 or c["coverage_4x4"] < 0.75:
        print("WARNING: rms above 1 px or the board did not reach all parts of the image; record again.")
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
