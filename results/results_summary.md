# GridSentinel AI - batch evaluation (seed 7, 300 scenarios per split)

Simulation on IEEE 14-bus (122 AC measurements). Synthetic attacks, attacker budget K_MAX=8 meters. Truth is used only to score results.

## Headline (deployed grid, in-model attacks)
- Gate target: P(max voltage error <= 0.01 pu) >= 90% per bound
- Bound coverage on held-out test: **92.7%**
- PROCEED share: **32.3%**; unsafe among PROCEED: **4.1%**; unsafe-PROCEED over all cases: **1.3%** (always-proceed would be 21.3%)
- Wrong voltage-limit action among PROCEED: 21.6%
- Runtime per snapshot: median 7 ms, p95 18 ms

## Hardened grid (5 protected meters: P_inj@B4, P_inj@B6, P_inj@B9, V@B1, V@B8)
- PROCEED 28.3%; unsafe among PROCEED 0.0%; bound coverage 88.7%

## Limit: out-of-model full stealth (attacker controls the whole stealth support)
- Deployed: unsafe rate 100.0%, PROCEED 30.0%, unsafe-PROCEED 30.0%
- Hardened: unsafe rate 100.0%, PROCEED 31.0%, unsafe-PROCEED 31.0%
- Out-of-model: the attacker controls far more than K_MAX meters. Perfect stealth leaves every residual unchanged, so no estimator-side method can detect it; the guarantee holds only inside the stated attacker budget. Hardening did NOT fix this case in our tests - we report the number as measured.

## Detection vs baselines (attacked vs clean, deployed test set)
| Method | Precision | Recall | F1 | FPR |
|---|---|---|---|---|
| GridSentinel (flags/isolates) | 98.2% | 66.1% | 79.0% | 5.8% |
| WLS + chi-square | 100.0% | 70.2% | 82.5% | 0.0% |
| WLS + LNR (>3) | 95.6% | 96.8% | 96.2% | 21.2% |
| IsolationForest (raw z) | 100.0% | 6.5% | 12.1% | 0.0% |

## Recovery error per attack type (max voltage error, pu)
| Attack | n | RMSE naive | RMSE Huber | RMSE recovered | p90 recovered | Iso recall | Iso precision | Wrong action naive | Wrong action recovered | PROCEED | Unsafe-PROCEED |
|---|---|---|---|---|---|---|---|---|---|---|---|
| none | 52 | 0.0022 | 0.0022 | 0.0022 | 0.0030 | n/a | 0.0% | 21.2% | 19.2% | 34.6% | 0.0% |
| random_single | 34 | 0.0086 | 0.0022 | 0.0022 | 0.0030 | 100.0% | 100.0% | 55.9% | 17.6% | 61.8% | 0.0% |
| single_small | 50 | 0.0026 | 0.0024 | 0.0023 | 0.0035 | 66.0% | 100.0% | 16.0% | 14.0% | 64.0% | 0.0% |
| multi_coordinated | 43 | 0.0047 | 0.0027 | 0.0027 | 0.0035 | 80.0% | 100.0% | 41.9% | 20.9% | 44.2% | 0.0% |
| stealth_partial | 58 | 0.0436 | 0.0488 | 0.0427 | 0.0651 | 29.6% | 51.3% | 77.6% | 51.7% | 10.3% | 5.2% |
| adaptive | 63 | 0.0174 | 0.0176 | 0.0176 | 0.0194 | 0.0% | 0.0% | 34.9% | 33.3% | 1.6% | 1.6% |

## Risk-coverage (AURC, lower is better)
- GridSentinel gate: 0.1031
- chi-square (raw J): 0.1380
- always-proceed: 0.2133

## Ablations (p90 max voltage error, pu)
| Variant | median | p90 | iso recall | false isolations / case |
|---|---|---|---|---|
| Full GridSentinel | 0.0030 | 0.0428 | 28.6% | 0.41 |
| No trust weighting | 0.0032 | 0.0514 | 0.0% | 0.00 |
| No observability guard | 0.0030 | 0.0428 | 28.6% | 0.41 |
| Basic meter set (no flows) | 0.0090 | 0.0686 | 6.7% | 0.08 |
| No gate (always proceed) | - | - | - | unsafe rate 21.3% |

Files: results.csv, summary.json, gate_calibration.json, calibration.png, risk_coverage.png, error_before_after.png, ablation.png

Note: 'wrong action' compares which buses violate [0.95, 1.05] pu; it is also non-zero on clean data because several buses sit near a limit, so read it relative to the 'none' row.

Caveats: simulated measurements and attacks on one network; results hold for the stated attack model and load range (+-20%). Re-run with your own seed and report the numbers you measure.