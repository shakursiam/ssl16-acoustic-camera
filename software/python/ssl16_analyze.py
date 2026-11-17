#!/usr/bin/env python3
"""
ssl16_analyze.py — offline analysis of SSL-16 test-campaign sessions (re-processes the saved raw WAVs).

Evening check of one day:
    python ssl16_analyze.py ssl16_campaign/2026-11-15_0930_lab_board1
Whole campaign, three algorithms, with channel calibration from the E0.3 broadside recording:
    python ssl16_analyze.py ssl16_campaign/* --methods srp,das,music --calib ssl16_campaign/<session>/E0/E0_CAL_r1_<time>.wav

Outputs (in --out, default ./analysis):
    points.csv    one row per run x method x calibration state
    summary.csv   one row per experiment x method x calibration state: bias, MAE (95% CI), RMSE, P95, detection
    E*_error.png  error vs the experiment's variable (mean +- std over reps), one line per source
    cdf_by_room.png, cdf_by_experiment.png, methods.png
Needs ssl16_core.py next to it.   pip install numpy matplotlib   (scipy optional, for Wilcoxon tests)
"""
import argparse, csv, glob, json, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from ssl16_core import (Locator, read_wav, wrap180, angular_error, azel_to_camera, estimate_calibration)

XVAR = {"E1": ("true_theta", "bearing θ (deg)"), "E2": ("true_phi", "vertical angle φ (deg)"),
        "E3": ("true_az", "azimuth α (deg)"), "E4": ("dist", "range (m)"), "E5": ("source", "source"),
        "E6": ("point", "SNR step (point ID)"), "E7": ("true_theta", "bearing θ (deg)"),
        "E8": ("true_theta", "bearing θ (deg)"), "E9": ("point", "point")}


def fnum(v, d=np.nan):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def analyse_run(meta, x, fs, method, calib):
    nfft = 2048 if fs <= 16000 else 4096
    loc = Locator(fs, nfft, band=(fnum(meta.get("band_lo"), 1500), fnum(meta.get("band_hi"), 5000)),
                  flip_x=str(meta.get("flip_x")) == "True", flip_y=str(meta.get("flip_y")) == "True",
                  rot=fnum(meta.get("rot_deg"), 0), temp_c=fnum(meta.get("temp_c"), 25), method=method,
                  delays_s=None if calib is None else calib[0])
    thr = fnum(meta.get("snr_thr"), 12)
    res = [loc.process(x[s:s + nfft]) for s in range(0, x.shape[0] - nfft + 1, nfft // 2)]
    det = [r for r in res if r["snr"] >= thr]
    T = meta
    out = dict(n_blocks=len(res), n_detect=len(det), detect_rate=len(det) / max(1, len(res)))
    if not det:
        return out, []
    az = np.array([r["az"] for r in det]); el = np.array([r["el"] for r in det])
    mv = np.mean(np.exp(1j * np.radians(az)))
    maz, mel = float(np.degrees(np.angle(mv))), float(el.mean())
    th, ph = azel_to_camera(maz, mel)
    taz, tel = fnum(T["true_az"]), fnum(T["true_el"])
    out.update(est_az=maz, est_el=mel, est_theta=th, est_phi=ph,
               az_err=float(wrap180(maz - taz)), ang_err=angular_error(taz, tel, maz, mel),
               theta_err=float(wrap180(th - fnum(T["true_theta"]))), phi_err=ph - fnum(T["true_phi"]),
               std_az=float(np.degrees(np.sqrt(max(0.0, -2 * np.log(min(abs(mv), 1.0) + 1e-12))))),
               snr_db=float(np.mean([r["snr"] for r in det])))
    block_err = [angular_error(taz, tel, r["az"], r["el"]) for r in det]
    return out, block_err


def main_err(row):
    return row.get("theta_err") if row["setup"] == "A" else (row.get("az_err") if row["setup"] == "B" else row.get("ang_err"))


def boot_ci(v, n=2000, seed=0):
    v = np.abs(np.asarray(v, float))
    if len(v) < 3: return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    m = [np.mean(rng.choice(v, len(v))) for _ in range(n)]
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sessions", nargs="+")
    ap.add_argument("--out", default="analysis")
    ap.add_argument("--methods", default="srp")
    ap.add_argument("--calib", help="broadside WAV from E0.3 (source at theta = 0, phi = 0)")
    ap.add_argument("--include-bad", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    sessions = [s for p in a.sessions for s in glob.glob(p) if os.path.isfile(os.path.join(s, "runs.csv"))]
    if not sessions:
        print("no session folders with runs.csv found"); return
    calib = None
    if a.calib:
        xc, fsc = read_wav(a.calib)
        calib = estimate_calibration(xc, fsc)
        print("calibration delays (us):", np.round(calib[0] * 1e6, 2).tolist())
        print("calibration gains (dB): ", np.round(20 * np.log10(calib[1]), 2).tolist())
    cal_states = [False, True] if calib is not None else [False]
    methods = [m.strip() for m in a.methods.split(",")]

    rows, cdf = [], {}
    for s in sorted(sessions):
        sess = json.load(open(os.path.join(s, "session.json"))) if os.path.exists(os.path.join(s, "session.json")) else {}
        runs = list(csv.DictReader(open(os.path.join(s, "runs.csv"))))
        print(f"{s}: {len(runs)} runs")
        for meta in runs:
            if meta["experiment"] == "E0" or (meta.get("flag") == "bad" and not a.include_bad):
                continue
            x, fs = read_wav(os.path.join(s, meta["wav"]))
            dist = float(np.sqrt(sum(fnum(meta[k], 0) ** 2 for k in ("x_m", "y_m", "z_m"))))
            for m in methods:
                for cs in cal_states:
                    res, berr = analyse_run(meta, x, fs, m, calib if cs else None)
                    row = dict(session=os.path.basename(s), room=sess.get("room", ""), board=sess.get("board", ""),
                               run_id=meta["run_id"], experiment=meta["experiment"], point=meta["point"], rep=meta["rep"],
                               setup=meta["setup"], source=meta["source"], dist=round(dist, 3), method=m, calibrated=cs,
                               **{k: fnum(meta[k]) for k in ("true_az", "true_el", "true_theta", "true_phi")}, **res)
                    rows.append(row)
                    cdf.setdefault((meta["experiment"], sess.get("room", ""), m, cs), []).extend(berr)

    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(os.path.join(a.out, "points.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)

    # ---- summary per experiment x method x calibration
    summ = []
    groups = sorted({(r["experiment"], r["method"], r["calibrated"]) for r in rows})
    for g in groups:
        rr = [r for r in rows if (r["experiment"], r["method"], r["calibrated"]) == g]
        e = np.array([main_err(r) for r in rr if main_err(r) is not None], float)
        ang = np.array([r["ang_err"] for r in rr if "ang_err" in r], float)
        lo, hi = boot_ci(e)
        summ.append(dict(experiment=g[0], method=g[1], calibrated=g[2], n_runs=len(rr), n_located=len(e),
                         bias=np.mean(e) if len(e) else np.nan, MAE=np.mean(np.abs(e)) if len(e) else np.nan,
                         MAE_CI_lo=lo, MAE_CI_hi=hi, RMSE=np.sqrt(np.mean(e ** 2)) if len(e) else np.nan,
                         P95=np.percentile(np.abs(e), 95) if len(e) else np.nan,
                         ang_MAE=np.mean(ang) if len(ang) else np.nan,
                         detect_rate=np.mean([r["detect_rate"] for r in rr])))
    with open(os.path.join(a.out, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summ[0].keys())); w.writeheader()
        w.writerows([{k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items()} for s in summ])
    print("\nexperiment method  cal   runs  bias   MAE  [95% CI]       RMSE   P95  3-D MAE  detect")
    for s in summ:
        print(f"{s['experiment']:10s} {s['method']:6s} {str(s['calibrated']):5s} {s['n_runs']:5d} {s['bias']:+6.2f} {s['MAE']:5.2f} "
              f"[{s['MAE_CI_lo']:4.2f}, {s['MAE_CI_hi']:4.2f}] {s['RMSE']:6.2f} {s['P95']:5.2f} {s['ang_MAE']:7.2f}  {100 * s['detect_rate']:5.1f}%")

    # ---- statistics: calibrated vs not, paired by run (needs scipy)
    try:
        from scipy.stats import wilcoxon
        for m in methods:
            if calib is None: break
            u = {r["run_id"]: abs(main_err(r)) for r in rows if r["method"] == m and not r["calibrated"] and main_err(r) is not None}
            c = {r["run_id"]: abs(main_err(r)) for r in rows if r["method"] == m and r["calibrated"] and main_err(r) is not None}
            ids = sorted(set(u) & set(c))
            if len(ids) >= 6:
                st = wilcoxon([u[i] for i in ids], [c[i] for i in ids])
                print(f"Wilcoxon calibrated vs uncalibrated ({m}, n={len(ids)}): p = {st.pvalue:.4f}, "
                      f"median |err| {np.median([u[i] for i in ids]):.2f} -> {np.median([c[i] for i in ids]):.2f} deg")
    except ImportError:
        pass

    # ---- figures (SRP-PHAT; calibrated if available)
    m0, c0 = methods[0], (calib is not None)
    for exp in sorted({r["experiment"] for r in rows}):
        rr = [r for r in rows if r["experiment"] == exp and r["method"] == m0 and r["calibrated"] == c0 and main_err(r) is not None]
        if not rr: continue
        xv, xlabel = XVAR.get(exp, ("true_theta", "angle"))
        fig, ax = plt.subplots(figsize=(7, 4))
        for src in sorted({r["source"] for r in rr}):
            sub = [r for r in rr if r["source"] == src]
            xs = sorted({r[xv] for r in sub}, key=lambda v: (isinstance(v, str), v))
            mean = [np.mean([main_err(r) for r in sub if r[xv] == v]) for v in xs]
            std = [np.std([main_err(r) for r in sub if r[xv] == v]) for v in xs]
            pos = np.arange(len(xs)) if isinstance(xs[0], str) else np.array(xs, float)
            ax.errorbar(pos, mean, yerr=std, marker="o", capsize=3, label=src)
            if isinstance(xs[0], str): ax.set_xticks(pos); ax.set_xticklabels(xs, rotation=30, ha="right")
        ax.axhline(0, color="0.6", lw=0.8)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("bearing error (deg)" if rr[0]["setup"] == "A" else "azimuth error (deg)")
        ax.set_title(f"{exp}: error vs {xlabel.split(' (')[0]} ({m0}{', calibrated' if c0 else ''}; mean ± std over reps)", fontsize=10)
        ax.grid(alpha=0.3); ax.legend(fontsize=8)
        fig.tight_layout(); fig.savefig(os.path.join(a.out, f"{exp}_error.png"), dpi=200); plt.close(fig)

    def cdf_plot(groupkey, fname, title):
        fig, ax = plt.subplots(figsize=(6, 4))
        merged = {}
        for (exp, room, m, cs), v in cdf.items():
            if m == m0 and cs == c0:
                merged.setdefault(groupkey(exp, room), []).extend(v)
        for k, v in sorted(merged.items()):
            v = np.sort(v)
            if len(v): ax.plot(v, np.arange(1, len(v) + 1) / len(v), label=f"{k} (n={len(v)})")
        ax.set_xlabel("3-D angular error per block (deg)"); ax.set_ylabel("cumulative fraction")
        ax.set_xlim(0, 30); ax.grid(alpha=0.3); ax.legend(fontsize=8); ax.set_title(title, fontsize=10)
        fig.tight_layout(); fig.savefig(os.path.join(a.out, fname), dpi=200); plt.close(fig)
    cdf_plot(lambda e, r: r or "room?", "cdf_by_room.png", "Error CDF by room")
    cdf_plot(lambda e, r: e, "cdf_by_experiment.png", "Error CDF by experiment")

    if len(methods) > 1 or calib is not None:
        fig, ax = plt.subplots(figsize=(7, 4))
        exps = sorted({s["experiment"] for s in summ})
        combos = [(m, cs) for m in methods for cs in cal_states]
        wdt = 0.8 / len(combos)
        for i, (m, cs) in enumerate(combos):
            v = [next((s["MAE"] for s in summ if s["experiment"] == e and s["method"] == m and s["calibrated"] == cs), np.nan) for e in exps]
            ax.bar(np.arange(len(exps)) + i * wdt, v, wdt, label=f"{m}{' cal' if cs else ''}")
        ax.set_xticks(np.arange(len(exps)) + 0.4 - wdt / 2); ax.set_xticklabels(exps)
        ax.set_ylabel("MAE (deg)"); ax.legend(fontsize=8); ax.grid(axis="y", alpha=0.3)
        ax.set_title("Method and calibration comparison (same recordings)", fontsize=10)
        fig.tight_layout(); fig.savefig(os.path.join(a.out, "methods.png"), dpi=200); plt.close(fig)
    print(f"\nwrote {a.out}/points.csv, summary.csv and figures")


if __name__ == "__main__":
    main()
