#!/usr/bin/env python
"""GridSentinel AI - run the SAME pipeline on any MATPOWER case file, e.g. Texas A&M ACTIVSg200 (NEW file).

  py -3.12 activsg_eval.py --file case_ACTIVSg200.m --check            # convert + sanity report only
  py -3.12 activsg_eval.py --file case_ACTIVSg200.m --n 100 --seeds 7 11 --out results_activsg

ACTIVSg cases are SYNTHETIC but realistic grids (Texas A&M), not real utility data. Attacks are injected synthetically.
Truth is used only for scoring. Same settings as every other grid (no tuning)."""
import argparse, copy, json, os, warnings
import numpy as np
warnings.filterwarnings("ignore")
import pandapower as pp
from pandapower.converter.matpower import from_mpc
import multi_grid_eval as mg
from gridsentinel_core import PipelineConfig


def load_net(path):
    net = from_mpc(path, f_hz=60)
    # light cleaning: drop out-of-service elements, keep one slack
    for tbl in ("gen", "sgen", "load", "line", "trafo", "shunt", "ext_grid"):
        t = getattr(net, tbl, None)
        if t is not None and len(t) and "in_service" in t:
            t.drop(t.index[~t["in_service"].astype(bool)], inplace=True)
    return net


def report(net):
    pp.runpp(net, init="dc", max_iteration=50)
    vm = net.res_bus.vm_pu
    return {"buses": int(len(net.bus)), "lines": int(len(net.line)), "trafos": int(len(net.trafo)), "gens": int(len(net.gen)),
            "sgens": int(len(net.sgen)), "loads": int(len(net.load)), "shunts": int(len(net.shunt)), "ext_grids": int(len(net.ext_grid)),
            "power_flow_converged": bool(net.converged), "vm_min": float(vm.min()), "vm_max": float(vm.max()),
            "total_load_mw": float(net.res_load.p_mw.sum())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seeds", nargs="+", type=int, default=[7, 11])
    ap.add_argument("--out", default="results_activsg")
    a = ap.parse_args()
    base = load_net(a.file)
    rep = report(copy.deepcopy(base))
    print(json.dumps(rep, indent=1))
    os.makedirs(a.out, exist_ok=True)
    json.dump(rep, open(os.path.join(a.out, "case_report.json"), "w"), indent=1)
    if a.check:
        return
    mg._ORIG["custom"] = lambda: copy.deepcopy(base)
    cfg, rows = PipelineConfig(), []
    for s in a.seeds:
        r = mg.one_run("custom", s, a.n, cfg); r["case"] = os.path.basename(a.file); rows.append(r)
        print(f"seed {s}: cov={r['bound_coverage']:.3f} proceed={r['proceed_rate']:.2f} unsafe|proceed={r['unsafe_given_proceed']:.3f} "
              f"iso_rec={r['isolation_recall']:.2f} clean_FA={r['clean_false_alarm']:.2f} err {r['median_err_naive']:.4f}->{r['median_err_recovered']:.4f} "
              f"{r['median_ms_pipeline']:.0f}ms/case", flush=True)
        json.dump(rows, open(os.path.join(a.out, "runs.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
