"""ssl16_cam_calib.py recovers a known camera from a synthetic checkerboard video, and ssl16_video_overlay.Camera
projects exactly like OpenCV (same intrinsics and distortion)."""
import json
import math
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "software", "python"))
av = pytest.importorskip("av")
cv2 = pytest.importorskip("cv2")
import ssl16_cam_calib as cc  # noqa: E402
import ssl16_video_overlay as vo  # noqa: E402

W, H = 960, 540
K = np.array([[700.0, 0, 485.0], [0, 700.0, 265.0], [0, 0, 1]])
DIST = np.array([0.08, -0.15, 0.0, 0.0, 0.0])


def board_image(cols, rows, sq_px=60, margin=60):
    bw, bh = (cols + 1) * sq_px + 2 * margin, (rows + 1) * sq_px + 2 * margin
    img = np.full((bh, bw), 255, np.uint8)
    for i in range(cols + 1):
        for j in range(rows + 1):
            if (i + j) % 2 == 0:
                img[margin + j * sq_px: margin + (j + 1) * sq_px, margin + i * sq_px: margin + (i + 1) * sq_px] = 0
    return img, sq_px, margin


def render_view(board, sq_px, margin, square_m, rvec, tvec):
    """Warp the board picture into a camera view (with distortion) by projecting a dense pixel grid."""
    bh, bw = board.shape
    # board pixel (px, py) -> board plane metres, origin at the first inner corner
    s = square_m / sq_px
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    # invert: undistort each image pixel, intersect its ray with the board plane
    pts = cv2.undistortPoints(np.c_[xs.ravel(), ys.ravel()][:, None, :], K, DIST).reshape(-1, 2)
    R, _ = cv2.Rodrigues(rvec)
    n, d0 = R[:, 2], float(R[:, 2] @ tvec.ravel())
    rays = np.c_[pts, np.ones(len(pts))]
    lam = d0 / (rays @ n)
    P = rays * lam[:, None]
    Pb = (P - tvec.ravel()) @ R                                   # board frame
    u = (Pb[:, 0] / s + margin + sq_px).reshape(H, W).astype(np.float32)
    v = (Pb[:, 1] / s + margin + sq_px).reshape(H, W).astype(np.float32)
    return cv2.remap(board, u, v, cv2.INTER_LINEAR, borderValue=128)


def test_calibration_recovers_camera(tmp_path):
    cols, rows, square_m = 9, 6, 0.025
    board, sq_px, margin = board_image(cols, rows)
    rng = np.random.default_rng(1)
    path = os.path.join(str(tmp_path), "checker.mp4")
    out = av.open(path, "w"); st = out.add_stream("libx264", rate=30)
    st.width, st.height, st.pix_fmt = W, H, "yuv420p"
    st.options = {"crf": "12"}
    n = 0
    for k in range(40):
        rvec = np.array([rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5), rng.uniform(-0.3, 0.3)])
        tvec = np.array([rng.uniform(-0.12, 0.02), rng.uniform(-0.08, 0.0), rng.uniform(0.35, 0.6)])
        img = render_view(board, sq_px, margin, square_m, rvec, tvec)
        f = av.VideoFrame.from_ndarray(np.repeat(img[..., None], 3, 2), format="rgb24")
        for _ in range(2):
            f.pts = n; n += 1
            for p in st.encode(f): out.mux(p)
    for p in st.encode(): out.mux(p)
    out.close()
    c = cc.calibrate(path, cols, rows, square_m * 1000, every=2, verbose=False)
    assert c["n_views"] >= 15
    assert c["rms_px"] < 1.0
    assert abs(c["fx"] - K[0, 0]) / K[0, 0] < 0.02 and abs(c["fy"] - K[1, 1]) / K[1, 1] < 0.02
    assert abs(c["cx"] - K[0, 2]) < 15 and abs(c["cy"] - K[1, 2]) < 15


def test_camera_projection_matches_opencv():
    cam = vo.Camera(W, H, K[0, 0], K[1, 1], K[0, 2], K[1, 2], dist=DIST)
    rng = np.random.default_rng(0)
    Pc = np.c_[rng.uniform(-0.6, 0.6, 50), rng.uniform(-0.3, 0.3, 50), rng.uniform(1, 3, 50)]   # camera frame
    P_arr = Pc @ cam.R_ac.T                                        # same points in the array frame (no offset)
    uv = cam.project_array_points(P_arr)
    ref, _ = cv2.projectPoints(Pc, np.zeros(3), np.zeros(3), K, DIST)
    assert np.max(np.abs(uv - ref.reshape(-1, 2))) < 1e-6
    # pixel -> direction -> pixel round trip (through the undistortion)
    az, el = cam.pixel_directions(uv[:, 0], uv[:, 1], 2.0)
    d = np.c_[np.cos(np.radians(el)) * np.cos(np.radians(az)), np.cos(np.radians(el)) * np.sin(np.radians(az)),
              np.sin(np.radians(el))]
    uv2 = cam.project_array_points(2.0 * d)
    assert np.max(np.abs(uv2 - uv)) < 0.05
    # a source on the operator's right (+x) must appear on the LEFT half of the image
    assert cam.project_array_points(np.array([[0.5, 0.0, 2.0]]))[0, 0] < K[0, 2]
