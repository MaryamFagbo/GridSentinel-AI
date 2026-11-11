# GridSentinel AI - Algorithm description

Status: research prototype. Everything is **simulation** (pandapower benchmark grids, synthetic attacks). No real SCADA/PMU data was used.

## 1. Problem

A control centre estimates the grid state (voltage magnitude and angle at every bus) from meter readings `z` using AC state estimation (SE). If an attacker alters some readings (false data injection, FDI), the estimate can be wrong, and operators may act on it (e.g. voltage-limit decisions).

Two questions GridSentinel answers for every snapshot:

1. **Recovery:** can we clean the readings and get a better state estimate?
2. **Trust gate:** how far could the recovered estimate still be from the truth, and should the operator PROCEED, take CAUTION, or VALIDATE manually? The answer comes with a *calibrated* error bound.

## 2. Notation

- `z in R^m`: measurements (bus voltage magnitudes V, bus P/Q injections, line P/Q flows at both ends).
- `x`: state (V at all buses, angles at non-slack buses), `n = 2*nb - 1`.
- `h(x)`: AC measurement model, `H = dh/dx`: analytic Jacobian (checked against finite differences in tests).
- `sigma_i`: assumed standard deviation of meter i (sigma_V = 0.004 pu, sigma_P = sigma_Q = 1 MW/MVAr).
- Truth `x_true` is **never** used inside the live pipeline; it is used only to score results.

## 3. Live pipeline (`run_pipeline`, uses `z` and the public grid model only)

1. **WLS** by Gauss-Newton: `x <- x + (H^T W H)^-1 H^T W (z - h(x))`, `W = diag(1/sigma^2)`.
2. **Huber IRLS** (k = 1.5) as a robust second opinion.
3. **Residual analysis:** normalized residuals `rN_i = r_i / sqrt(Omega_ii)`; critical measurements (errors undetectable by redundancy) are flagged and never blamed. Robust scale `s = max(1, 1.4826 * MAD(rN))`; robust z-score `z_i = |rN_i| / s`.
4. **One-at-a-time isolation:** up to 16 rounds. Take the largest `z_i >= 4.5`, remove it only if the **observability guard** says the grid stays observable (smallest eigenvalue of the gain matrix >= 2% of reference), re-solve WLS. At most 25% of meters may be removed.
5. **Reinstatement:** isolated meters whose residual under the cleaned estimate is `< 2.5` robust sigma are put back.
6. **Per-meter trust score:** `trust = 100 * clip((6.5 - z)/(6.5 - 2.5), 0, 1)` (100% below z = 2.5, 0% at z >= 6.5).
7. **Eleven runtime features** are computed (no truth): log chi-square/dof after and before cleaning, largest remaining and first z-score, fraction isolated, max shift caused by recovery, WLS-vs-Huber disagreement, model std of V from the gain matrix, number of critical measurements, observability margin, observability-blocked flag.
8. **Hard fail** (no convergence, lost observability, or a suspicious meter that could not be removed) forces VALIDATE.

## 4. Trust gate (offline calibration, then online use)

**Offline** (per grid):
1. Generate scenarios: attacked/clean snapshots through the same live pipeline. Record features `f` and the true error `e = max_bus |V_est - V_true|`.
2. Train gradient-boosted trees (numpy; 120 rounds, depth 3, lr 0.08) on the *train* split to predict `y = log10(e)` from `f`.
3. **Split conformal:** on a separate *calibration* split compute residuals `R = y - y_hat`. Predictions are binned into 3 quantile bins (Mondrian conformal); each bin keeps its own sorted residuals.
4. For a new snapshot with bin `b`: `U = 10^(y_hat + R_b[k])`, `k = ceil((n_b + 1)(1 - alpha))`, alpha = 0.10.

**Guarantee (established, Vovk et al. / Lei et al. 2018; Mondrian variant):** if calibration and test scenarios are exchangeable (same generator), `P(e <= U) >= 1 - alpha` (marginal, per bin approximately). It is **not** a guarantee for attacks outside the generator, and it is not a guarantee conditional on PROCEED.

**Online decision** (`decide_level`): hard fail -> VALIDATE; `U <= 0.01 pu` -> PROCEED; else if estimated `P(e <= 0.01) >= 50%` -> CAUTION; else VALIDATE.

## 5. Data generation (simulation)

- Grid: pandapower `case14 / case30 / case57 / case118`; base power flow gives the operating point.
- Load scenario: global scale ~ U(0.8, 1.2) times per-load noise N(1, 0.05) clipped to [0.7, 1.3]; AC power flow gives `x_true`.
- Measurements: `h(x_true)` + Gaussian noise (sigma above).
- Attack mix (in-model): none 15%, random single 15%, single small 15%, multi-coordinated 15%, stealth partial 20%, adaptive (white-box against the trust rule) 20%. Attacker budget `K_MAX = 8` meters.
- Out-of-model test: `stealth_full` (a = H c on all relevant meters; the chi-square statistic is provably unchanged). GridSentinel does **not** claim to detect this; it is used to show hardening: protecting a small set of meters raises the attacker's cost.

## 6. Evaluation protocol

- Splits: n train / n calibration / n test scenarios per grid and per seed. Calibration is refit on every grid and seed (nothing is tuned on test).
- Metrics: bound coverage (target 0.90), PROCEED rate, unsafe-given-PROCEED (e > 0.01 pu), isolation recall (attacked meters isolated / attacked meters), clean false-alarm rate (clean snapshots with any isolation or hard fail), median error before/after recovery, runtime.
- Baselines (IEEE 14 batch evaluation, `batch_eval.py`): chi-square test, largest normalized residual (LNR > 3), Huber estimator, IsolationForest on raw z, always-proceed.
- Multi-grid: `multi_grid_eval.py` (see `docs/EXPERIMENTS.md`). The same hyper-parameters are used on every grid (no per-grid tuning).

## 7. Known limits (state these openly)

- Synthetic data only; the generator and the calibration come from the same family, so coverage holds *within* that family.
- Gaussian noise, static (single-snapshot) SE, no topology errors, no time dynamics.
- Fully stealthy attacks (`a = H c`) are invisible to residual-based detection by construction; only hardening (protecting meters) helps.
- Isolation recall on the mixed set is low because many attacks are stealth-partial/adaptive by design; the gate's job is to say *"I'm not sure"* rather than to detect everything.
- On larger grids the benefit of recovery shrinks (see experiments).

## 8. Reproduce

```bash
pip install -r requirements.txt
python batch_eval.py --n 300 --seed 7 --out results                  # IEEE 14 full evaluation
python multi_grid_eval.py --cases case14 case30 case57 --n 300 \
       --seeds 7 11 13 17 19 --out results_multigrid                 # multi-grid, multi-seed
python multi_grid_eval.py --cases case118 --n 200 --seeds 7 11 13 \
       --out results_multigrid_118
pytest test_gridsentinel.py
```

`multi_grid_eval.py` switches the grid by pointing `pandapower.networks.case14` at the requested case while the model is built, so no existing file had to change.

## 9. References (verified to exist)

- Y. Liu, P. Ning, M. Reiter, "False data injection attacks against state estimation in electric power grids", ACM CCS 2009 / ACM TISSEC 14(1), 2011.
- A. N. Angelopoulos, S. Bates, A. Fisch, L. Lei, T. Schuster, "Conformal Risk Control", ICLR 2024.
- V. Vovk, A. Gammerman, G. Shafer, *Algorithmic Learning in a Random World* (conformal prediction); J. Lei et al., "Distribution-free predictive inference for regression", JASA 2018.
- L. Thurner et al., pandapower, IEEE Trans. Power Systems 33(6), 2018.
- S. Nand, J. Zhang, Q. Hu, survey of ML methods for FDIA detection, IEEE Open Journal of the Computer Society, 2025.
