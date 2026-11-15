# GridSentinel AI - Hybrid gate experiment (IEEE 14, simulation only)

New scripts: `hybrid_gate_eval.py`, `stealth_magnitude_sweep.py`. Results: `results_hybrid/`, `results_stealth_sweep/`. Status: **experiment**. The shipped app and the main results use the 11-feature gate; the hybrid is not wired into the app.

Idea: add one feature to the Trust Gate, the log reconstruction error of an autoencoder trained only on clean measurements. Everything else (gradient-boosted trees, split conformal calibration, PROCEED/CAUTION/VALIDATE rule) is unchanged.

## Hybrid vs shipped gate (5 seeds, n = 300 per split, mean +/- 95% CI)
| Test set | Gate | Bound coverage (target 0.90) | PROCEED rate | Unsafe given PROCEED |
|---|---|---|---|---|
| default mix | shipped (11 features) | 0.915 +/- 0.011 | 0.353 +/- 0.045 | 0.045 +/- 0.038 |
| default mix | hybrid (+ autoencoder) | 0.898 +/- 0.035 | 0.687 +/- 0.036 | 0.013 +/- 0.011 |
| load range 0.6-1.4 | shipped | 0.905 +/- 0.022 | 0.364 +/- 0.063 | 0.054 +/- 0.022 |
| load range 0.6-1.4 | hybrid | 0.898 +/- 0.024 | 0.666 +/- 0.013 | 0.012 +/- 0.008 |
| 90% adaptive / stealth-partial | shipped | 0.817 +/- 0.036 | 0.149 +/- 0.048 | 0.322 +/- 0.054 |
| 90% adaptive / stealth-partial | hybrid | 0.849 +/- 0.050 | 0.294 +/- 0.046 | 0.053 +/- 0.031 |
| perfect stealth (dV 0.03-0.08 pu) | shipped | 0.107 +/- 0.056 | 0.329 +/- 0.104 | 1.000 |
| perfect stealth (dV 0.03-0.08 pu) | hybrid | 0.973 +/- 0.024 | 0.003 +/- 0.005 | (almost never PROCEED) |

## How small can a perfect-stealth attack be? (5 seeds, 200 attacks per magnitude)
| dV (pu) | Gate | Attack matters (error > 0.01 pu) | PROCEED rate | Accepted and unsafe |
|---|---|---|---|---|
| 0.005 | shipped / hybrid | 0.00 / 0.00 | 0.52 / 0.83 | 0.00 / 0.00 |
| 0.01 | shipped / hybrid | 0.48 / 0.48 | 0.52 / 0.61 | 0.24 / 0.30 |
| 0.02 | shipped / hybrid | 1.00 / 1.00 | 0.52 / 0.22 | 0.52 / 0.22 |
| 0.03 | shipped / hybrid | 1.00 / 1.00 | 0.50 / 0.01 | 0.50 / 0.01 |
| 0.05 | shipped / hybrid | 1.00 / 1.00 | 0.51 / 0.00 | 0.51 / 0.00 |

## Reading, stated plainly
- In simulation the hybrid roughly doubles how often the gate says PROCEED (35% to 69%) while the share of unsafe results after PROCEED falls (4.5% to 1.3%). It also shrinks the damage from a shifted attack mix (unsafe after PROCEED 32% to 5%).
- It catches large perfect-stealth attacks (a 0.03-0.08 pu voltage shift at one bus) but **not small ones**: at 0.01 to 0.02 pu, right at the 0.01 pu tolerance, 22% to 30% of attacks are still accepted and unsafe. Small stealth attacks that stay below the normal variation of the grid are the remaining hole. Meter hardening is still needed for them.
- Coverage on the shifted attack mix is still below 0.90 (0.85). Not solved.
- The autoencoder and the gate were trained on the same simulator; the gain may not carry over to real data. Real-data validation has not been done.
