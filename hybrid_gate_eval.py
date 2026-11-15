#!/usr/bin/env python
"""GridSentinel AI - hybrid gate experiment (NEW file; no existing file is modified).

Question: if a learned anomaly score (autoencoder trained on clean measurements) is added as one extra
feature to the Trust Gate, do the weaknesses found in robustness_eval.py shrink?
Gate A = the shipped gate (11 physics features). Gate H = the same gate + 1 feature (log10 autoencoder error).
IEEE 14, simulation only. Truth is used only for scoring."""
import argparse, json, os, warnings
import numpy as np
warnings.filterwarnings("ignore")
import batch_eval as be
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from gridsentinel_core import GateCalibration, GridModel, PipelineConfig, decide_level
from batch_eval import feats, errs, gen_cases
from robustness_eval import with_load, HEAVY

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", nargs="+", type=int, default=[7, 11, 13, 17, 19])
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--out", default="results_hybrid")
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    if a.quick: a.n, a.seeds = 60, [7]
    os.makedirs(a.out, exist_ok=True)
    cfg, model = PipelineConfig(), GridModel()
    res = {}
    for s in a.seeds:
        rng = np.random.default_rng(s)
        clean = gen_cases(model, cfg, a.n, rng, fixed_mode="none")
        Z = np.array([c["z"] for c in clean]); sc = StandardScaler().fit(Z); Zs = sc.transform(Z)
        ae = MLPRegressor(hidden_layer_sizes=(64, 16, 64), max_iter=400, random_state=0, early_stopping=True).fit(Zs, Zs)
        def aescore(cases):
            Zc = sc.transform(np.array([c["z"] for c in cases]))
            return np.log10(np.mean((ae.predict(Zc) - Zc) ** 2, axis=1) + 1e-12)
        aug = lambda cases: np.column_stack([feats(cases), aescore(cases)])
        tr = gen_cases(model, cfg, a.n, rng); ca = gen_cases(model, cfg, a.n, rng)
        calA = GateCalibration.fit(feats(tr), errs(tr), feats(ca), errs(ca), cfg.tol_pu, cfg.alpha)
        calH = GateCalibration.fit(aug(tr), errs(tr), aug(ca), errs(ca), cfg.tol_pu, cfg.alpha)
        tests = {
            "default mix": lambda: gen_cases(model, cfg, a.n, rng),
            "load range 0.6-1.4": lambda: with_load((0.6, 1.4), lambda: gen_cases(model, cfg, a.n, rng)),
            "90% adaptive / stealth-partial": lambda: gen_cases(model, cfg, a.n, rng, mix=HEAVY),
            "perfect stealth (out-of-model)": lambda: gen_cases(model, cfg, a.n, rng, fixed_mode="stealth_full"),
        }
        for tn, fn in tests.items():
            cases = fn(); E = errs(cases)
            for gn, cal, F in (("A: shipped gate (11 features)", calA, feats(cases)), ("H: hybrid gate (+ autoencoder score)", calH, aug(cases))):
                U = np.array([cal.bound(f, cfg.alpha) for f in F])
                conf = np.array([100 * cal.prob_within(f, cfg.tol_pu) for f in F])
                lv = np.array([decide_level(u, cf, c["res"].hard_fail, cfg)[0] for u, cf, c in zip(U, conf, cases)])
                pr = lv == "green"; unsafe = E > cfg.tol_pu
                res.setdefault((gn, tn), []).append({"cov": float(np.mean(E <= U)), "proceed": float(pr.mean()),
                    "unsafe_given_proceed": float(unsafe[pr].mean()) if pr.any() else float("nan")})
        print("seed", s, flush=True)
    f = lambda L, k: (lambda v: f"{np.nanmean(v):.3f} +/- {1.96*np.nanstd(v, ddof=1)/np.sqrt(max(len(v),1)):.3f}" if len(v) > 1 else f"{np.nanmean(v):.3f}")([d[k] for d in L])
    L = ["# Hybrid gate vs shipped gate (IEEE 14, simulation only)", "", f"seeds {a.seeds}, n = {a.n}. Mean +/- 95% CI. 'unsafe given PROCEED' is nan when the gate never says PROCEED.", "",
         "| Test set | Gate | Bound coverage (target 0.90) | PROCEED rate | Unsafe given PROCEED |", "|---|---|---|---|---|"]
    for tn in ("default mix", "load range 0.6-1.4", "90% adaptive / stealth-partial", "perfect stealth (out-of-model)"):
        for gn in ("A: shipped gate (11 features)", "H: hybrid gate (+ autoencoder score)"):
            v = res[(gn, tn)]; L.append(f"| {tn} | {gn} | {f(v,'cov')} | {f(v,'proceed')} | {f(v,'unsafe_given_proceed')} |")
    open(os.path.join(a.out, "results_hybrid.md"), "w").write("\n".join(L) + "\n")
    json.dump({f"{k[0]} | {k[1]}": v for k, v in res.items()}, open(os.path.join(a.out, "runs.json"), "w"), indent=1)
    print("\n".join(L))

if __name__ == "__main__":
    main()
