# GridSentinel AI - Robustness tests (IEEE 14, simulation only)

New scripts: `robustness_eval.py`, `worstcase_calibration_eval.py`. Results: `results_robustness/`, `results_worstcase/`, `results_multigrid_14_10seeds/`. Mean +/- 95% CI over seeds (5 seeds, n = 300 per split; the 10-seed run is IEEE 14 only).

## 1. More seeds (IEEE 14, 10 seeds)
Bound coverage 0.901 +/- 0.013 (target 0.90); unsafe given PROCEED 5.3% +/- 0.9; clean false alarm 2.9% +/- 1.5; median error 0.0059 -> 0.0032 pu.

## 2. Distribution shift (gate calibrated on the default generator)
| Test condition | Bound coverage (target 0.90) | PROCEED rate | Unsafe given PROCEED |
|---|---|---|---|
| in-distribution (control) | 0.907 +/- 0.019 | 0.365 +/- 0.074 | 0.044 +/- 0.010 |
| load range 0.6-1.4 (was 0.8-1.2) | 0.902 +/- 0.013 | 0.322 +/- 0.067 | 0.040 +/- 0.012 |
| attack mix: 90% adaptive / stealth-partial | 0.797 +/- 0.021 | 0.127 +/- 0.031 | 0.362 +/- 0.090 |
| both shifts together | 0.793 +/- 0.019 | 0.100 +/- 0.047 | 0.413 +/- 0.079 |
| out-of-model: perfect stealth only | 0.129 +/- 0.074 | 0.299 +/- 0.126 | 1.000 +/- 0.000 |

Reading: the bound survives a load-range shift. It does **not** survive a shift in the attack mix: the 90% guarantee is marginal over the attack mix used in calibration. Against perfect-stealth attacks the gate is wrong (it says PROCEED 30% of the time and every PROCEED is unsafe). This is the known limit of residual-based methods; meter hardening is the answer we show.

## 3. Calibrating on a pessimistic mix
| Gate | Test set | Bound coverage | PROCEED rate | Unsafe given PROCEED |
|---|---|---|---|---|
| A: default-mix calibration | default mix | 0.923 +/- 0.018 | 0.381 +/- 0.042 | 0.028 +/- 0.007 |
| A | pessimistic mix | 0.817 +/- 0.022 | 0.125 +/- 0.053 | 0.329 +/- 0.070 |
| A | perfect stealth | 0.127 +/- 0.067 | 0.310 +/- 0.141 | 1.000 |
| B: pessimistic-mix calibration | default mix | 0.961 +/- 0.011 | 0.003 +/- 0.005 | 0.000 |
| B | pessimistic mix | 0.908 +/- 0.008 | 0.005 +/- 0.009 | 0.071 +/- 0.089 |
| B | perfect stealth | 0.312 +/- 0.046 | 0.008 +/- 0.014 | 1.000 |

Reading: calibrating on the harsh mix restores coverage and makes the gate refuse almost everything (PROCEED about 0.5%). It fails safe, but is hardly useful. The choice of calibration mix is a dial between safety and availability. Finding a middle setting is future work.

## 4. Autoencoder baseline (detection only)
An autoencoder (64-16-64, scikit-learn) trained on clean measurements only; alarm threshold at the 95th percentile of clean reconstruction error.

| Method | Attack recall | False alarm on clean | False alarm on clean, load range shifted |
|---|---|---|---|
| GridSentinel | 0.682 +/- 0.031 | 0.023 +/- 0.019 | 0.012 +/- 0.003 |
| Autoencoder | 0.854 +/- 0.024 | 0.065 +/- 0.020 | 0.127 +/- 0.028 |

| Attack | GridSentinel | Autoencoder |
|---|---|---|
| adaptive | 0.02 | 0.94 |
| multi_coordinated | 0.99 | 0.94 |
| random_single | 1.00 | 0.91 |
| single_small | 0.67 | 0.38 |
| stealth_partial | 0.90 | 1.00 |
| perfect stealth (out-of-model) | 0.01 | 1.00 |

Reading, stated plainly:
- The autoencoder catches more attacks in our simulator, including adaptive and perfect-stealth ones, which GridSentinel's residual-based isolation does not. The adaptive attack was designed against GridSentinel's own trust rule, not against the autoencoder.
- It raises more false alarms (6.5%, and 12.7% when the load range shifts, against 1.2% for GridSentinel), because it learns what normal looks like for one operating range.
- It gives an alarm only. It does not recover the state and it does not give an error bound or a PROCEED/CAUTION/VALIDATE decision.
- Both were tested on the same synthetic generator, so the autoencoder's advantage may not carry over to real data. A hybrid (physics residuals plus a learned anomaly score as another gate feature) is the obvious next step. It was not built or tested here.
