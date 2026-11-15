# Multi-grid results (simulation only)

n per split = 300, seeds = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]. Mean +/- 95% CI over seeds (small number of seeds: CI is rough).

| Grid | Buses | Bound coverage (target 0.90) | PROCEED rate | Unsafe given PROCEED | Isolation recall | Clean false alarm | Median err naive -> recovered (pu) | ms/case |
|---|---|---|---|---|---|---|---|---|
| case14 | 14 | 0.901 +/- 0.013 | 0.383 +/- 0.049 | 0.053 +/- 0.009 | 0.273 +/- 0.010 | 0.029 +/- 0.015 | 0.0059 -> 0.0032 | 9 |
