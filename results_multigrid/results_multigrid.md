# Multi-grid results (simulation only)

n per split = 300, seeds = [7, 11, 13, 17, 19]. Mean +/- 95% CI over seeds (small number of seeds: CI is rough).

| Grid | Buses | Bound coverage (target 0.90) | PROCEED rate | Unsafe given PROCEED | Isolation recall | Clean false alarm | Median err naive -> recovered (pu) | ms/case |
|---|---|---|---|---|---|---|---|---|
| case14 | 14 | 0.907 +/- 0.019 | 0.365 +/- 0.074 | 0.044 +/- 0.010 | 0.286 +/- 0.020 | 0.023 +/- 0.019 | 0.0063 -> 0.0032 | 7 |
| case30 | 30 | 0.918 +/- 0.028 | 0.345 +/- 0.041 | 0.041 +/- 0.019 | 0.240 +/- 0.017 | 0.037 +/- 0.017 | 0.0067 -> 0.0046 | 21 |
| case57 | 57 | 0.909 +/- 0.017 | 0.345 +/- 0.008 | 0.038 +/- 0.026 | 0.239 +/- 0.018 | 0.071 +/- 0.038 | 0.0063 -> 0.0053 | 88 |
