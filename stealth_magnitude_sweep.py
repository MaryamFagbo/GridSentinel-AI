#!/usr/bin/env python
"""GridSentinel AI - how small can a perfect-stealth attack be before the hybrid gate stops noticing it?
NEW file; no existing file is modified. IEEE 14, simulation only.
The attacker shifts the voltage at one bus by dV (per unit) with a measurement bias a = H c (chi-square unchanged).
Reported per dV: share of attacks whose recovered-state error exceeds tolerance (0.01 pu), PROCEED rate,
and the share of ALL attacks that are both accepted (PROCEED) and unsafe (joint risk), for gate A and gate H."""
import argparse, json, os, warnings
import numpy as np
warnings.filterwarnings("ignore")
import batch_eval as be
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from gridsentinel_core import GateCalibration, GridModel, PipelineConfig, decide_level
from batch_eval import feats, errs, gen_cases

_orig = be.apply_attack
def set_dv(dv):
    if dv is None:
        be.apply_attack = _orig
    else:
        be.apply_attack = lambda model, sc, mode, rng, cfg=None, **kw: _orig(model, sc, "custom_stealth" if mode == "stealth_full" else mode, rng, cfg, size=dv if mode == "stealth_full" else None, **kw)

ap = argparse.ArgumentParser()
ap.add_argument("--seeds", nargs="+", type=int, default=[7, 11, 13, 17, 19])
ap.add_argument("--n", type=int, default=200)
ap.add_argument("--out", default="results_stealth_sweep")
ap.add_argument("--quick", action="store_true")
a = ap.parse_args()
DVS = [0.005, 0.01, 0.02, 0.03, 0.05]
if a.quick: a.n, a.seeds, DVS = 40, [7], [0.01, 0.05]
os.makedirs(a.out, exist_ok=True)
cfg, model = PipelineConfig(), GridModel()
res = {}
for s in a.seeds:
    rng = np.random.default_rng(s)
    set_dv(None)
    clean = gen_cases(model, cfg, a.n * 2, rng, fixed_mode="none")
    Z = np.array([c["z"] for c in clean]); sc = StandardScaler().fit(Z); Zs = sc.transform(Z)
    ae = MLPRegressor(hidden_layer_sizes=(64, 16, 64), max_iter=400, random_state=0, early_stopping=True).fit(Zs, Zs)
    aescore = lambda cases: np.log10(np.mean((ae.predict(sc.transform(np.array([c["z"] for c in cases]))) - sc.transform(np.array([c["z"] for c in cases]))) ** 2, axis=1) + 1e-12)
    aug = lambda cases: np.column_stack([feats(cases), aescore(cases)])
    tr = gen_cases(model, cfg, a.n * 2, rng); ca = gen_cases(model, cfg, a.n * 2, rng)
    gates = {"A (shipped)": (GateCalibration.fit(feats(tr), errs(tr), feats(ca), errs(ca), cfg.tol_pu, cfg.alpha), feats),
             "H (hybrid)": (GateCalibration.fit(aug(tr), errs(tr), aug(ca), errs(ca), cfg.tol_pu, cfg.alpha), aug)}
    for dv in DVS:
        set_dv(dv)
        cases = gen_cases(model, cfg, a.n, rng, fixed_mode="stealth_full"); set_dv(None)
        E = errs(cases); unsafe = E > cfg.tol_pu
        for gn, (cal, fx) in gates.items():
            F = fx(cases); U = np.array([cal.bound(f, cfg.alpha) for f in F]); conf = np.array([100 * cal.prob_within(f, cfg.tol_pu) for f in F])
            pr = np.array([decide_level(u, cf, c["res"].hard_fail, cfg)[0] == "green" for u, cf, c in zip(U, conf, cases)])
            res.setdefault((dv, gn), []).append({"attack_unsafe": float(unsafe.mean()), "proceed": float(pr.mean()), "joint": float(np.mean(pr & unsafe))})
    print("seed", s, flush=True)
m = lambda L, k: float(np.mean([d[k] for d in L]))
L = ["# Perfect-stealth magnitude sweep (IEEE 14, simulation only)", "", f"seeds {a.seeds}, {a.n} attacks per magnitude per seed.", "",
     "dV = voltage shift forced on one bus by the attacker. 'Attack matters' = share of attacks whose recovered-state error exceeds 0.01 pu. 'Accepted and unsafe' = share of ALL attacks where the gate said PROCEED although the error exceeds tolerance.", "",
     "| dV (pu) | Gate | Attack matters (error > 0.01 pu) | PROCEED rate | Accepted and unsafe |", "|---|---|---|---|---|"]
for (dv, gn), v in res.items():
    L.append(f"| {dv} | {gn} | {m(v,'attack_unsafe'):.2f} | {m(v,'proceed'):.2f} | {m(v,'joint'):.2f} |")
open(os.path.join(a.out, "results_stealth_sweep.md"), "w").write("\n".join(L) + "\n")
json.dump({f"{k[0]} | {k[1]}": v for k, v in res.items()}, open(os.path.join(a.out, "runs.json"), "w"), indent=1)
print("\n".join(L))
