# Worst-case calibration (IEEE 14, simulation only)

seeds [7, 11, 13, 17, 19], n = 300. Mean +/- 95% CI.

| Gate | Test set | Bound coverage (target 0.90) | PROCEED rate | Unsafe given PROCEED |
|---|---|---|---|---|
| A: calibrated on default mix | test: default mix | 0.923 +/- 0.018 | 0.381 +/- 0.042 | 0.028 +/- 0.007 |
| A: calibrated on default mix | test: pessimistic mix | 0.817 +/- 0.022 | 0.125 +/- 0.053 | 0.329 +/- 0.070 |
| A: calibrated on default mix | test: perfect stealth (out-of-model) | 0.127 +/- 0.067 | 0.310 +/- 0.141 | 1.000 +/- 0.000 |
| B: calibrated on pessimistic mix | test: default mix | 0.961 +/- 0.011 | 0.003 +/- 0.005 | 0.000 +/- nan |
| B: calibrated on pessimistic mix | test: pessimistic mix | 0.908 +/- 0.008 | 0.005 +/- 0.009 | 0.071 +/- 0.089 |
| B: calibrated on pessimistic mix | test: perfect stealth (out-of-model) | 0.312 +/- 0.046 | 0.008 +/- 0.014 | 1.000 +/- 0.000 |
