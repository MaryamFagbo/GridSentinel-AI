# GridSentinel AI - Multi-grid experiments (simulation only)

Script: `multi_grid_eval.py` (new file, no existing file modified). Same pipeline and hyper-parameters on every grid; the gate is re-calibrated per grid and per seed on its own train/calibration splits; metrics are on held-out test scenarios (about 15% clean, 85% attacked, mix in `docs/ALGORITHM.md`). Mean +/- 95% CI over seeds (few seeds, so CIs are rough).

| Grid | Buses | n per split | Seeds | Bound coverage (target 0.90) | PROCEED rate | Unsafe given PROCEED | Isolation recall | Clean false alarm | Median error naive -> recovered (pu) | ms/case |
|---|---|---|---|---|---|---|---|---|---|---|
| IEEE 14 | 14 | 300 | 5 | 0.907 +/- 0.019 | 0.365 +/- 0.074 | 0.044 +/- 0.010 | 0.286 +/- 0.020 | 0.023 +/- 0.019 | 0.0063 -> 0.0032 | 7 |
| IEEE 30 | 30 | 300 | 5 | 0.918 +/- 0.028 | 0.345 +/- 0.041 | 0.041 +/- 0.019 | 0.240 +/- 0.017 | 0.037 +/- 0.017 | 0.0067 -> 0.0046 | 21 |
| IEEE 57 | 57 | 300 | 5 | 0.909 +/- 0.017 | 0.345 +/- 0.008 | 0.038 +/- 0.026 | 0.239 +/- 0.018 | 0.071 +/- 0.038 | 0.0063 -> 0.0053 | 88 |
| IEEE 118 | 118 | 200 | 3 | 0.895 +/- 0.006 | 0.548 +/- 0.134 | 0.056 +/- 0.018 | 0.234 +/- 0.028 | 0.172 +/- 0.076 | 0.0030 -> 0.0024 | 673 |

Raw per-run numbers: `results_multigrid/runs.json`, `results_multigrid_118/runs.json`.

## What the numbers support

- The calibrated error bound reached about the 90% target on all four grids (0.895-0.918). 118 is slightly under 0.90 with n = 200 per split (smaller calibration set).
- When the gate says PROCEED, the recovered voltage error exceeded 0.01 pu in about 4-6% of cases on every grid (naive "always proceed" has no such control).
- The same code works from 14 to 118 buses without re-tuning; runtime per snapshot grows (7 ms -> 673 ms, numpy dense matrices, not optimized).

## What they do not support (be upfront about this)

- Recovery benefit shrinks with size: median error falls about 49% (14), 31% (30), 16% (57), 20% (118). On big grids the recovery step alone is a modest gain; the gate (knowing when not to trust) carries more of the value.
- Clean false alarms rise with grid size (2% -> 4% -> 7% -> 17%). Thresholds were not re-tuned per grid. This is a real weakness at 118 buses.
- Isolation recall on this mix is about 24-29%: many scenarios are stealth-partial or adaptive on purpose. It is not a detector benchmark.
- The conformal guarantee is marginal and holds only for scenarios from the same generator. It says nothing about real SCADA data or unseen attack types. "Unsafe given PROCEED" is an empirical rate, not a guaranteed bound.
- Only a few seeds were used; the 118 run has 3 seeds and fewer scenarios.

## Next experiments to make it harder to attack at the exhibition

1. More seeds (10+) and larger n; report CIs from a bootstrap.
2. Per-grid threshold tuning on a validation split, to see if 118 false alarms can be cut.
3. A learned baseline (autoencoder or CVAE on measurements) against GridSentinel on the same splits.
4. Shifted-distribution test: calibrate on one load range or attack mix, test on another, and report the coverage drop.
5. Different noise levels (sigma x 0.5, x 2) and measurement sets (fewer meters).
6. A public dataset or real-grid validation if one becomes available to you (none was used here).
