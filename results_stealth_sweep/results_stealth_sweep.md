# Perfect-stealth magnitude sweep (IEEE 14, simulation only)

seeds [7, 11, 13, 17, 19], 200 attacks per magnitude per seed.

dV = voltage shift forced on one bus by the attacker. 'Attack matters' = share of attacks whose recovered-state error exceeds 0.01 pu. 'Accepted and unsafe' = share of ALL attacks where the gate said PROCEED although the error exceeds tolerance.

| dV (pu) | Gate | Attack matters (error > 0.01 pu) | PROCEED rate | Accepted and unsafe |
|---|---|---|---|---|
| 0.005 | A (shipped) | 0.00 | 0.52 | 0.00 |
| 0.005 | H (hybrid) | 0.00 | 0.83 | 0.00 |
| 0.01 | A (shipped) | 0.48 | 0.52 | 0.24 |
| 0.01 | H (hybrid) | 0.48 | 0.61 | 0.30 |
| 0.02 | A (shipped) | 1.00 | 0.52 | 0.52 |
| 0.02 | H (hybrid) | 1.00 | 0.22 | 0.22 |
| 0.03 | A (shipped) | 1.00 | 0.50 | 0.50 |
| 0.03 | H (hybrid) | 1.00 | 0.01 | 0.01 |
| 0.05 | A (shipped) | 1.00 | 0.51 | 0.51 |
| 0.05 | H (hybrid) | 1.00 | 0.00 | 0.00 |
