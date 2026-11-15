#!/usr/bin/env python
"""GridSentinel AI - does calibrating on a pessimistic attack mix fix the coverage loss under attack-mix shift?
NEW file; no existing file is modified. IEEE 14, simulation only.
Gate A: calibrated on the default mix.  Gate B: calibrated on a pessimistic mix (45% adaptive, 45% stealth-partial, 10% clean).
Both are tested on the default mix, the pessimistic mix, and perfect-stealth (out-of-model) attacks."""
import argparse, json, os, warnings
import numpy as np
warnings.filterwarnings("ignore")
from gridsentinel_core import GateCalibration, GridModel, PipelineConfig
from batch_eval import feats, errs, gen_cases, gate_metrics

HEAVY = {"none": 0.10, "adaptive": 0.45, "stealth_partial": 0.45}
ap = argparse.ArgumentParser()
ap.add_argument("--seeds", nargs="+", type=int, default=[7, 11, 13, 17, 19])
ap.add_argument("--n", type=int, default=300)
ap.add_argument("--out", default="results_worstcase")
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
cfg, model = PipelineConfig(), GridModel()
res = {}
for s in a.seeds:
    rng = np.random.default_rng(s)
    cal = {}
    for name, mix in (("A: calibrated on default mix", None), ("B: calibrated on pessimistic mix", HEAVY)):
        tr = gen_cases(model, cfg, a.n, rng, mix=mix); ca = gen_cases(model, cfg, a.n, rng, mix=mix)
        cal[name] = GateCalibration.fit(feats(tr), errs(tr), feats(ca), errs(ca), cfg.tol_pu, cfg.alpha)
    tests = {"test: default mix": gen_cases(model, cfg, a.n, rng), "test: pessimistic mix": gen_cases(model, cfg, a.n, rng, mix=HEAVY),
             "test: perfect stealth (out-of-model)": gen_cases(model, cfg, a.n, rng, fixed_mode="stealth_full")}
    for cn, c in cal.items():
        for tn, cases in tests.items():
            g = gate_metrics(c, cases, cfg)
            res.setdefault((cn, tn), []).append({k: g[k] for k in ("bound_coverage", "proceed_rate", "unsafe_given_proceed")})
    print("seed", s, flush=True)
f = lambda L, k: (lambda v: f"{np.nanmean(v):.3f} +/- {1.96*np.nanstd(v, ddof=1)/np.sqrt(len(v)):.3f}")([d[k] for d in L])
L = ["# Worst-case calibration (IEEE 14, simulation only)", "", f"seeds {a.seeds}, n = {a.n}. Mean +/- 95% CI.", "",
     "| Gate | Test set | Bound coverage (target 0.90) | PROCEED rate | Unsafe given PROCEED |", "|---|---|---|---|---|"]
for (cn, tn), v in res.items():
    L.append(f"| {cn} | {tn} | {f(v,'bound_coverage')} | {f(v,'proceed_rate')} | {f(v,'unsafe_given_proceed')} |")
open(os.path.join(a.out, "results_worstcase.md"), "w").write("\n".join(L) + "\n")
json.dump({f"{k[0]} | {k[1]}": v for k, v in res.items()}, open(os.path.join(a.out, "runs.json"), "w"), indent=1)
print("\n".join(L))
