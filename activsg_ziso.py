#!/usr/bin/env python
"""NEW: tune the isolation threshold z_iso on a large grid to cut clean false alarms. Validation seed picks z, test seed confirms.
py -3.12 activsg_ziso.py --file case_ACTIVSg200.m --z 5.0 5.5 --seed 303 --nclean 40 --natt 40 --out ziso_303_a.json"""
import argparse, copy, json, numpy as np
import multi_grid_eval as mg, activsg_eval as ae
from gridsentinel_core import PipelineConfig
from batch_eval import gen_cases
ap = argparse.ArgumentParser(); ap.add_argument("--file", required=True); ap.add_argument("--z", nargs="+", type=float, required=True)
ap.add_argument("--seed", type=int, default=303); ap.add_argument("--nclean", type=int, default=40); ap.add_argument("--natt", type=int, default=40); ap.add_argument("--out", required=True)
a = ap.parse_args(); base = ae.load_net(a.file); mg._ORIG["custom"] = lambda: copy.deepcopy(base); model = mg.make_model("custom"); out = []
ATT = {"random_single": .2, "single_small": .2, "multi_coordinated": .2, "stealth_partial": .2, "adaptive": .2}
for z in a.z:
    cfg = PipelineConfig(z_iso=z, z_zero=z + 2.0)
    cl = gen_cases(model, cfg, a.nclean, np.random.default_rng(a.seed), mix={"none": 1.0})
    at = gen_cases(model, cfg, a.natt, np.random.default_rng(a.seed + 1), mix=ATT)
    r = {"z_iso": z, "seed": a.seed, "clean_false_alarm": float(np.mean([c["n_iso"] > 0 or c["res"].hard_fail for c in cl])),
         "clean_hard_fail": float(np.mean([c["res"].hard_fail for c in cl])), "clean_mean_iso": float(np.mean([c["n_iso"] for c in cl])),
         "iso_recall": sum(c["hits"] for c in at) / max(1, sum(c["n_att"] for c in at)),
         "err_naive": float(np.median([c["err_plain"] for c in at])), "err_recovered": float(np.median([c["err_rec"] for c in at]))}
    out.append(r); print(r, flush=True); json.dump(out, open(a.out, "w"), indent=1)
