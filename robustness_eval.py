#!/usr/bin/env python
"""GridSentinel AI - robustness tests (NEW file; no existing file is modified).

1) Distribution shift: calibrate the gate on the default generator, then test it on
   shifted load ranges and shifted attack mixes. Reports how far coverage drops.
2) Deep-learning baseline: an autoencoder trained on clean measurements (reconstruction
   error as the alarm) versus GridSentinel, same test scenarios, detection only.

SIMULATION ONLY (IEEE 14, pandapower). Truth is used only for scoring.
Usage: python robustness_eval.py --seeds 7 11 13 17 19 --n 300 --out results_robustness
"""
import argparse, json, os, warnings
import numpy as np
warnings.filterwarnings("ignore")
import batch_eval as be
from gridsentinel_core import GateCalibration, GridModel, PipelineConfig, IN_MODEL_MIX
from batch_eval import feats, errs, gen_cases, gate_metrics, chi2_stats

_orig_ms = be.make_scenarios

def with_load(lr, fn):
    be.make_scenarios = lambda m, n, r: _orig_ms(m, n, r, load_range=lr)
    try:
        return fn()
    finally:
        be.make_scenarios = _orig_ms

HEAVY = {"none": 0.10, "adaptive": 0.45, "stealth_partial": 0.45}

def conds(model, cfg, n, rng):
    return {
        "in-distribution (control)": lambda: gen_cases(model, cfg, n, rng),
        "load range 0.6-1.4 (was 0.8-1.2)": lambda: with_load((0.6, 1.4), lambda: gen_cases(model, cfg, n, rng)),
        "attack mix: 90% adaptive/stealth-partial": lambda: gen_cases(model, cfg, n, rng, mix=HEAVY),
        "both shifts together": lambda: with_load((0.6, 1.4), lambda: gen_cases(model, cfg, n, rng, mix=HEAVY)),
        "out-of-model: stealth_full only": lambda: gen_cases(model, cfg, n, rng, fixed_mode="stealth_full"),
    }

def autoencoder_part(model, cfg, n, rng, test_cases, full_stealth=None):
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import StandardScaler
    clean_tr = gen_cases(model, cfg, n, rng, fixed_mode="none")
    clean_ca = gen_cases(model, cfg, n, rng, fixed_mode="none")
    Z = np.array([c["z"] for c in clean_tr]); sc = StandardScaler().fit(Z)
    ae = MLPRegressor(hidden_layer_sizes=(64, 16, 64), max_iter=400, random_state=0, early_stopping=True)
    Zs = sc.transform(Z); ae.fit(Zs, Zs)
    err = lambda z: float(np.mean((ae.predict(sc.transform(z[None, :]))[0] - sc.transform(z[None, :])[0]) ** 2))
    thr = float(np.quantile([err(c["z"]) for c in clean_ca], 0.95))
    rows = {"GridSentinel": {"tp": 0, "fn": 0, "fp": 0, "tn": 0}, "Autoencoder (clean-trained)": {"tp": 0, "fn": 0, "fp": 0, "tn": 0}}
    per = {}
    for c in test_cases:
        att = c["mode"] != "none"
        f = {"GridSentinel": c["res"].hard_fail or c["n_iso"] > 0,
             "Autoencoder (clean-trained)": err(c["z"]) > thr}
        for k, v in f.items():
            rows[k][("tp" if v else "fn") if att else ("fp" if v else "tn")] += 1
            if att:
                per.setdefault(c["mode"], {}).setdefault(k, []).append(bool(v))
    for c in (full_stealth or []):
        for k, v in {"GridSentinel": c["res"].hard_fail or c["n_iso"] > 0, "Autoencoder (clean-trained)": err(c["z"]) > thr}.items():
            per.setdefault("stealth_full (out-of-model)", {}).setdefault(k, []).append(bool(v))
    shifted = with_load((0.6, 1.4), lambda: gen_cases(model, cfg, n, rng, fixed_mode="none"))
    fa_shift = {"GridSentinel": float(np.mean([c["res"].hard_fail or c["n_iso"] > 0 for c in shifted])),
                "Autoencoder (clean-trained)": float(np.mean([err(c["z"]) > thr for c in shifted]))}
    out = {k: {"recall": d["tp"] / max(d["tp"] + d["fn"], 1), "false_alarm": d["fp"] / max(d["fp"] + d["tn"], 1)} for k, d in rows.items()}
    out["fa_load_shift"] = fa_shift
    out["per_mode_recall"] = {m: {k: float(np.mean(v)) for k, v in d.items()} for m, d in per.items()}
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", nargs="+", type=int, default=[7, 11, 13, 17, 19])
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--out", default="results_robustness")
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    if a.quick: a.n, a.seeds = 60, [7]
    os.makedirs(a.out, exist_ok=True)
    cfg = PipelineConfig(); model = GridModel()
    shift, ae_res = {}, []
    for s in a.seeds:
        rng = np.random.default_rng(s)
        tr = gen_cases(model, cfg, a.n, rng); ca = gen_cases(model, cfg, a.n, rng)
        cal = GateCalibration.fit(feats(tr), errs(tr), feats(ca), errs(ca), cfg.tol_pu, cfg.alpha)
        for name, fn in conds(model, cfg, a.n, rng).items():
            cases = fn(); gm = gate_metrics(cal, cases, cfg)
            shift.setdefault(name, []).append({k: gm[k] for k in ("bound_coverage", "proceed_rate", "unsafe_given_proceed", "unsafe_proceed_joint")})
            if name.startswith("in-distribution"):
                ae_res.append(autoencoder_part(model, cfg, a.n, rng, cases, gen_cases(model, cfg, a.n, rng, fixed_mode="stealth_full")))
        print("seed", s, "done", flush=True)
    m = lambda L, k: float(np.nanmean([d[k] for d in L]))
    ci = lambda L, k: float(1.96 * np.nanstd([d[k] for d in L], ddof=1) / np.sqrt(len(L))) if len(L) > 1 else float("nan")
    summ = {"shift": {n: {k: {"mean": m(L, k), "ci95": ci(L, k)} for k in L[0]} for n, L in shift.items()},
            "autoencoder": {k: {kk: {"mean": m([r[k] for r in ae_res], kk), "ci95": ci([r[k] for r in ae_res], kk)} for kk in ("recall", "false_alarm")}
                            for k in ("GridSentinel", "Autoencoder (clean-trained)")},
            "clean_false_alarm_load_shift": {k: {"mean": float(np.mean([r["fa_load_shift"][k] for r in ae_res])), "ci95": ci([{"v": r["fa_load_shift"][k]} for r in ae_res], "v")} for k in ("GridSentinel", "Autoencoder (clean-trained)")},
            "per_mode_recall": {mode: {k: float(np.mean([r["per_mode_recall"].get(mode, {}).get(k, np.nan) for r in ae_res])) for k in ("GridSentinel", "Autoencoder (clean-trained)")}
                                for mode in sorted({mm for r in ae_res for mm in r["per_mode_recall"]})},
            "seeds": a.seeds, "n": a.n}
    json.dump(summ, open(os.path.join(a.out, "summary.json"), "w"), indent=1)
    L = ["# Robustness results (IEEE 14, simulation only)", "", f"Gate calibrated on the default generator; seeds {a.seeds}, n = {a.n} per split. Mean +/- 95% CI.", "",
         "## 1. Distribution shift", "", "| Test condition | Bound coverage (target 0.90) | PROCEED rate | Unsafe given PROCEED |", "|---|---|---|---|"]
    f = lambda d: f"{d['mean']:.3f} +/- {d['ci95']:.3f}" if d['ci95'] == d['ci95'] else f"{d['mean']:.3f}"
    for n, d in summ["shift"].items():
        L.append(f"| {n} | {f(d['bound_coverage'])} | {f(d['proceed_rate'])} | {f(d['unsafe_given_proceed'])} |")
    L += ["", "## 2. Autoencoder baseline vs GridSentinel (detection only)", "", "| Method | Attack recall | False alarm on clean |", "|---|---|---|"]
    for k, d in summ["autoencoder"].items():
        L.append(f"| {k} | {f(d['recall'])} | {f(d['false_alarm'])} |")
    L += ["", "False alarm on CLEAN snapshots when the load range shifts to 0.6-1.4 (the autoencoder was trained on 0.8-1.2):", "", "| Method | False alarm on clean, shifted load |", "|---|---|"]
    for k, d in summ["clean_false_alarm_load_shift"].items():
        L.append(f"| {k} | {f(d)} |")
    L += ["", "Recall per attack type:", "", "| Attack | GridSentinel | Autoencoder |", "|---|---|---|"]
    for mode, d in summ["per_mode_recall"].items():
        L.append(f"| {mode} | {d['GridSentinel']:.2f} | {d['Autoencoder (clean-trained)']:.2f} |")
    open(os.path.join(a.out, "results_robustness.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))

if __name__ == "__main__":
    main()
