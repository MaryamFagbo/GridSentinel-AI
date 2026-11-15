# Hybrid gate vs shipped gate (IEEE 14, simulation only)

seeds [7, 11, 13, 17, 19], n = 300. Mean +/- 95% CI. 'unsafe given PROCEED' is nan when the gate never says PROCEED.

| Test set | Gate | Bound coverage (target 0.90) | PROCEED rate | Unsafe given PROCEED |
|---|---|---|---|---|
| default mix | A: shipped gate (11 features) | 0.915 +/- 0.011 | 0.353 +/- 0.045 | 0.045 +/- 0.038 |
| default mix | H: hybrid gate (+ autoencoder score) | 0.898 +/- 0.035 | 0.687 +/- 0.036 | 0.013 +/- 0.011 |
| load range 0.6-1.4 | A: shipped gate (11 features) | 0.905 +/- 0.022 | 0.364 +/- 0.063 | 0.054 +/- 0.022 |
| load range 0.6-1.4 | H: hybrid gate (+ autoencoder score) | 0.898 +/- 0.024 | 0.666 +/- 0.013 | 0.012 +/- 0.008 |
| 90% adaptive / stealth-partial | A: shipped gate (11 features) | 0.817 +/- 0.036 | 0.149 +/- 0.048 | 0.322 +/- 0.054 |
| 90% adaptive / stealth-partial | H: hybrid gate (+ autoencoder score) | 0.849 +/- 0.050 | 0.294 +/- 0.046 | 0.053 +/- 0.031 |
| perfect stealth (out-of-model) | A: shipped gate (11 features) | 0.107 +/- 0.056 | 0.329 +/- 0.104 | 1.000 +/- 0.000 |
| perfect stealth (out-of-model) | H: hybrid gate (+ autoencoder score) | 0.973 +/- 0.024 | 0.003 +/- 0.005 | 1.000 +/- nan |
