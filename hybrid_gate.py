#!/usr/bin/env python
"""GridSentinel AI - HybridGate (NEW file; no existing file is modified).

Wraps the shipped pipeline and adds ONE feature to the Trust Gate: the log reconstruction error of an
autoencoder trained only on clean measurements. Everything else is the shipped code.

    from hybrid_gate import HybridGate
    hg = HybridGate(GridModel()).fit(n=300, seed=7)      # about 1-2 minutes
    out = hg.assess(z)                                   # z = measurement vector
    out["hybrid"], out["shipped"]                        # ("PROCEED"|"CAUTION"|"VALIDATE")

    python hybrid_gate.py --demo                         # side-by-side on 5 attack types

EXPERIMENT (IEEE 14, simulation). See docs/HYBRID.md for results and limits."""
import argparse
import warnings
import numpy as np
warnings.filterwarnings("ignore")
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from gridsentinel_core import (GateCalibration, GridModel, PipelineConfig, apply_attack, decide_level,
                               make_scenarios, run_pipeline, true_error)
from batch_eval import errs, feats, gen_cases

NAME = {"green": "PROCEED", "yellow": "CAUTION", "red": "VALIDATE"}


class HybridGate:
    def __init__(self, model, cfg=None):
        self.model, self.cfg = model, cfg or PipelineConfig()

    def _ae_score(self, Z):
        Zs = self.sc.transform(np.atleast_2d(Z))
        return np.log10(np.mean((self.ae.predict(Zs) - Zs) ** 2, axis=1) + 1e-12)

    def fit(self, n=300, seed=7):
        rng = np.random.default_rng(seed)
        clean = gen_cases(self.model, self.cfg, n, rng, fixed_mode="none")
        Z = np.array([c["z"] for c in clean])
        self.sc = StandardScaler().fit(Z)
        Zs = self.sc.transform(Z)
        self.ae = MLPRegressor(hidden_layer_sizes=(64, 16, 64), max_iter=400, random_state=0, early_stopping=True).fit(Zs, Zs)
        tr, ca = gen_cases(self.model, self.cfg, n, rng), gen_cases(self.model, self.cfg, n, rng)
        aug = lambda cs: np.column_stack([feats(cs), self._ae_score(np.array([c["z"] for c in cs]))])
        t, a = self.cfg.tol_pu, self.cfg.alpha
        self.calA = GateCalibration.fit(feats(tr), errs(tr), feats(ca), errs(ca), t, a)
        self.calH = GateCalibration.fit(aug(tr), errs(tr), aug(ca), errs(ca), t, a)
        return self

    def assess(self, z):
        res = run_pipeline(self.model, z, self.cfg)
        out = {"result": res}
        for name, cal, f in (("shipped", self.calA, res.fvec),
                             ("hybrid", self.calH, np.append(res.fvec, self._ae_score(z)[0]))):
            U = cal.bound(f, self.cfg.alpha)
            conf = 100 * cal.prob_within(f, self.cfg.tol_pu)
            out[name] = NAME[decide_level(U, conf, res.hard_fail, self.cfg)[0]]
            out[name + "_bound_pu"] = float(U)
        return out


def demo(n=200, k=20, seed=3):
    model, cfg = GridModel(), PipelineConfig()
    hg = HybridGate(model, cfg).fit(n=n, seed=7)
    rng = np.random.default_rng(seed)
    print(f"\n{k} scenarios per attack type. Counts: PROCEED/CAUTION/VALIDATE; 'bad' = PROCEED although the true error exceeds {cfg.tol_pu} pu.\n")
    print(f"{'attack':18s} {'shipped P/C/V (bad)':24s} {'hybrid P/C/V (bad)':24s}")
    for mode in ("none", "random_single", "stealth_partial", "adaptive", "stealth_full"):
        cnt = {"shipped": [0, 0, 0], "hybrid": [0, 0, 0]}; bad = {"shipped": 0, "hybrid": 0}
        for sc in make_scenarios(model, k, rng):
            z, _ = apply_attack(model, sc, mode, rng, cfg)
            o = hg.assess(z)
            err = true_error(model, sc.x_true, o["result"].rec_V)
            for g in ("shipped", "hybrid"):
                i = ("PROCEED", "CAUTION", "VALIDATE").index(o[g]); cnt[g][i] += 1
                bad[g] += int(o[g] == "PROCEED" and err > cfg.tol_pu)
        sh = "/".join(map(str, cnt["shipped"])) + " (" + str(bad["shipped"]) + ")"
        hy = "/".join(map(str, cnt["hybrid"])) + " (" + str(bad["hybrid"]) + ")"
        print(f"{mode:18s} {sh:24s} {hy:24s}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--n", type=int, default=200)
    a = ap.parse_args()
    demo(a.n) if a.demo else print(__doc__)
