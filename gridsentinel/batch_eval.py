#!/usr/bin/env python
"""GridSentinel AI - batch evaluation (reproducible numbers for the booth / Q&A).

Usage:
    python batch_eval.py --n 300 --seed 7 --out results          # full run
    python batch_eval.py --quick --out results_quick             # smoke test (~ few minutes)
    python batch_eval.py --n 300 --no-ablation

Everything here is SIMULATION on the IEEE 14-bus system with synthetic attacks.
Truth (x_true) is used ONLY to score results - never inside run_pipeline().
Outputs (in --out): results.csv, results_summary.md, summary.json, gate_calibration.json,
                    plots: calibration.png, risk_coverage.png, error_before_after.png, ablation.png
"""
import argparse
import json
import os
import time
import warnings

import numpy as np

warnings.filterwarnings("ignore")

from gridsentinel_core import (  # noqa: E402
    IN_MODEL_MIX, FEATURE_NAMES, GateCalibration, GridModel, PipelineConfig,
    apply_attack, decide_level, hardening_plan, limit_violations, make_scenarios,
    run_pipeline, true_error,
)

TYPES = list(IN_MODEL_MIX)


# --------------------------------------------------------------------------- data generation
def gen_cases(model, cfg, n, rng, mix=None, protected=None, keep_z=False, fixed_mode=None):
    """Attack -> LIVE pipeline (z only) -> record truth-based scores separately."""
    mix = mix or IN_MODEL_MIX
    modes = list(mix)
    p = np.array([mix[k] for k in modes], float)
    p /= p.sum()
    out = []
    for sc in make_scenarios(model, n, rng):
        mode = fixed_mode or str(rng.choice(modes, p=p))
        z, info = apply_attack(model, sc, mode, rng, cfg, protected=protected)
        res = run_pipeline(model, z, cfg)
        Vt, _ = model.unpack(sc.x_true)
        att = set(int(i) for i in info.idx)
        iso = set(int(i) for i in res.iso_idx)
        out.append({
            "mode": mode, "z": z if keep_z else None, "res": res,
            "err_rec": true_error(model, sc.x_true, res.rec_V),
            "err_plain": true_error(model, sc.x_true, res.plain_V),
            "err_huber": true_error(model, sc.x_true, res.huber_V),
            "n_att": len(att), "hits": len(att & iso), "n_iso": len(iso), "false_iso": len(iso - att),
            "wrong_rec": limit_violations(res.rec_V, cfg.v_limits) != limit_violations(Vt, cfg.v_limits),
            "wrong_naive": limit_violations(res.plain_V, cfg.v_limits) != limit_violations(Vt, cfg.v_limits),
            "z": z, "Vt": Vt, "ms": res.ms,
        })
    return out


def feats(cases):
    return np.array([c["res"].fvec for c in cases])


def errs(cases):
    return np.array([c["err_rec"] for c in cases])


# --------------------------------------------------------------------------- baselines
def chi2_stats(model, z, res):
    """Plain-WLS chi-square and largest normalized residual (the textbook detectors)."""
    from scipy.stats import chi2
    fit = model.wls(z, model.avail)
    ana = model.analyze(z, fit.x, model.avail)
    r = (z - model.h(fit.x)) / model.sigma
    J = float(np.sum(r[model.avail] ** 2))
    dof = int(model.avail.sum() - len(fit.x))
    return J > chi2.ppf(0.99, dof), float(np.max(np.abs(ana.rN[~ana.crit]))) if (~ana.crit).any() else 0.0


def detection_table(model, cases, iforest):
    rows = {}
    for name in ("GridSentinel (flags/isolates)", "WLS + chi-square", "WLS + LNR (>3)", "IsolationForest (raw z)"):
        rows[name] = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for c in cases:
        attacked = c["mode"] != "none"
        res = c["res"]
        chi_flag, lnr = chi2_stats(model, c["z"], res)
        flags = {
            "GridSentinel (flags/isolates)": res.hard_fail or c["n_iso"] > 0,
            "WLS + chi-square": bool(chi_flag),
            "WLS + LNR (>3)": lnr > 3.0,
            "IsolationForest (raw z)": bool(iforest.predict(c["z"][None, :])[0] == -1) if iforest is not None else False,
        }
        for k, f in flags.items():
            key = ("tp" if f else "fn") if attacked else ("fp" if f else "tn")
            rows[k][key] += 1
    out = {}
    for k, d in rows.items():
        prec = d["tp"] / max(d["tp"] + d["fp"], 1)
        rec = d["tp"] / max(d["tp"] + d["fn"], 1)
        out[k] = {"precision": prec, "recall": rec, "f1": 2 * prec * rec / max(prec + rec, 1e-9),
                  "fpr": d["fp"] / max(d["fp"] + d["tn"], 1)}
    return out


# --------------------------------------------------------------------------- gate metrics
def gate_metrics(cal, cases, cfg):
    F = feats(cases)
    E = errs(cases)
    U = np.array([cal.bound(f, cfg.alpha) for f in F])
    conf = np.array([100 * cal.prob_within(f, cfg.tol_pu) for f in F])
    levels = np.array([decide_level(u, cf, c["res"].hard_fail, cfg)[0] for u, cf, c in zip(U, conf, cases)])
    proceed = levels == "green"
    unsafe = E > cfg.tol_pu
    wrong = np.array([c["wrong_rec"] for c in cases])
    cov_bound = float(np.mean(E <= U))
    return {
        "n": len(cases),
        "proceed_rate": float(proceed.mean()),
        "caution_rate": float((levels == "yellow").mean()),
        "validate_rate": float((levels == "red").mean()),
        "unsafe_given_proceed": float(unsafe[proceed].mean()) if proceed.any() else float("nan"),
        "unsafe_proceed_joint": float(np.mean(proceed & unsafe)),
        "wrong_action_given_proceed": float(wrong[proceed].mean()) if proceed.any() else float("nan"),
        "bound_coverage": cov_bound,
        "unsafe_rate_all": float(unsafe.mean()),
        "per_type": {t: {"n": int(sum(c["mode"] == t for c in cases)),
                         "proceed": float(np.mean([p for p, c in zip(proceed, cases) if c["mode"] == t] or [np.nan])),
                         "unsafe_proceed": float(np.mean([(p and u) for p, u, c in zip(proceed, unsafe, cases) if c["mode"] == t] or [np.nan]))}
                     for t in sorted(set(c["mode"] for c in cases))},
        "_U": U, "_E": E, "_proceed": proceed, "_unsafe": unsafe,
    }


def risk_coverage(score, unsafe):
    """Accept cases from lowest score (most trusted) upward. Returns coverage, selective risk, AURC."""
    order = np.argsort(score)
    u = unsafe[order].astype(float)
    k = np.arange(1, len(u) + 1)
    risk = np.cumsum(u) / k
    cov = k / len(u)
    return cov, risk, float(np.mean(risk))


# --------------------------------------------------------------------------- plots
def make_plots(out, cal_stats, rc, before_after, ablation):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    E, U = cal_stats["_E"], cal_stats["_U"]
    fin = np.isfinite(U)
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.loglog(np.maximum(U[fin], 1e-5), np.maximum(E[fin], 1e-5), ".", alpha=0.4, ms=4)
    lim = [1e-5, 1]
    ax.plot(lim, lim, "k--", lw=1, label="error = bound")
    ax.axhline(0.01, color="r", lw=0.8, ls=":")
    ax.set_xlabel("Calibrated bound U (pu)")
    ax.set_ylabel("True max voltage error (pu)")
    ax.set_title(f"Calibration: {100 * cal_stats['bound_coverage']:.1f}% of cases under the bound (target >= 90%)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(out, "calibration.png"), dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6, 4.5))
    for name, (cov, risk, aurc) in rc.items():
        ax.plot(cov, risk, label=f"{name} (AURC {aurc:.3f})")
    ax.set_xlabel("Coverage (fraction of cases auto-accepted)")
    ax.set_ylabel("Unsafe rate among accepted")
    ax.set_title("Risk-coverage: lower is better")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "risk_coverage.png"), dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    ts = list(before_after)
    x = np.arange(len(ts))
    ax.bar(x - 0.2, [before_after[t][0] for t in ts], 0.4, label="Naive WLS")
    ax.bar(x + 0.2, [before_after[t][1] for t in ts], 0.4, label="GridSentinel recovered")
    ax.axhline(0.01, color="r", ls=":", lw=0.8)
    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(ts, rotation=25, ha="right", fontsize=8)
    ax.set_ylabel("Median max voltage error (pu)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(out, "error_before_after.png"), dpi=140)
    plt.close(fig)

    if ablation:
        fig, ax = plt.subplots(figsize=(7, 4))
        names = list(ablation)
        ax.bar(range(len(names)), [ablation[k]["p90"] for k in names])
        ax.set_xticks(range(len(names)))
        ax.set_xticklabels(names, rotation=25, ha="right", fontsize=8)
        ax.set_yscale("log")
        ax.set_ylabel("90th percentile max voltage error (pu)")
        ax.set_title("Ablation: what each component buys")
        fig.tight_layout()
        fig.savefig(os.path.join(out, "ablation.png"), dpi=140)
        plt.close(fig)


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300, help="scenarios per split (train / calibration / test)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="results")
    ap.add_argument("--quick", action="store_true", help="small run for a smoke test")
    ap.add_argument("--no-ablation", action="store_true")
    a = ap.parse_args()
    n = 80 if a.quick else a.n
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    cfg = PipelineConfig()
    model = GridModel()
    rng = np.random.default_rng(a.seed)
    log = lambda s: print(f"[{time.time() - t0:6.0f}s] {s}", flush=True)

    # ---- deployed grid
    log(f"generating train/cal/test ({n} each) for the deployed grid")
    tr = gen_cases(model, cfg, n, rng)
    ca = gen_cases(model, cfg, n, rng)
    te = gen_cases(model, cfg, n, rng)
    cal = GateCalibration.fit(feats(tr), errs(tr), feats(ca), errs(ca), cfg.tol_pu, cfg.alpha)
    with open(os.path.join(a.out, "gate_calibration.json"), "w") as f:
        f.write(cal.to_json())
    gm = gate_metrics(cal, te, cfg)
    log(f"deployed: proceed {gm['proceed_rate']:.2f}, unsafe|proceed {gm['unsafe_given_proceed']:.3f}, bound cov {gm['bound_coverage']:.3f}")

    # ---- hardened grid (5 protected meters)
    plan = hardening_plan(model)
    mask = np.zeros(model.m, bool)
    mask[[i for i, _, _ in plan]] = True
    log(f"hardened grid: protecting {len(plan)} meters")
    htr = gen_cases(model, cfg, n, rng, protected=mask)
    hca = gen_cases(model, cfg, n, rng, protected=mask)
    hte = gen_cases(model, cfg, n, rng, protected=mask)
    hcal = GateCalibration.fit(feats(htr), errs(htr), feats(hca), errs(hca), cfg.tol_pu, cfg.alpha)
    hm = gate_metrics(hcal, hte, cfg)
    log(f"hardened: proceed {hm['proceed_rate']:.2f}, unsafe|proceed {hm['unsafe_given_proceed']:.3f}")

    # ---- out-of-model stealth_full (limit of the method)
    sf = gen_cases(model, cfg, max(n // 3, 30), rng, fixed_mode="stealth_full")
    sfm = gate_metrics(cal, sf, cfg)
    sf_h = gen_cases(model, cfg, max(n // 3, 30), rng, fixed_mode="stealth_full", protected=mask)
    sfm_h = gate_metrics(hcal, sf_h, cfg)

    # ---- baselines: detection
    iforest = None
    try:
        from sklearn.ensemble import IsolationForest
        clean = [sc.z_clean for sc in make_scenarios(model, n, rng)]
        iforest = IsolationForest(n_estimators=200, contamination=0.01, random_state=a.seed).fit(np.array(clean))
    except Exception as e:  # sklearn missing
        log(f"IsolationForest skipped ({e})")
    det = detection_table(model, te, iforest)

    # ---- recovery error: before vs after, per attack type
    before_after, rows = {}, []
    for t in TYPES:
        cs = [c for c in te if c["mode"] == t]
        if not cs:
            continue
        ep = np.array([c["err_plain"] for c in cs])
        eh = np.array([c["err_huber"] for c in cs])
        er = np.array([c["err_rec"] for c in cs])
        before_after[t] = (float(np.median(ep)), float(np.median(er)))
        na = sum(c["n_att"] for c in cs)
        hits = sum(c["hits"] for c in cs)
        niso = sum(c["n_iso"] for c in cs)
        rows.append({
            "attack": t, "n": len(cs),
            "rmse_naive_pu": float(np.sqrt(np.mean(ep ** 2))), "rmse_huber_pu": float(np.sqrt(np.mean(eh ** 2))),
            "rmse_recovered_pu": float(np.sqrt(np.mean(er ** 2))),
            "median_naive_pu": float(np.median(ep)), "median_recovered_pu": float(np.median(er)),
            "p90_recovered_pu": float(np.quantile(er, 0.9)),
            "iso_recall": hits / na if na else float("nan"), "iso_precision": hits / niso if niso else float("nan"),
            "wrong_action_naive": float(np.mean([c["wrong_naive"] for c in cs])),
            "wrong_action_recovered": float(np.mean([c["wrong_rec"] for c in cs])),
            "proceed_rate": gm["per_type"][t]["proceed"], "unsafe_proceed": gm["per_type"][t]["unsafe_proceed"],
        })

    # ---- risk-coverage vs baselines (selector = score; lower = more trusted)
    E = gm["_E"]
    unsafe = E > cfg.tol_pu
    Fte = feats(te)
    j_raw = Fte[:, FEATURE_NAMES.index("log_J_raw")]
    rc = {
        "GridSentinel gate": risk_coverage(gm["_U"], unsafe),
        "chi-square (raw J)": risk_coverage(j_raw, unsafe),
        "always-proceed": (np.array([1.0]), np.array([unsafe.mean()]), float(unsafe.mean())),
    }

    # ---- ablations (recovery error, 90th percentile, on the same attack mix)
    ablation = {}
    if not a.no_ablation:
        log("ablations")
        variants = {
            "Full GridSentinel": (model, cfg),
            "No trust weighting": (model, PipelineConfig(use_trust=False)),
            "No observability guard": (model, PipelineConfig(use_obs_guard=False)),
            "Basic meter set (no flows)": (GridModel("basic"), cfg),
        }
        for name, (m, c) in variants.items():
            cs = gen_cases(m, c, max(n, 100), np.random.default_rng(a.seed + 100))
            e = np.array([x["err_rec"] for x in cs])
            ablation[name] = {"median": float(np.median(e)), "p90": float(np.quantile(e, 0.9)),
                              "naive_p90": float(np.quantile([x["err_plain"] for x in cs], 0.9)),
                              "iso_recall": sum(x["hits"] for x in cs) / max(sum(x["n_att"] for x in cs), 1),
                              "false_iso": sum(x["false_iso"] for x in cs) / len(cs)}
        # always-proceed ("no gate")
        ablation["No gate (always proceed)"] = {"unsafe_rate": float(unsafe.mean()), "p90": ablation["Full GridSentinel"]["p90"]}

    runtime = {"median_ms": float(np.median([c["ms"] for c in te])), "p95_ms": float(np.quantile([c["ms"] for c in te], 0.95))}

    # ---- outputs
    import csv
    with open(os.path.join(a.out, "results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    make_plots(a.out, gm, rc, before_after, ablation)

    strip = lambda d: {k: v for k, v in d.items() if not k.startswith("_")}
    summary = {"seed": a.seed, "n_per_split": n, "deployed": strip(gm), "hardened": strip(hm),
               "stealth_full_deployed": strip(sfm), "stealth_full_hardened": strip(sfm_h),
               "detection": det, "per_attack": rows, "ablation": ablation, "runtime_ms": runtime,
               "aurc": {k: v[2] for k, v in rc.items()}, "protected_meters": [p[1] for p in plan],
               "alpha": cfg.alpha, "tol_pu": cfg.tol_pu}
    with open(os.path.join(a.out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=float)

    P = lambda x: f"{100 * x:.1f}%" if np.isfinite(x) else "n/a"
    md = [f"# GridSentinel AI - batch evaluation (seed {a.seed}, {n} scenarios per split)",
          "", "Simulation on IEEE 14-bus (122 AC measurements). Synthetic attacks, attacker budget K_MAX=8 meters. "
          "Truth is used only to score results.", "",
          "## Headline (deployed grid, in-model attacks)",
          f"- Gate target: P(max voltage error <= {cfg.tol_pu} pu) >= {100 * (1 - cfg.alpha):.0f}% per bound",
          f"- Bound coverage on held-out test: **{P(gm['bound_coverage'])}**",
          f"- PROCEED share: **{P(gm['proceed_rate'])}**; unsafe among PROCEED: **{P(gm['unsafe_given_proceed'])}**; "
          f"unsafe-PROCEED over all cases: **{P(gm['unsafe_proceed_joint'])}** (always-proceed would be {P(gm['unsafe_rate_all'])})",
          f"- Wrong voltage-limit action among PROCEED: {P(gm['wrong_action_given_proceed'])}",
          f"- Runtime per snapshot: median {runtime['median_ms']:.0f} ms, p95 {runtime['p95_ms']:.0f} ms",
          "", "## Hardened grid (5 protected meters: " + ", ".join(p[1] for p in plan) + ")",
          f"- PROCEED {P(hm['proceed_rate'])}; unsafe among PROCEED {P(hm['unsafe_given_proceed'])}; bound coverage {P(hm['bound_coverage'])}",
          "", "## Limit: out-of-model full stealth (attacker controls the whole stealth support)",
          f"- Deployed: unsafe rate {P(sfm['unsafe_rate_all'])}, PROCEED {P(sfm['proceed_rate'])}, unsafe-PROCEED {P(sfm['unsafe_proceed_joint'])}",
          f"- Hardened: unsafe rate {P(sfm_h['unsafe_rate_all'])}, PROCEED {P(sfm_h['proceed_rate'])}, unsafe-PROCEED {P(sfm_h['unsafe_proceed_joint'])}",
          "- Out-of-model: the attacker controls far more than K_MAX meters. Perfect stealth leaves every residual unchanged, so no estimator-side method can detect it; "
          "the guarantee holds only inside the stated attacker budget. Hardening did NOT fix this case in our tests - we report the number as measured.",
          "", "## Detection vs baselines (attacked vs clean, deployed test set)",
          "| Method | Precision | Recall | F1 | FPR |", "|---|---|---|---|---|"]
    md += [f"| {k} | {P(v['precision'])} | {P(v['recall'])} | {P(v['f1'])} | {P(v['fpr'])} |" for k, v in det.items()]
    md += ["", "## Recovery error per attack type (max voltage error, pu)",
           "| Attack | n | RMSE naive | RMSE Huber | RMSE recovered | p90 recovered | Iso recall | Iso precision | Wrong action naive | Wrong action recovered | PROCEED | Unsafe-PROCEED |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    md += [f"| {r['attack']} | {r['n']} | {r['rmse_naive_pu']:.4f} | {r['rmse_huber_pu']:.4f} | {r['rmse_recovered_pu']:.4f} | "
           f"{r['p90_recovered_pu']:.4f} | {P(r['iso_recall'])} | {P(r['iso_precision'])} | {P(r['wrong_action_naive'])} | "
           f"{P(r['wrong_action_recovered'])} | {P(r['proceed_rate'])} | {P(r['unsafe_proceed'])} |" for r in rows]
    md += ["", "## Risk-coverage (AURC, lower is better)"] + [f"- {k}: {v[2]:.4f}" for k, v in rc.items()]
    if ablation:
        md += ["", "## Ablations (p90 max voltage error, pu)", "| Variant | median | p90 | iso recall | false isolations / case |", "|---|---|---|---|---|"]
        for k, v in ablation.items():
            if "median" in v:
                md.append(f"| {k} | {v['median']:.4f} | {v['p90']:.4f} | {P(v['iso_recall'])} | {v['false_iso']:.2f} |")
            else:
                md.append(f"| {k} | - | - | - | unsafe rate {P(v['unsafe_rate'])} |")
    md += ["", "Files: results.csv, summary.json, gate_calibration.json, calibration.png, risk_coverage.png, "
           "error_before_after.png, ablation.png", "",
           "Note: 'wrong action' compares which buses violate [0.95, 1.05] pu; it is also non-zero on clean data because several buses sit near a limit, so read it relative to the 'none' row.", "",
           "Caveats: simulated measurements and attacks on one network; results hold for the stated attack model and load range "
           "(+-20%). Re-run with your own seed and report the numbers you measure."]
    with open(os.path.join(a.out, "results_summary.md"), "w") as f:
        f.write("\n".join(md))
    log("done -> " + a.out)
    print("\n".join(md))


if __name__ == "__main__":
    main()
