#!/usr/bin/env python
"""NEW: generate a pool of scenarios on a MATPOWER case once, save features/errors, so tuning can be done offline
without regenerating (2.7 s/case on ACTIVSg200). Usage: py -3.12 activsg_pool.py --file case_ACTIVSg200.m --n 250 --seed 101 --out pool_101.npz"""
import argparse, copy, numpy as np
import multi_grid_eval as mg, activsg_eval as ae
from gridsentinel_core import PipelineConfig
from batch_eval import gen_cases
ap = argparse.ArgumentParser(); ap.add_argument("--file", required=True); ap.add_argument("--n", type=int, default=250)
ap.add_argument("--seed", type=int, default=101); ap.add_argument("--out", required=True); ap.add_argument("--z_iso", type=float, default=4.5); a = ap.parse_args()
base = ae.load_net(a.file); mg._ORIG["custom"] = lambda: copy.deepcopy(base)
cfg = PipelineConfig(z_iso=a.z_iso, z_zero=a.z_iso + 2.0) if a.z_iso != 4.5 else PipelineConfig(); model = mg.make_model("custom"); rng = np.random.default_rng(a.seed)
cs = gen_cases(model, cfg, a.n, rng)
np.savez(a.out, F=np.array([c["res"].fvec for c in cs]), E=np.array([c["err_rec"] for c in cs]), Ep=np.array([c["err_plain"] for c in cs]),
         mode=np.array([c["mode"] for c in cs]), n_iso=np.array([c["n_iso"] for c in cs]), n_att=np.array([c["n_att"] for c in cs]),
         hits=np.array([c["hits"] for c in cs]), hard=np.array([c["res"].hard_fail for c in cs]))
print("done", a.out)
