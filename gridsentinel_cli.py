#!/usr/bin/env python
"""GridSentinel AI - "bring your own grid" command-line tool (NEW file; no existing file is changed).

Takes a standard grid model (MATPOWER .m, or case14/30/57/118) and a CSV of measurement snapshots and returns, for every snapshot:
attack status, isolated meters, recovered voltages, calibrated error bound, and PROCEED / CAUTION / VALIDATE.

  1) template : py -3.12 gridsentinel_cli.py template --grid case14 --out meas_template.csv
                (writes the exact column list, with units, plus 5 example snapshots incl. attacks)
  2) calibrate: py -3.12 gridsentinel_cli.py calibrate --grid case14 --cal cal_case14.json [--n 200] [--tol 0.01]
                (offline, uses the grid MODEL only - builds the Trust Gate; time grows with grid size)
  3) run      : py -3.12 gridsentinel_cli.py run --grid case14 --meas meas_template.csv --cal cal_case14.json --out decisions.csv

Measurement CSV: one row per snapshot, one column per meter (names exactly as in the template). Units: V in per unit, P in MW,
Q in MVAr, injections positive = generation, flows measured at the 'from' or 'to' end as named.
ASSUMPTIONS (state them): static AC snapshot, the grid model matches the real grid, meter noise sd = 0.004 pu (V) and 1 MW/MVAr (P/Q)
unless you change them with --sigma_v / --sigma_pq. Research prototype; simulation-validated only."""
import argparse, copy, json, os, sys, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore")
import pandapower.networks as pn
import multi_grid_eval as mg
from gridsentinel_core import (GridModel, PipelineConfig, GateCalibration, build_calibration, run_pipeline,
                               make_scenarios, apply_attack)

BUILTIN = {"case14", "case30", "case57", "case118"}


def load_model(grid, sigma_v=0.004, sigma_pq=1.0):
    if grid in BUILTIN:
        fn = mg._ORIG[grid]
    elif os.path.exists(grid):
        from activsg_eval import load_net
        base = load_net(grid)
        fn = lambda: copy.deepcopy(base)
    else:
        sys.exit(f"grid '{grid}' not found: use case14/30/57/118 or a path to a MATPOWER .m file")
    saved = pn.case14
    pn.case14 = fn
    try:
        return GridModel(sigma_v=sigma_v, sigma_pq=sigma_pq)
    finally:
        pn.case14 = saved


def cmd_template(a):
    model = load_model(a.grid)
    cfg = PipelineConfig()
    rng = np.random.default_rng(a.seed)
    rows, labels = [], []
    modes = ["none", "none", "random_single", "multi_coordinated", "stealth_partial"]
    for sc, mode in zip(make_scenarios(model, len(modes), rng), modes):
        z, _ = apply_attack(model, sc, mode, rng, cfg)
        rows.append(z); labels.append(mode)
    df = pd.DataFrame(rows, columns=model.names)
    df.insert(0, "snapshot_id", [f"example_{i}_{m}" for i, m in enumerate(labels)])
    df.to_csv(a.out, index=False)
    pd.DataFrame({"column": model.names, "kind": model.kinds,
                  "unit": ["pu" if k == "V" else ("MW" if k[0] == "P" else "MVAr") for k in model.kinds]}).to_csv(
        os.path.splitext(a.out)[0] + "_columns.csv", index=False)
    print(f"{model.nb} buses, {model.nl} branches, {model.m} meters per snapshot. Wrote {a.out} and *_columns.csv")


def cmd_calibrate(a):
    model = load_model(a.grid, a.sigma_v, a.sigma_pq)
    cfg = PipelineConfig(tol_pu=a.tol, z_iso=a.z_iso, z_zero=a.z_iso + 2.0)
    n = a.n
    print(f"Building Trust Gate for {model.nb} buses from {2 * n} synthetic scenarios (model only, no real data)...", flush=True)
    cal = build_calibration(model, n, n, a.seed, cfg,
                            progress=lambda i, t: print(f"  {i}/{t}", flush=True) if i % 50 == 0 else None)
    meta = {"grid": a.grid, "tol": a.tol, "z_iso": a.z_iso, "sigma_v": a.sigma_v, "sigma_pq": a.sigma_pq, "n": n}
    d = json.loads(cal.to_json()); d["cli_meta"] = meta
    json.dump(d, open(a.cal, "w"))
    print("saved", a.cal)


def cmd_run(a):
    meta = json.load(open(a.cal)).get("cli_meta", {})
    tol, z_iso = meta.get("tol", 0.01), meta.get("z_iso", 4.5)
    model = load_model(a.grid, meta.get("sigma_v", 0.004), meta.get("sigma_pq", 1.0))
    cfg = PipelineConfig(tol_pu=tol, z_iso=z_iso, z_zero=z_iso + 2.0)
    cal = GateCalibration.from_json(open(a.cal).read())
    df = pd.read_csv(a.meas)
    missing = [c for c in model.names if c not in df.columns]
    if missing:
        sys.exit(f"{len(missing)} required columns missing, e.g. {missing[:5]}. Run 'template' to see the exact names.")
    out = []
    for _, r in df.iterrows():
        z = r[model.names].to_numpy(float)
        if not np.isfinite(z).all():
            out.append({"snapshot_id": r.get("snapshot_id", ""), "decision": "VALIDATE", "reason": "missing/NaN readings"}); continue
        res = run_pipeline(model, z, cfg, cal)
        lv = {"green": "PROCEED", "yellow": "CAUTION", "red": "VALIDATE"}[res.level]
        out.append({"snapshot_id": r.get("snapshot_id", ""), "decision": lv, "error_bound_pu": round(res.bound_pu, 5),
                    "p_within_tol_pct": round(res.conf, 1), "converged": res.converged, "n_isolated": len(res.iso_idx),
                    "isolated_meters": "; ".join(res.iso_names), "min_V_recovered": round(float(res.rec_V.min()), 4),
                    "max_V_recovered": round(float(res.rec_V.max()), 4), "runtime_ms": round(res.ms, 1),
                    "reason": " | ".join(res.reasons) if res.reasons else ""})
    o = pd.DataFrame(out); o.to_csv(a.out, index=False)
    print(o[["snapshot_id", "decision", "error_bound_pu", "n_isolated", "isolated_meters"]].to_string(index=False))
    print(f"\nwrote {a.out}  (tolerance {tol} pu; 90% target bound; simulation-validated prototype)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    t = sp.add_parser("template"); t.add_argument("--grid", required=True); t.add_argument("--out", default="meas_template.csv"); t.add_argument("--seed", type=int, default=5)
    c = sp.add_parser("calibrate"); c.add_argument("--grid", required=True); c.add_argument("--cal", required=True)
    c.add_argument("--n", type=int, default=200); c.add_argument("--tol", type=float, default=0.01); c.add_argument("--z_iso", type=float, default=4.5)
    c.add_argument("--sigma_v", type=float, default=0.004); c.add_argument("--sigma_pq", type=float, default=1.0); c.add_argument("--seed", type=int, default=7)
    r = sp.add_parser("run"); r.add_argument("--grid", required=True); r.add_argument("--meas", required=True); r.add_argument("--cal", required=True); r.add_argument("--out", default="decisions.csv")
    a = ap.parse_args()
    {"template": cmd_template, "calibrate": cmd_calibrate, "run": cmd_run}[a.cmd](a)


if __name__ == "__main__":
    main()
