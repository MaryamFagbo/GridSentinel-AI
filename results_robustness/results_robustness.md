# Robustness results (IEEE 14, simulation only)

Gate calibrated on the default generator; seeds [7, 11, 13, 17, 19], n = 300 per split. Mean +/- 95% CI.

## 1. Distribution shift

| Test condition | Bound coverage (target 0.90) | PROCEED rate | Unsafe given PROCEED |
|---|---|---|---|
| in-distribution (control) | 0.907 +/- 0.019 | 0.365 +/- 0.074 | 0.044 +/- 0.010 |
| load range 0.6-1.4 (was 0.8-1.2) | 0.902 +/- 0.013 | 0.322 +/- 0.067 | 0.040 +/- 0.012 |
| attack mix: 90% adaptive/stealth-partial | 0.797 +/- 0.021 | 0.127 +/- 0.031 | 0.362 +/- 0.090 |
| both shifts together | 0.793 +/- 0.019 | 0.100 +/- 0.047 | 0.413 +/- 0.079 |
| out-of-model: stealth_full only | 0.129 +/- 0.074 | 0.299 +/- 0.126 | 1.000 +/- 0.000 |

## 2. Autoencoder baseline vs GridSentinel (detection only)

| Method | Attack recall | False alarm on clean |
|---|---|---|
| GridSentinel | 0.682 +/- 0.031 | 0.023 +/- 0.019 |
| Autoencoder (clean-trained) | 0.854 +/- 0.024 | 0.065 +/- 0.020 |

False alarm on CLEAN snapshots when the load range shifts to 0.6-1.4 (the autoencoder was trained on 0.8-1.2):

| Method | False alarm on clean, shifted load |
|---|---|
| GridSentinel | 0.012 +/- 0.003 |
| Autoencoder (clean-trained) | 0.127 +/- 0.028 |

Recall per attack type:

| Attack | GridSentinel | Autoencoder |
|---|---|---|
| adaptive | 0.02 | 0.94 |
| multi_coordinated | 0.99 | 0.94 |
| random_single | 1.00 | 0.91 |
| single_small | 0.67 | 0.38 |
| stealth_full (out-of-model) | 0.01 | 1.00 |
| stealth_partial | 0.90 | 1.00 |
