#!/usr/bin/env python
"""NEW: per-grid operating-tolerance tuning for a large grid, done on a VALIDATION split, reported once on a held-out TEST split.
Why: on 200 buses the max-over-buses voltage error of even a clean estimate is larger than on 14 buses, so the fixed 0.01 pu tolerance
is almost never certifiable. Bound U does not depend on tol; only the PROCEED/CAUTION decision and the 'unsafe' label do.
Usage: py -3.12 activsg_tune.py --pools pool_101.npz pool_202.npz --out results_activsg200_tuned"""
import argparse, json, os, numpy as np
from gridsentinel_core import GateCalibration, PipelineConfig, decide_level
ap = argparse.ArgumentParser(); ap.add_argument("--pools", nargs="+", required=True); ap.add_argument("--out", default="results_activsg200_tuned")
ap.add_argument("--splits", type=int, default=20); ap.add_argument("--min_proceed", type=float, default=0.10); ap.add_argument("--max_unsafe", type=float, default=0.10)
a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
P = [np.load(p, allow_pickle=True) for p in a.pools]
F = np.vstack([p["F"] for p in P]); E = np.concatenate([p["E"] for p in P]); Ep = np.concatenate([p["Ep"] for p in P])
mode = np.concatenate([p["mode"] for p in P]); hard = np.concatenate([p["hard"] for p in P]); n_iso = np.concatenate([p["n_iso"] for p in P])
N = len(E); clean = mode == "none"
TOLS = [0.008, 0.010, 0.012, 0.015, 0.020, 0.025, 0.030]
info = {"N": int(N), "n_clean": int(clean.sum()), "err_clean_pct(50,90,95)": [float(x) for x in np.percentile(E[clean], [50, 90, 95])],
        "err_all_pct(50,90)": [float(x) for x in np.percentile(E, [50, 90])], "clean_false_alarm_default": float(np.mean((n_iso[clean] > 0) | hard[clean]))}
print(info)

def evaluate(cal, idx, tol, cfg):
    cfg.tol_pu = tol
    U = np.array([cal.bound(F[i], cfg.alpha) for i in idx]); cf = np.array([100 * cal.prob_within(F[i], tol) for i in idx])
    lv = np.array([decide_level(u, c, hard[i], cfg)[0] for u, c, i in zip(U, cf, idx)])
    pr = lv == "green"; uns = E[idx] > tol
    return {"proceed": float(pr.mean()), "unsafe_given_proceed": float(uns[pr].mean()) if pr.any() else float("nan"),
            "coverage": float(np.mean(E[idx] <= U)), "unsafe_rate": float(uns.mean())}

rows, chosen = [], []
for s in range(a.splits):
    rng = np.random.default_rng(1000 + s); perm = rng.permutation(N)
    k = N // 5; tr, ca, va, te = perm[:2 * k], perm[2 * k:3 * k], perm[3 * k:4 * k], perm[4 * k:]
    cal = GateCalibration.fit(F[tr], E[tr], F[ca], E[ca], 0.01, 0.10)
    best = None
    for t in TOLS:
        v = evaluate(cal, va, t, PipelineConfig())
        if v["proceed"] >= a.min_proceed and v["unsafe_given_proceed"] <= a.max_unsafe: best = t; break
    t_use = best if best is not None else TOLS[-1]
    tst = evaluate(cal, te, t_use, PipelineConfig()); tst0 = evaluate(cal, te, 0.01, PipelineConfig())
    sweep = {str(t): evaluate(cal, te, t, PipelineConfig()) for t in TOLS}
    rows.append({"split": s, "chosen_tol": t_use, "found": best is not None, "test_tuned": tst, "test_default_tol": tst0, "test_sweep": sweep})
    chosen.append(t_use)

def agg(key, sub):
    v = [r[sub][key] for r in rows if r[sub][key] == r[sub][key]]; return (float(np.mean(v)), float(np.std(v))) if v else (float("nan"), float("nan"))
summ = {"info": info, "chosen_tol_values": {str(t): int(chosen.count(t)) for t in TOLS}, "found_in_splits": int(sum(r["found"] for r in rows)),
        "default_tol_0.01": {k: agg(k, "test_default_tol") for k in ["proceed", "unsafe_given_proceed", "coverage"]},
        "tuned_tol": {k: agg(k, "test_tuned") for k in ["proceed", "unsafe_given_proceed", "coverage"]},
        "sweep_mean": {str(t): {k: float(np.nanmean([r["test_sweep"][str(t)][k] for r in rows])) for k in ["proceed", "unsafe_given_proceed", "coverage"]} for t in TOLS}}
json.dump({"summary": summ, "rows": rows}, open(os.path.join(a.out, "tuning.json"), "w"), indent=1)
print(json.dumps(summ, indent=1))
