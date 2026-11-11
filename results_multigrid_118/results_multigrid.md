# Multi-grid results (simulation only)

n per split = 200, seeds = [7, 11, 13]. Mean +/- 95% CI over seeds (small number of seeds: CI is rough).

| Grid | Buses | Bound coverage (target 0.90) | PROCEED rate | Unsafe given PROCEED | Isolation recall | Clean false alarm | Median err naive -> recovered (pu) | ms/case |
|---|---|---|---|---|---|---|---|---|
| case118 | 118 | 0.895 +/- 0.006 | 0.548 +/- 0.134 | 0.056 +/- 0.018 | 0.234 +/- 0.028 | 0.172 +/- 0.076 | 0.0030 -> 0.0024 | 673 |
