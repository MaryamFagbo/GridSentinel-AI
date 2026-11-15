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

## ACTIVSg200 (Texas A&M synthetic 200-bus grid; added later)

ACTIVSg200 is a **synthetic but realistic** grid (ARPA-E GRID DATA / Texas A&M), not utility data. 200 buses, 179 lines, 66 transformers (converted by pandapower to impedance elements), 48 generators, 108 loads; AC power flow converges. Script: `activsg_eval.py` (same pipeline, same settings, gate re-calibrated on this grid). Files: `results_activsg200/`.

| Run | Bound coverage (target 0.90) | PROCEED rate | Isolation recall | Clean false alarm | Median error naive -> recovered (pu) | s/case |
|---|---|---|---|---|---|---|
| n = 60 per split, seed 7 | 0.950 | 0.00 | 0.20 | 0.11 | 0.0080 -> 0.0073 | 2.7 |
| n = 60 per split, seed 11 | 0.950 | 0.00 | 0.21 | 0.14 | 0.0067 -> 0.0067 | 2.8 |
| n = 150 per split, seed 7 | 0.920 | 0.00 | 0.22 | 0.23 | 0.0063 -> 0.0062 | 2.7 |

Reading, stated plainly:
- The calibrated bound still reaches its target, but **the gate never says PROCEED**: it refuses every case. It fails safe, but it is not useful at this size.
- **Recovery gives almost no gain** (error 0.0063 -> 0.0062 at n = 150), and **23% of clean snapshots were flagged**. The thresholds were set on IEEE 14 and not tuned for 200 buses. Per-grid tuning has not been done.
- Few runs (1 to 2 seeds, small n) because one scenario takes about 2.7 s. These numbers are indicative, not final.
- So the honest scope of our results: working and calibrated up to IEEE 118; on a 200-bus realistic grid the same untuned settings do not deliver a useful decision.

## ACTIVSg200 - per-grid tolerance tuning (simulation; synthetic-but-realistic grid)

Problem found earlier: at 200 buses the gate never said PROCEED with the default tolerance 0.01 pu. Reason: the error metric is the MAX over 200 buses, so even a good estimate often exceeds 0.01 pu; the bound is calibrated (coverage ~0.90) but it is not tight enough to certify 0.01.

Procedure (`activsg_pool.py` + `activsg_tune.py`): 500 scenarios (2 pools, seeds 101/202), 20 random 40/20/20/20 splits (train / conformal calibration / validation / test). On each split the tolerance is chosen on the VALIDATION part only (smallest tolerance in {0.008..0.03} with PROCEED >= 10% and unsafe-given-PROCEED <= 10%), then reported on the held-out TEST part. Core code unchanged; only the decision tolerance differs.

| Tolerance (pu) | PROCEED rate (test, mean of 20 splits) | Unsafe given PROCEED |
|---|---|---|
| 0.010 (default) | 0.4% | 0% (almost no PROCEEDs) |
| 0.015 | 4.4% | 13% |
| 0.020 | 12.9% | 9.1% |
| 0.025 | 25.6% | 7.9% |
| 0.030 | 37.5% | 11.3% |

Validation-selected tolerance: 0.03 in 14/20 splits (found in 10/20; 10 fell back to the largest). Bound coverage on test 0.90 +/- 0.03 (target 0.90).
Honest reading: on a 200-bus grid the gate works (valid bound, usable PROCEED rate) only for a looser tolerance, about 0.025-0.03 pu. It is a per-grid operating choice, not a free improvement; the unsafe-given-PROCEED rate (8-11%) is near the 10% target but is not guaranteed (the conformal guarantee is marginal). Clean false alarms (23%) were NOT fixed by this step; that needs re-tuning z_iso with regeneration (not done).
Reproduce: `py -3.12 activsg_pool.py --file case_ACTIVSg200.m --n 250 --seed 101 --out pool_101.npz` (and seed 202), then `py -3.12 activsg_tune.py --pools pool_101.npz pool_202.npz`.

### ACTIVSg200 - isolation threshold z_iso (false alarms)
`activsg_ziso.py`: validation seed 303 (40 clean + 40 attacked scenarios per setting). Clean false alarm: z_iso 4.5 -> 23% (earlier 150-case run), 5.0 -> 2.5%, 5.5 / 6.0 / 7.0 -> 0%; isolation recall 0.29 / 0.28 / 0.25 / 0.24. Chosen z_iso = 5.0 (z_zero = 7.0) on VALIDATION only.
Confirmation on fresh 500-scenario pool (seeds 101/202, different from the selection seed): clean false alarm 6.2% (5/81; the 95% interval is wide because the sample is small), isolation recall about 0.20, median error plain -> recovered about 0.0071 -> 0.0065 pu (recovery still helps only slightly at 200 buses).
Gate with z_iso = 5.0, tolerance chosen on validation (20 splits): coverage 0.906 +/- 0.037; tolerance 0.03 pu chosen in 14/20 splits; at 0.025 pu PROCEED 17.7% / unsafe-given-PROCEED 11.9%; at 0.03 pu PROCEED 30.1% / unsafe 11.6%. Files: results_activsg200_tuned_z5/.
Reading: false alarms fixed (23% -> about 6%), gate usable only at a loose 2.5-3% tolerance, recovery benefit on this grid is small. These are per-grid operating choices made on validation data, reported on held-out data; the 200-bus result is a scaling limit, not a success claim.
