"""
GridSentinel AI - core pipeline
================================
Trust-aware decision layer for smart-grid state estimation under false-data
injection attacks (FDIA), IEEE 14-bus system (pandapower).

DESIGN RULE (the "no oracle" rule)
----------------------------------
* `run_pipeline(model, z, cfg, calibration)` is the LIVE path. It receives only
  what a control-centre operator sees: the measurement vector `z`, the public
  network model, and an offline-calibrated gate. It never receives the true
  state, the attack label or the attacked meter list.
* Everything that needs the truth (scenario generation, attacks, error
  metrics, recovery tables) lives in clearly separated functions:
  `make_scenarios`, `apply_attack`, `recovery_table`, `evaluate_run`.

Measurement set (full): bus voltage magnitudes (14), bus P/Q injections (28),
branch P/Q flows at BOTH ends (80) = 122 measurements for 27 states.

Pipeline: robust (Huber) AC-WLS fit -> trust score per measurement from
normalized residuals with a median/MAD robust scale -> isolation with an
observability guard -> re-estimation on the trusted set -> runtime-only gate
features -> calibrated risk bound (split-conformal, Mondrian bins) ->
PROCEED / CAUTION / VALIDATE.
"""
from __future__ import annotations

import copy
import json
import math
import time
from dataclasses import dataclass, field

import numpy as np

KINDS = ("V", "Pinj", "Qinj", "Pf", "Qf", "Pt", "Qt")
FEATURE_NAMES = (
    "log_J",          # log10 of chi-square statistic per degree of freedom (retained set)
    "log_zmax",       # log10 of largest remaining robust z-score
    "frac_iso",       # fraction of measurements isolated
    "log_shift",      # log10 of max change in voltage estimate caused by recovery
    "log_disagree",   # log10 of max disagreement between WLS recovery and Huber estimate
    "log_sdV",        # log10 of model-based std of the voltage estimate (from gain matrix)
    "n_crit",         # number of critical (undetectable-error) measurements retained
    "obs_blocked",    # 1 if suspicious measurements could not be removed (observability)
    "log_obs",        # log10 of observability margin (relative smallest eigenvalue)
    "log_J_raw",      # log10 chi-square per dof of the RAW (uncleaned) WLS fit: conflict before cleaning
    "log_zfirst",     # log10 of the largest z-score seen BEFORE any isolation
)
K_MAX = 8  # threat model: attacker can compromise at most K_MAX meters
IN_MODEL_MIX = {
    "none": 0.15,
    "random_single": 0.15,
    "single_small": 0.15,
    "multi_coordinated": 0.15,
    "stealth_partial": 0.20,
    "adaptive": 0.20,
}
ATTACK_MODES = (
    "none", "random_single", "single_small", "multi_coordinated",
    "stealth_partial", "adaptive", "stealth_full", "custom_voltage", "custom_stealth",
)


# =============================================================================
# 1. Network / AC measurement model
# =============================================================================
@dataclass
class Fit:
    x: np.ndarray
    converged: bool
    iters: int


@dataclass
class Analysis:
    rN: np.ndarray        # normalized residuals (0 for critical / unavailable)
    crit: np.ndarray      # critical measurements (error undetectable)
    res: np.ndarray       # raw residuals z - h(x)
    Ginv: np.ndarray
    lam_min: float


class GridModel:
    """IEEE-14 AC measurement model h(x), Jacobian, WLS / Huber estimators."""

    def __init__(self, meas_set: str = "full", sigma_v: float = 0.004, sigma_pq: float = 1.0):
        import pandapower as pp
        import pandapower.networks as pn

        net = pn.case14()
        pp.runpp(net, calculate_voltage_angles=True, numba=False)
        ppc = net._ppc
        lk = np.asarray(net._pd2ppc_lookups["bus"])
        nb = len(net.bus)
        if not np.array_equal(lk[:nb], np.arange(nb)):
            raise RuntimeError("Unexpected bus ordering in pandapower ppc")
        internal = ppc["internal"]
        self.net = net
        self.base = float(ppc["baseMVA"])
        self.Ybus = np.asarray(internal["Ybus"].todense(), dtype=complex)
        self.Yf = np.asarray(internal["Yf"].todense(), dtype=complex)
        self.Yt = np.asarray(internal["Yt"].todense(), dtype=complex)
        br = ppc["branch"]
        self.f = br[:, 0].real.astype(int)
        self.t = br[:, 1].real.astype(int)
        self.nb = nb
        self.nl = len(self.f)
        self.slack = int(net.ext_grid.bus.iloc[0])
        self.nonref = np.array([b for b in range(nb) if b != self.slack])
        self.n_state = 2 * nb - 1
        self.Cf = np.zeros((self.nl, nb))
        self.Ct = np.zeros((self.nl, nb))
        self.Cf[np.arange(self.nl), self.f] = 1.0
        self.Ct[np.arange(self.nl), self.t] = 1.0

        self.kinds = np.array(["V"] * nb + ["Pinj"] * nb + ["Qinj"] * nb
                              + ["Pf"] * self.nl + ["Qf"] * self.nl + ["Pt"] * self.nl + ["Qt"] * self.nl)
        self.elem = np.concatenate([np.arange(nb)] * 3 + [np.arange(self.nl)] * 4)
        self.loc = np.concatenate([np.arange(nb)] * 3 + [self.f, self.f, self.t, self.t])
        self.m = len(self.kinds)
        self.sigma = np.where(self.kinds == "V", sigma_v, sigma_pq).astype(float)
        self.meas_set = meas_set
        if meas_set == "full":
            self.avail = np.ones(self.m, bool)
        elif meas_set == "basic":  # voltages + injections only (ablation)
            self.avail = np.isin(self.kinds, ["V", "Pinj", "Qinj"])
        else:
            raise ValueError("meas_set must be 'full' or 'basic'")
        self.names = []
        for k, e in zip(self.kinds, self.elem):
            if k == "V":
                self.names.append(f"V@B{e + 1}")
            elif k in ("Pinj", "Qinj"):
                self.names.append(f"{k[0]}_inj@B{e + 1}")
            else:
                a, b = (self.f[e], self.t[e]) if k.endswith("f") else (self.t[e], self.f[e])
                self.names.append(f"{k[0]}_flow B{a + 1}->B{b + 1}")
        self.iV = np.arange(nb)  # measurement indices of voltage meters
        self.stateV = (nb - 1) + np.arange(nb)  # state indices of voltage magnitudes

        V0 = net.res_bus.vm_pu.values.copy()
        th0 = np.deg2rad(net.res_bus.va_degree.values)
        self.x_base = self.pack(V0, th0)
        self.lam_ref = self.obs_lambda(self.x_base, self.avail)

    # -- state packing ---------------------------------------------------
    def pack(self, V, th):
        return np.concatenate([np.asarray(th)[self.nonref], np.asarray(V)])

    def unpack(self, x):
        th = np.zeros(self.nb)
        th[self.nonref] = x[: self.nb - 1]
        return np.asarray(x[self.nb - 1:]), th

    def flat_start(self):
        return self.pack(np.ones(self.nb), np.zeros(self.nb))

    # -- measurement function and Jacobian ---------------------------------
    def h(self, x):
        V, th = self.unpack(x)
        Vc = V * np.exp(1j * th)
        Sb = Vc * np.conj(self.Ybus @ Vc) * self.base
        Sf = Vc[self.f] * np.conj(self.Yf @ Vc) * self.base
        St = Vc[self.t] * np.conj(self.Yt @ Vc) * self.base
        return np.concatenate([V, Sb.real, Sb.imag, Sf.real, Sf.imag, St.real, St.imag])

    def jac(self, x):
        V, th = self.unpack(x)
        nb = self.nb
        Vc = V * np.exp(1j * th)
        Vn = np.exp(1j * th)
        Ib = self.Ybus @ Vc
        dV = np.diag(Vc)
        dVn = np.diag(Vn)
        dSb_dVm = dV @ np.conj(self.Ybus @ dVn) + np.conj(np.diag(Ib)) @ dVn
        dSb_dVa = 1j * dV @ np.conj(np.diag(Ib) - self.Ybus @ dV)
        If = self.Yf @ Vc
        It = self.Yt @ Vc
        dVf = np.diag(Vc[self.f])
        dVt = np.diag(Vc[self.t])
        dSf_dVa = 1j * (np.conj(np.diag(If)) @ self.Cf @ dV - dVf @ np.conj(self.Yf @ dV))
        dSf_dVm = dVf @ np.conj(self.Yf @ dVn) + np.conj(np.diag(If)) @ self.Cf @ dVn
        dSt_dVa = 1j * (np.conj(np.diag(It)) @ self.Ct @ dV - dVt @ np.conj(self.Yt @ dV))
        dSt_dVm = dVt @ np.conj(self.Yt @ dVn) + np.conj(np.diag(It)) @ self.Ct @ dVn
        nr = self.nonref
        b = self.base

        def blk(dVa, dVm, part):
            return np.hstack([part(dVa)[:, nr], part(dVm)]) * b

        HV = np.hstack([np.zeros((nb, nb - 1)), np.eye(nb)])
        return np.vstack([
            HV,
            blk(dSb_dVa, dSb_dVm, np.real), blk(dSb_dVa, dSb_dVm, np.imag),
            blk(dSf_dVa, dSf_dVm, np.real), blk(dSf_dVa, dSf_dVm, np.imag),
            blk(dSt_dVa, dSt_dVm, np.real), blk(dSt_dVa, dSt_dVm, np.imag),
        ])

    # -- estimators ----------------------------------------------------------
    def wls(self, z, active, sig_eff=None, x0=None, max_iter=30, tol=1e-6) -> Fit:
        sig = self.sigma if sig_eff is None else sig_eff
        idx = np.where(active)[0]
        w = 1.0 / sig[idx] ** 2
        zi = z[idx]
        x = self.flat_start() if x0 is None else np.array(x0, float)

        def cost(xx):
            r = zi - self.h(xx)[idx]
            return float(np.sum(w * r * r))

        c = cost(x)
        for it in range(max_iter):
            r = zi - self.h(x)[idx]
            H = self.jac(x)[idx]
            G = H.T @ (H * w[:, None])
            g = H.T @ (w * r)
            try:
                dx = np.linalg.solve(G, g)
            except np.linalg.LinAlgError:
                return Fit(x, False, it)
            step = 1.0
            xn, cn = x, c
            for _ in range(10):
                xn = x + step * dx
                xn[self.nb - 1:] = np.maximum(xn[self.nb - 1:], 0.3)
                cn = cost(xn)
                if np.isfinite(cn) and cn <= c * (1 + 1e-12):
                    break
                step *= 0.5
            x, c = xn, cn
            if np.max(np.abs(step * dx)) < tol:
                return Fit(x, True, it + 1)
        return Fit(x, False, max_iter)

    def huber(self, z, active, x0=None, k=1.5, iters=8) -> Fit:
        sig = self.sigma
        sig_eff = sig.copy()
        x = x0
        fit = None
        for _ in range(iters):
            fit = self.wls(z, active, sig_eff, x0=x)
            if not fit.converged:
                return fit
            x = fit.x
            r = np.abs(z - self.h(x)) / sig
            wgt = np.minimum(1.0, k / np.maximum(r, 1e-9))
            new = sig / np.sqrt(wgt)
            if np.max(np.abs(new - sig_eff) / sig_eff) < 1e-3:
                break
            sig_eff = new
        return fit

    # -- diagnostics -------------------------------------------------------------
    def analyze(self, z, x, active) -> Analysis:
        H = self.jac(x)
        w = 1.0 / self.sigma ** 2
        Ha = H[active]
        G = Ha.T @ (Ha * w[active][:, None])
        try:
            Ginv = np.linalg.inv(G)
        except np.linalg.LinAlgError:
            Ginv = np.linalg.pinv(G)
        lam = float(np.linalg.eigvalsh(G)[0])
        Q = np.einsum("ij,jk,ik->i", H, Ginv, H)
        res = z - self.h(x)
        s2 = self.sigma ** 2
        var = np.where(active, s2 - Q, s2 + Q)
        crit = active & (var < 0.02 * s2)
        rN = res / np.sqrt(np.maximum(var, 1e-12))
        rN = np.where(crit | ~self.avail, 0.0, rN)
        return Analysis(rN=rN, crit=crit, res=res, Ginv=Ginv, lam_min=lam)

    def obs_lambda(self, x, active) -> float:
        H = self.jac(x)[active]
        G = H.T @ (H / (self.sigma[active] ** 2)[:, None])
        return float(np.linalg.eigvalsh(G)[0])

    def obs_ratio(self, x, active) -> float:
        return max(0.0, self.obs_lambda(x, active)) / self.lam_ref


# =============================================================================
# 2. Scenarios (TRUTH LIVES HERE - never passed to run_pipeline)
# =============================================================================
@dataclass
class Scenario:
    x_true: np.ndarray
    z_true: np.ndarray   # noise-free measurements
    noise: np.ndarray
    load_factor: float

    @property
    def z_clean(self):
        return self.z_true + self.noise


def make_scenarios(model: GridModel, n: int, rng, load_range=(0.8, 1.2), per_load_sd=0.05):
    """n operating points: global load swing +-20%, per-load variation, AC power flow."""
    import pandapower as pp

    net = copy.deepcopy(model.net)
    p0 = net.load.p_mw.values.copy()
    q0 = net.load.q_mvar.values.copy()
    out, tries = [], 0
    while len(out) < n and tries < 6 * n + 20:
        tries += 1
        g = rng.uniform(*load_range)
        fct = g * np.clip(1 + rng.normal(0, per_load_sd, len(p0)), 0.7, 1.3)
        net.load["p_mw"] = p0 * fct
        net.load["q_mvar"] = q0 * fct
        try:
            pp.runpp(net, calculate_voltage_angles=True, init="results", numba=False)
        except Exception:
            try:
                pp.runpp(net, calculate_voltage_angles=True, init="flat", numba=False)
            except Exception:
                continue
        V = net.res_bus.vm_pu.values.copy()
        th = np.deg2rad(net.res_bus.va_degree.values)
        x = model.pack(V, th)
        out.append(Scenario(x, model.h(x), rng.normal(0.0, model.sigma), float(g)))
    return out


# =============================================================================
# 3. Attacks (evaluation / demo only)
# =============================================================================
@dataclass
class AttackInfo:
    mode: str
    bias: np.ndarray
    idx: np.ndarray
    target_bus: int | None = None
    meta: dict = field(default_factory=dict)

    @property
    def attacked_buses(self):
        return self.meta.get("attacked_buses", [])


def _stealth_bias(model, x_true, bus, dV, dth):
    """a = h(x+c) - h(x): consistent with the AC model, invisible to residual tests
    if the attacker controls every meter in the support of `a`."""
    V, th = model.unpack(x_true)
    V, th = V.copy(), th.copy()
    V[bus] += dV
    if bus != model.slack:
        th[bus] += dth
    return model.h(model.pack(V, th)) - model.h(x_true)


def _attacked_buses(model, idx):
    return sorted({int(model.loc[i]) for i in idx})


def _cfg_default():
    return PipelineConfig()


def quick_detect(model, z, cfg=None) -> bool:
    """White-box detection stage used by the adaptive attacker: would the first
    isolation round flag anything?"""
    cfg = cfg or _cfg_default()
    avail = model.avail
    plain = model.wls(z, avail)
    hub = model.huber(z, avail, x0=plain.x if plain.converged else None, k=cfg.huber_k)
    if not hub.converged:
        return True
    ana = model.analyze(z, hub.x, avail)
    s = _robust_scale(ana.rN, avail & ~ana.crit)
    zs = np.abs(ana.rN) / s
    return bool(np.any(avail & ~ana.crit & (zs >= cfg.z_iso)))


SUPPORT_EPS = 0.1  # a meter is "in the support" if the attack must move it by >= 0.1 sigma


def apply_attack(model: GridModel, sc: Scenario, mode: str, rng, cfg=None, bus=None, size=None,
                 protected=None):
    """Returns (z_attacked, AttackInfo). `bus` (0-based) and `size` for custom modes.
    `protected`: meter indices the attacker cannot touch (hardened meters)."""
    protected = np.zeros(model.m, bool) if protected is None else np.asarray(protected, bool)
    z = sc.z_clean.copy()
    avail_idx = np.where(model.avail)[0]
    sig = model.sigma
    bias = np.zeros(model.m)
    meta: dict = {}
    target = None

    if mode == "none":
        pass
    elif mode == "random_single":
        i = int(rng.choice(avail_idx))
        bias[i] = rng.choice([-1, 1]) * rng.uniform(10, 60) * sig[i]
    elif mode == "single_small":
        i = int(rng.choice(avail_idx))
        bias[i] = rng.choice([-1, 1]) * rng.uniform(3, 8) * sig[i]
    elif mode == "multi_coordinated":
        k = int(rng.integers(2, 6))
        center = int(rng.integers(model.nb))
        nbrs = set([center]) | {int(model.t[e]) for e in np.where(model.f == center)[0]} \
            | {int(model.f[e]) for e in np.where(model.t == center)[0]}
        pool = [i for i in avail_idx if int(model.loc[i]) in nbrs]
        pick = rng.choice(pool, size=min(k, len(pool)), replace=False)
        sign_by_kind = {kd: rng.choice([-1, 1]) for kd in KINDS}
        for i in pick:
            bias[int(i)] = sign_by_kind[model.kinds[i]] * rng.uniform(3, 15) * sig[i]
        target = center
    elif mode in ("stealth_partial", "adaptive", "stealth_full", "custom_stealth"):
        b = int(rng.integers(model.nb)) if bus is None else int(bus)
        target = b
        sign = rng.choice([-1, 1])
        dV0 = sign * (rng.uniform(0.03, 0.08) if size is None else abs(size))
        if size is not None and size < 0:
            dV0 = -abs(size)
        dth0 = 0.0
        a_full = _stealth_bias(model, sc.x_true, b, dV0, dth0) * model.avail
        support = np.where(np.abs(a_full) / sig > SUPPORT_EPS)[0]
        order = np.array([i for i in support[np.argsort(-np.abs(a_full[support]) / sig[support])]
                          if not protected[i]], dtype=int)
        meta.update(support_size=int(support.size), stealth_cost=int(support.size),
                    protected_in_support=int(protected[support].sum()))
        if mode in ("stealth_full", "custom_stealth"):
            bias[order] = a_full[order]          # controls everything it is allowed to touch
            meta["controlled"] = int(len(order))
        elif mode == "stealth_partial":
            ctrl = order[: min(K_MAX, order.size)]
            bias[ctrl] = a_full[ctrl]
            meta["controlled"] = int(len(ctrl))
        else:  # adaptive: white-box against the trust rule, budget K_MAX
            ctrl = order[: min(K_MAX, order.size)]
            mask = np.zeros(model.m)
            mask[ctrl] = 1.0
            lo, hi = 0.0, 1.0
            for _ in range(7):
                s = 0.5 * (lo + hi)
                a_s = _stealth_bias(model, sc.x_true, b, s * dV0, 0.0) * mask * model.avail
                if quick_detect(model, z + a_s, cfg):
                    hi = s
                else:
                    lo = s
            bias = _stealth_bias(model, sc.x_true, b, lo * dV0, 0.0) * mask * model.avail
            meta.update(controlled=int(len(ctrl)), adaptive_scale=float(lo), dV=float(lo * dV0))
    elif mode == "custom_voltage":
        b = int(rng.integers(model.nb)) if bus is None else int(bus)
        amount = float(rng.uniform(0.05, 0.15) if size is None else size)
        bias[model.iV[b]] = amount
        target = b
    else:
        raise ValueError(f"unknown attack mode {mode}")

    bias = np.where(protected, 0.0, bias)
    idx = np.where(np.abs(bias) > 0)[0]
    meta["attacked_buses"] = _attacked_buses(model, idx)
    return z + bias, AttackInfo(mode, bias, idx, target, meta)


# =============================================================================
# 4. LIVE PIPELINE (operator-visible inputs only)
# =============================================================================
@dataclass
class PipelineConfig:
    z_iso: float = 4.5         # robust z-score at which a measurement is isolated (trust 50%)
    z_full: float = 2.5        # z-score up to which trust is 100%
    z_zero: float = 6.5        # z-score at which trust is 0%
    z_reinstate: float = 2.5
    max_rounds: int = 16       # one-at-a-time removal (largest normalized residual first)
    iso_per_round: int = 1
    max_iso_frac: float = 0.25
    huber_k: float = 1.5
    use_trust: bool = True     # ablation switch
    use_obs_guard: bool = True  # ablation switch
    obs_ratio_min: float = 0.02
    tol_pu: float = 0.01       # voltage tolerance defining an unsafe recovery
    alpha: float = 0.10        # target risk level of the calibrated bound
    caution_conf: float = 0.50
    v_limits: tuple = (0.95, 1.05)


def decide_level(bound, conf, hard_fail, cfg):
    """Gate rule (shared by the live pipeline and the batch evaluation)."""
    if hard_fail:
        return "red", "VALIDATE - operator review required"
    if bound <= cfg.tol_pu:
        return "green", "PROCEED with recovered state"
    if conf >= 100.0 * cfg.caution_conf:
        return "yellow", "CAUTION - proceed only with extra checks"
    return "red", "VALIDATE - operator review required"


def _robust_scale(rN, mask):
    v = rN[mask]
    if v.size < 5:
        return 1.0
    return max(1.0, 1.4826 * float(np.median(np.abs(v - np.median(v)))))


@dataclass
class PipelineResult:
    converged: bool
    plain_V: np.ndarray
    huber_V: np.ndarray
    rec_V: np.ndarray
    rec_x: np.ndarray
    iso: np.ndarray                 # bool mask over measurements
    blocked: list
    z_score: np.ndarray
    trust: np.ndarray               # per measurement, 0-100
    bus_trust: np.ndarray           # per bus, 0-100 (min over meters located there)
    crit: np.ndarray
    features: dict
    fvec: np.ndarray
    obs_ok: bool
    conf: float | None              # calibrated P(max voltage error <= tol), 0-100
    bound_pu: float | None          # calibrated upper bound on max voltage error
    level: str                      # green / yellow / red / grey
    label: str
    reasons: list
    ms: float
    hard_fail: bool = False
    names: list = field(default_factory=list)

    @property
    def iso_idx(self):
        return np.where(self.iso)[0]

    @property
    def iso_names(self):
        return [self.names[i] for i in self.iso_idx]


def run_pipeline(model: GridModel, z: np.ndarray, cfg: PipelineConfig | None = None,
                 calibration: "GateCalibration | None" = None) -> PipelineResult:
    """LIVE PATH. Inputs: measurements, public model, offline-calibrated gate. Nothing else."""
    cfg = cfg or PipelineConfig()
    t0 = time.perf_counter()
    avail = model.avail
    m_av = int(avail.sum())

    plain = model.wls(z, avail)
    hub = model.huber(z, avail, x0=plain.x if plain.converged else None, k=cfg.huber_k)
    converged = bool(hub.converged)
    iso = np.zeros(model.m, bool)
    z_at_iso = np.zeros(model.m)
    blocked: list = []
    z_first = None
    fit = hub if converged else plain

    if cfg.use_trust and converged:
        max_iso = int(cfg.max_iso_frac * m_av)
        for _ in range(cfg.max_rounds):
            act = avail & ~iso
            ana = model.analyze(z, fit.x, act)
            s = _robust_scale(ana.rN, act & ~ana.crit)
            zs = np.abs(ana.rN) / s
            if z_first is None:
                z_first = float(zs[act & ~ana.crit].max())
            cand = np.where(act & ~ana.crit & (zs >= cfg.z_iso))[0]
            if cand.size == 0:
                break
            changed = False
            took = 0
            for i in cand[np.argsort(-zs[cand])]:
                if iso.sum() >= max_iso or took >= cfg.iso_per_round:
                    break
                trial = iso.copy()
                trial[i] = True
                if cfg.use_obs_guard and model.obs_ratio(fit.x, avail & ~trial) < cfg.obs_ratio_min:
                    if int(i) not in blocked:
                        blocked.append(int(i))
                    continue
                iso = trial
                z_at_iso[i] = zs[i]
                changed = True
                took += 1
            if not changed:
                break
            new = model.wls(z, avail & ~iso, x0=fit.x)
            if not new.converged:
                break
            fit = new
        # reinstate measurements that agree with the cleaned estimate
        if iso.any():
            act = avail & ~iso
            ana = model.analyze(z, fit.x, act)
            s = _robust_scale(ana.rN, act & ~ana.crit)
            back = [i for i in np.where(iso)[0] if abs(ana.rN[i]) / s < cfg.z_reinstate]
            if back:
                iso[back] = False
                new = model.wls(z, avail & ~iso, x0=fit.x)
                if new.converged:
                    fit = new
                else:
                    iso[back] = True

    act = avail & ~iso
    ana = model.analyze(z, fit.x, act)
    s_f = _robust_scale(ana.rN, act & ~ana.crit)
    zs_f = np.abs(ana.rN) / s_f
    z_score = np.where(iso & (z_at_iso > 0), z_at_iso, zs_f)
    trust = 100.0 * np.clip((cfg.z_zero - z_score) / (cfg.z_zero - cfg.z_full), 0.0, 1.0)
    trust = np.where(model.avail, trust, np.nan)
    bus_trust = np.array([np.nanmin(trust[(model.loc == b) & model.avail]) for b in range(model.nb)])

    r = (z - model.h(fit.x))[act] / model.sigma[act]
    df = max(int(act.sum()) - model.n_state, 1)
    J_norm = float(np.sum(r * r) / df)
    Vp, _ = model.unpack(plain.x)
    Vh, _ = model.unpack(hub.x)
    Vr, _ = model.unpack(fit.x)
    shift = float(np.max(np.abs(Vr - Vp))) if plain.converged else 1.0
    disagree = float(np.max(np.abs(Vr - Vh))) if converged else 1.0
    sdV = float(np.sqrt(np.max(np.diag(ana.Ginv)[model.stateV])))
    ratio = max(ana.lam_min, 0.0) / model.lam_ref
    obs_ok = ratio >= cfg.obs_ratio_min
    if plain.converged:
        r_raw = (z - model.h(plain.x))[avail] / model.sigma[avail]
        J_raw = float(np.sum(r_raw * r_raw) / max(m_av - model.n_state, 1))
    else:
        J_raw = 1e3
    if z_first is None:
        z_first = float(np.max(zs_f[act & ~ana.crit])) if np.any(act & ~ana.crit) else 0.0
    feats = {
        "log_J": math.log10(J_norm + 1e-3),
        "log_zmax": math.log10(float(np.max(zs_f[act & ~ana.crit])) + 0.1) if np.any(act & ~ana.crit) else 0.0,
        "frac_iso": float(iso.sum() / m_av),
        "log_shift": math.log10(shift + 1e-5),
        "log_disagree": math.log10(disagree + 1e-5),
        "log_sdV": math.log10(sdV + 1e-6),
        "n_crit": float(ana.crit.sum()),
        "obs_blocked": 1.0 if blocked else 0.0,
        "log_obs": math.log10(ratio + 1e-6),
        "log_J_raw": math.log10(J_raw + 1e-3),
        "log_zfirst": math.log10(z_first + 0.1),
    }
    fvec = np.array([feats[n] for n in FEATURE_NAMES])

    conf = bound = None
    level, label, reasons = "grey", "NOT CALIBRATED", []
    hard_fail = (not converged) or (not fit.converged) or (not obs_ok) or bool(blocked)
    if calibration is not None:
        conf = 100.0 * calibration.prob_within(fvec, cfg.tol_pu)
        bound = calibration.bound(fvec, cfg.alpha)
        level, label = decide_level(bound, conf, hard_fail, cfg)
    if not converged:
        reasons.append("State estimation did not converge: input data is inconsistent.")
    if blocked:
        reasons.append(f"{len(blocked)} suspicious measurement(s) could not be removed without losing observability.")
    if not obs_ok:
        reasons.append("Remaining measurements do not make the grid observable.")
    if iso.any():
        reasons.append("Isolated: " + ", ".join(model.names[i] for i in np.where(iso)[0][:6])
                       + (" ..." if iso.sum() > 6 else ""))
    else:
        reasons.append("No measurement isolated (all residuals within the noise level).")
    reasons.append(f"Recovery changed the voltage estimate by up to {shift:.4f} pu versus the raw estimate.")
    if bound is not None:
        reasons.append(f"Calibrated risk bound on the voltage error: {bound:.4f} pu "
                       f"(tolerance {cfg.tol_pu} pu, target risk {cfg.alpha:.0%}).")

    return PipelineResult(
        converged=converged, plain_V=Vp, huber_V=Vh, rec_V=Vr, rec_x=fit.x, iso=iso, blocked=blocked,
        z_score=z_score, trust=trust, bus_trust=bus_trust, crit=ana.crit, features=feats, fvec=fvec,
        obs_ok=bool(obs_ok), conf=conf, bound_pu=bound, level=level, label=label, reasons=reasons,
        ms=(time.perf_counter() - t0) * 1000.0, hard_fail=bool(hard_fail), names=model.names,
    )


# =============================================================================
# 5. Calibrated gate (boosted trees + split-conformal, Mondrian bins on the prediction)
# =============================================================================
class BoostedTrees:
    """Tiny gradient-boosted regression trees (numpy only, JSON-serialisable)."""

    def __init__(self, n_rounds=120, lr=0.08, depth=3, min_leaf=10, n_thr=20, subsample=0.8, seed=0):
        self.n_rounds, self.lr, self.depth = n_rounds, lr, depth
        self.min_leaf, self.n_thr, self.subsample, self.seed = min_leaf, n_thr, subsample, seed
        self.init = 0.0
        self.trees: list = []

    def _build(self, X, r, depth):
        n = len(r)
        if depth == 0 or n < 2 * self.min_leaf:
            return {"v": float(r.mean()) if n else 0.0}
        best = None
        tot, tot_n = r.sum(), n
        for j in range(X.shape[1]):
            col = X[:, j]
            thr = np.unique(np.quantile(col, np.linspace(0, 1, self.n_thr + 2)[1:-1]))
            for t in thr:
                left = col <= t
                nl = int(left.sum())
                if nl < self.min_leaf or n - nl < self.min_leaf:
                    continue
                sl = r[left].sum()
                gain = sl * sl / nl + (tot - sl) ** 2 / (tot_n - nl)
                if best is None or gain > best[0]:
                    best = (gain, j, float(t))
        if best is None:
            return {"v": float(r.mean())}
        _, j, t = best
        left = X[:, j] <= t
        return {"f": j, "t": t, "l": self._build(X[left], r[left], depth - 1),
                "r": self._build(X[~left], r[~left], depth - 1)}

    @staticmethod
    def _walk(node, x):
        while "v" not in node:
            node = node["l"] if x[node["f"]] <= node["t"] else node["r"]
        return node["v"]

    def fit(self, X, y):
        X, y = np.asarray(X, float), np.asarray(y, float)
        rng = np.random.default_rng(self.seed)
        self.init = float(y.mean())
        pred = np.full(len(y), self.init)
        self.trees = []
        for _ in range(self.n_rounds):
            idx = rng.choice(len(y), max(int(self.subsample * len(y)), 2 * self.min_leaf), replace=False)
            tree = self._build(X[idx], (y - pred)[idx], self.depth)
            self.trees.append(tree)
            pred += self.lr * np.array([self._walk(tree, x) for x in X])
        return self

    def predict_one(self, x):
        x = np.asarray(x, float)
        return self.init + self.lr * sum(self._walk(t, x) for t in self.trees)

    def to_dict(self):
        return {"init": self.init, "lr": self.lr, "trees": self.trees}

    @classmethod
    def from_dict(cls, d):
        m = cls(lr=d["lr"])
        m.init, m.trees = d["init"], d["trees"]
        return m


class GateCalibration:
    """Offline: boosted trees predict log10(max voltage error) from RUNTIME features;
    split-conformal residual quantiles (per bin of the prediction) turn the prediction
    into a bound U with P(error <= U) >= 1 - alpha under the calibration distribution.
    Online: only the feature vector is needed - no truth."""

    def __init__(self, model, edges, bin_res, tol, alpha, meta=None):
        self.model = model
        self.edges = np.asarray(edges, float)
        self.bin_res = [np.sort(np.asarray(r, float)) for r in bin_res]
        self.tol = float(tol)
        self.alpha = float(alpha)
        self.meta = meta or {}

    @classmethod
    def fit(cls, X_train, err_train, X_cal, err_cal, tol=0.01, alpha=0.10, n_bins=3, seed=0):
        X_train, X_cal = np.asarray(X_train, float), np.asarray(X_cal, float)
        y_tr = np.log10(np.maximum(np.asarray(err_train, float), 1e-6))
        y_ca = np.log10(np.maximum(np.asarray(err_cal, float), 1e-6))
        bt = BoostedTrees(seed=seed).fit(X_train, y_tr)
        yhat_cal = np.array([bt.predict_one(x) for x in X_cal])
        res = y_ca - yhat_cal
        n_bins = max(1, min(n_bins, len(res) // 80))
        edges = np.quantile(yhat_cal, np.linspace(0, 1, n_bins + 1)[1:-1]) if n_bins > 1 else np.array([])
        bidx = np.searchsorted(edges, yhat_cal)
        bin_res = [res[bidx == b] for b in range(n_bins)]
        meta = {"n_train": int(len(y_tr)), "n_cal": int(len(y_ca)), "n_bins": int(n_bins)}
        return cls(bt, edges, bin_res, tol, alpha, meta)

    def predict_log(self, fvec):
        return float(self.model.predict_one(fvec))

    def _bin(self, yhat):
        return int(np.searchsorted(self.edges, yhat))

    def prob_within(self, fvec, tol=None):
        tol = self.tol if tol is None else tol
        yhat = self.predict_log(fvec)
        R = self.bin_res[self._bin(yhat)]
        return float(np.sum(R <= math.log10(tol) - yhat) / (len(R) + 1))

    def bound(self, fvec, alpha=None):
        alpha = self.alpha if alpha is None else alpha
        yhat = self.predict_log(fvec)
        R = self.bin_res[self._bin(yhat)]
        k = math.ceil((len(R) + 1) * (1 - alpha))
        if k > len(R):
            return float("inf")
        return float(10 ** (yhat + R[k - 1]))

    def to_json(self):
        return json.dumps({
            "model": self.model.to_dict(), "edges": self.edges.tolist(),
            "bin_res": [r.tolist() for r in self.bin_res], "tol": self.tol, "alpha": self.alpha,
            "meta": self.meta, "features": list(FEATURE_NAMES),
        })

    @classmethod
    def from_json(cls, s):
        d = json.loads(s)
        if d.get("features") != list(FEATURE_NAMES):
            raise ValueError("Calibration file does not match the current feature set; re-run batch_eval.py")
        return cls(BoostedTrees.from_dict(d["model"]), d["edges"], d["bin_res"], d["tol"], d["alpha"], d.get("meta"))


# =============================================================================
# 6. Evaluation helpers (use the truth: demo / batch only)
# =============================================================================
def true_error(model, x_true, V_est) -> float:
    Vt, _ = model.unpack(x_true)
    return float(np.max(np.abs(np.asarray(V_est) - Vt)))


def limit_violations(V, limits=(0.95, 1.05)):
    V = np.asarray(V)
    return sorted(int(b) for b in np.where((V < limits[0]) | (V > limits[1]))[0])


def recovery_table(model, res: PipelineResult, z, x_true, info: AttackInfo | None, cfg=None):
    """Recovery Accuracy Evaluation (EVALUATION ONLY - never used by the live path).
    Columns: true voltage, attacked reading, naive WLS estimate, reconstructed voltage and errors."""
    cfg = cfg or PipelineConfig()
    Vt, _ = model.unpack(x_true)
    attacked = set(info.attacked_buses) if info is not None else set()
    iso_buses = {int(model.loc[i]) for i in res.iso_idx}
    rows = []
    for b in range(model.nb):
        role = "ATTACKED+ISOLATED" if (b in attacked and b in iso_buses) else \
            "ATTACKED" if b in attacked else "ISOLATED (false alarm)" if b in iso_buses else "-"
        rows.append({
            "Bus": f"B{b + 1}",
            "True voltage (pu)": round(float(Vt[b]), 4),
            "Attacked reading (pu)": round(float(z[model.iV[b]]), 4),
            "Naive estimate (pu)": round(float(res.plain_V[b]), 4),
            "Reconstructed (pu)": round(float(res.rec_V[b]), 4),
            "Reconstruction error (pu)": round(float(abs(res.rec_V[b] - Vt[b])), 4),
            "Naive error (pu)": round(float(abs(res.plain_V[b] - Vt[b])), 4),
            "Role": role,
        })
    err = np.abs(res.rec_V - Vt)
    naive = np.abs(res.plain_V - Vt)
    mx = float(err.max())
    if mx <= cfg.tol_pu:
        note = f"Recovery is close to the reference (max error {mx:.4f} pu <= {cfg.tol_pu} pu)."
    elif mx <= 3 * cfg.tol_pu:
        note = f"Recovery is acceptable but not tight (max error {mx:.4f} pu)."
    else:
        note = f"Recovery deviates strongly from the reference (max error {mx:.4f} pu): do not rely on it."
    return rows, {"max_error": mx, "mean_error": float(err.mean()), "naive_max_error": float(naive.max()),
                  "naive_mean_error": float(naive.mean()), "note": note}


def consequence_view(model, res: PipelineResult, x_true, cfg=None):
    """What the operator would conclude from voltage-limit checks on each state."""
    cfg = cfg or PipelineConfig()
    Vt, _ = model.unpack(x_true)
    t = limit_violations(Vt, cfg.v_limits)
    n = limit_violations(res.plain_V, cfg.v_limits)
    r = limit_violations(res.rec_V, cfg.v_limits)
    lab = lambda s: ", ".join(f"B{b + 1}" for b in s) or "none"
    return {
        "true": lab(t), "naive": lab(n), "recovered": lab(r),
        "naive_wrong_action": n != t, "recovered_wrong_action": r != t,
    }


def run_gridsentinel(seed=None, attack_mode="random_single", model=None, calibration=None,
                     cfg=None, bus=None, size=None):
    """Convenience API for demos and notebooks. Returns operator-view and evaluation-view keys."""
    model = model or GridModel()
    cfg = cfg or PipelineConfig()
    rng = np.random.default_rng(seed)
    sc = make_scenarios(model, 1, rng)[0]
    z, info = apply_attack(model, sc, attack_mode, rng, cfg, bus=bus, size=size)
    if calibration is None:
        calibration = get_default_calibration(model, cfg=cfg)
    res = run_pipeline(model, z, cfg, calibration)        # <- live path: z only
    rows, summary = recovery_table(model, res, z, sc.x_true, info, cfg)
    return {
        # operator view
        "level": res.level, "label": res.label, "conf": res.conf, "bound_pu": res.bound_pu,
        "isolated": res.iso_names, "success": res.converged, "residual_norm": res.features["log_J"],
        "reasons": res.reasons, "bus_trust": res.bus_trust,
        # evaluation view (demo only)
        "attack_mode": attack_mode, "attack_buses": [b + 1 for b in info.attacked_buses],
        "recovery_rows": rows, "recovery": summary, "consequence": consequence_view(model, res, sc.x_true, cfg),
        "true_error": true_error(model, sc.x_true, res.rec_V),
        "result": res, "scenario": sc, "attack": info, "z": z,
    }


# =============================================================================
# 7. Calibration builder + hardening ranking
# =============================================================================
def build_calibration(model, n_train=300, n_cal=300, seed=7, cfg=None, mix=None, progress=None):
    """Generate attacked scenarios, run the LIVE pipeline, and fit the gate offline."""
    cfg = cfg or PipelineConfig()
    mix = mix or IN_MODEL_MIX
    rng = np.random.default_rng(seed)
    modes = list(mix.keys())
    probs = np.array([mix[k] for k in modes], float)
    probs /= probs.sum()
    feats, errs = [], []
    for k, n in enumerate((n_train, n_cal)):
        F, E = [], []
        for sc in make_scenarios(model, n, rng):
            mode = str(rng.choice(modes, p=probs))
            z, _ = apply_attack(model, sc, mode, rng, cfg)
            res = run_pipeline(model, z, cfg)
            F.append(res.fvec)
            E.append(true_error(model, sc.x_true, res.rec_V))
            if progress:
                progress(len(F) + k * n_train, n_train + n_cal)
        feats.append(np.array(F))
        errs.append(np.array(E))
    return GateCalibration.fit(feats[0], errs[0], feats[1], errs[1], cfg.tol_pu, cfg.alpha)


def get_default_calibration(model, path="gate_calibration.json", cfg=None, quick_n=240, seed=7):
    import os
    if os.path.exists(path):
        try:
            return GateCalibration.from_json(open(path).read())
        except Exception:
            pass
    cal = build_calibration(model, quick_n, quick_n, seed, cfg)
    try:
        open(path, "w").write(cal.to_json())
    except OSError:
        pass
    return cal


def stealth_costs(model: GridModel, x=None):
    """For each bus: meters an attacker must control to shift that bus's voltage
    stealthily (single-bus, voltage-targeting). Lower = easier to attack."""
    x = model.x_base if x is None else x
    out = []
    for b in range(model.nb):
        a = _stealth_bias(model, x, b, 0.03, 0.0) * model.avail
        out.append(np.where(np.abs(a) / model.sigma > SUPPORT_EPS)[0])
    return out


def hardening_plan(model: GridModel):
    """Greedy hitting set: fewest meters whose protection blocks every single-bus
    voltage-targeting stealth attack (the attacker must control ALL meters in the support)."""
    sets = [set(map(int, s)) for s in stealth_costs(model)]
    remaining = list(range(len(sets)))
    chosen = []
    while remaining:
        counts = {}
        for b in remaining:
            for i in sets[b]:
                counts[i] = counts.get(i, 0) + 1
        best = max(counts, key=lambda i: (counts[i], -i))
        chosen.append((best, sorted(b for b in remaining if best in sets[b])))
        remaining = [b for b in remaining if best not in sets[b]]
    return [(int(i), model.names[i], [f"B{b + 1}" for b in covered]) for i, covered in chosen]
