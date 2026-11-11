#!/usr/bin/env python
"""GridSentinel AI - multi-grid, multi-seed evaluation (NEW file; no existing file is modified).

Runs the SAME pipeline (no re-tuning) on IEEE 14 / 30 / 57 / 118 test systems from pandapower.
For each grid and each seed it builds its own train / calibration / test split, fits the
conformal trust gate on that grid, and scores it on held-out test scenarios.

How the grid is switched without touching gridsentinel_core.py:
    gridsentinel_core builds its network with pandapower.networks.case14(); here that
    function is temporarily pointed at the requested case. Nothing else changes.

Usage:
    python multi_grid_eval.py --cases case14 case30 case57 --n 150 --seeds 7 11 13 --out results_multigrid
    python multi_grid_eval.py --quick            # smoke test

SIMULATION ONLY: synthetic attacks on pandapower benchmark grids. Truth is used only for scoring.
"""
import argparse
import json
import os
import time
import warnings

import numpy as np

warnings.filterwarnings("ignore")

import pandapower.networks as pn  # noqa: E402

_ORIG = {c: getattr(pn, c) for c in ("case14", "case30", "case57", "case118") if hasattr(pn, c)}

from gridsentinel_core import GateCalibration, GridModel, PipelineConfig  # noqa: E402
from batch_eval import feats, errs, gen_cases, gate_metrics  # noqa: E402

ATTACK_TYPES = None  # use the repo's default in-model mix


def make_model(case):
    """Point core's case14() call at the requested grid, build the model, restore."""
    saved = pn.case14
    pn.case14 = _ORIG[case]
    try:
        return GridModel()
    finally:
        pn.case14 = saved


def ci95(x):
    x = np.asarray([v for v in x if v == v], float)
    if len(x) < 2:
        return float(x.mean()) if len(x) else float("nan"), float("nan")
    return float(x.mean()), float(1.96 * x.std(ddof=1) / np.sqrt(len(x)))


def one_run(case, seed, n, cfg):
    model = make_model(case)
    rng = np.random.default_rng(seed)
    t0 = time.time()
    tr = gen_cases(model, cfg, n, rng)
    ca = gen_cases(model, cfg, n, rng)
    te = gen_cases(model, cfg, n, rng)
    cal = GateCalibration.fit(feats(tr), errs(tr), feats(ca), errs(ca), cfg.tol_pu, cfg.alpha)
    gm = gate_metrics(cal, te, cfg)
    att = [c for c in te if c["mode"] != "none"]
    clean = [c for c in te if c["mode"] == "none"]
    hits = sum(c["hits"] for c in att)
    n_att = sum(c["n_att"] for c in att)
    out = {
        "case": case, "seed": seed, "n_test": len(te), "n_bus": model.nb,
        "bound_coverage": gm["bound_coverage"],
        "proceed_rate": gm["proceed_rate"],
        "unsafe_given_proceed": gm["unsafe_given_proceed"],
        "unsafe_proceed_joint": gm["unsafe_proceed_joint"],
        "unsafe_rate_all": gm["unsafe_rate_all"],
        "isolation_recall": hits / max(n_att, 1),
        "clean_false_alarm": float(np.mean([c["n_iso"] > 0 or c["res"].hard_fail for c in clean])) if clean else float("nan"),
        "n_clean": len(clean),
        "median_err_naive": float(np.median([c["err_plain"] for c in att])) if att else float("nan"),
        "median_err_recovered": float(np.median([c["err_rec"] for c in att])) if att else float("nan"),
        "median_ms_pipeline": float(np.median([c["ms"] for c in te])),
        "wall_s": time.time() - t0,
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", nargs="+", default=["case14", "case30", "case57"])
    ap.add_argument("--n", type=int, default=150, help="scenarios per split (train/cal/test)")
    ap.add_argument("--seeds", nargs="+", type=int, default=[7, 11, 13])
    ap.add_argument("--out", default="results_multigrid")
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    if a.quick:
        a.n, a.seeds = 40, [7]
    os.makedirs(a.out, exist_ok=True)
    cfg = PipelineConfig()
    rows = []
    for case in a.cases:
        for s in a.seeds:
            r = one_run(case, s, a.n, cfg)
            rows.append(r)
            print(f"{case} seed={s}: cov={r['bound_coverage']:.3f} proceed={r['proceed_rate']:.2f} "
                  f"unsafe|proceed={r['unsafe_given_proceed']:.3f} iso_rec={r['isolation_recall']:.2f} "
                  f"clean_FA={r['clean_false_alarm']:.2f} err {r['median_err_naive']:.4f}->{r['median_err_recovered']:.4f} "
                  f"{r['median_ms_pipeline']:.0f}ms/case wall={r['wall_s']:.0f}s", flush=True)
            with open(os.path.join(a.out, "runs.json"), "w") as f:
                json.dump(rows, f, indent=1)
    keys = ["bound_coverage", "proceed_rate", "unsafe_given_proceed", "unsafe_proceed_joint", "isolation_recall",
            "clean_false_alarm", "median_err_naive", "median_err_recovered", "median_ms_pipeline"]
    summ = {}
    for case in a.cases:
        rr = [r for r in rows if r["case"] == case]
        summ[case] = {"n_bus": rr[0]["n_bus"], "seeds": [r["seed"] for r in rr], "n_test_per_seed": rr[0]["n_test"]}
        for k in keys:
            m, h = ci95([r[k] for r in rr])
            summ[case][k] = {"mean": m, "ci95": h}
    with open(os.path.join(a.out, "summary.json"), "w") as f:
        json.dump(summ, f, indent=1)
    L = ["# Multi-grid results (simulation only)", "",
         f"n per split = {a.n}, seeds = {a.seeds}. Mean +/- 95% CI over seeds (small number of seeds: CI is rough).", "",
         "| Grid | Buses | Bound coverage (target 0.90) | PROCEED rate | Unsafe given PROCEED | Isolation recall | Clean false alarm | Median err naive -> recovered (pu) | ms/case |",
         "|---|---|---|---|---|---|---|---|---|"]
    f2 = lambda d: f"{d['mean']:.3f} +/- {d['ci95']:.3f}" if d['ci95'] == d['ci95'] else f"{d['mean']:.3f}"
    for case, s in summ.items():
        L.append(f"| {case} | {s['n_bus']} | {f2(s['bound_coverage'])} | {f2(s['proceed_rate'])} | {f2(s['unsafe_given_proceed'])} | "
                 f"{f2(s['isolation_recall'])} | {f2(s['clean_false_alarm'])} | "
                 f"{s['median_err_naive']['mean']:.4f} -> {s['median_err_recovered']['mean']:.4f} | {s['median_ms_pipeline']['mean']:.0f} |")
    open(os.path.join(a.out, "results_multigrid.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
