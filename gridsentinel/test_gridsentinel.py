"""Run: python -m pytest -q test_gridsentinel.py   (or: python test_gridsentinel.py)"""
import ast, inspect
import numpy as np
import gridsentinel_core as g

M = g.GridModel()
CFG = g.PipelineConfig()


def _sc(seed=1):
    rng = np.random.default_rng(seed)
    return rng, g.make_scenarios(M, 1, rng)[0]


def test_jacobian_matches_finite_differences():
    x = M.x_base.copy()
    J = M.jac(x)
    rng = np.random.default_rng(0)
    for j in rng.choice(len(x), 6, replace=False):
        e = np.zeros(len(x)); e[j] = 1e-6
        fd = (M.h(x + e) - M.h(x - e)) / 2e-6
        assert np.allclose(J[:, j], fd, atol=1e-4, rtol=1e-4)


def test_clean_recovery_is_accurate():
    rng, sc = _sc(2)
    res = g.run_pipeline(M, sc.z_clean, CFG)
    assert res.converged and g.true_error(M, sc.x_true, res.rec_V) < 0.01


def test_big_attack_isolated_and_recovered():
    rng, sc = _sc(3)
    z, info = g.apply_attack(M, sc, "random_single", rng, CFG)
    res = g.run_pipeline(M, z, CFG)
    assert set(info.idx) <= set(res.iso_idx)
    assert g.true_error(M, sc.x_true, res.rec_V) < 0.01   # back to the noise floor after isolation


def test_full_stealth_leaves_chi_square_unchanged():
    rng, sc = _sc(4)
    z, _ = g.apply_attack(M, sc, "stealth_full", rng, CFG, bus=8)
    a = M.wls(sc.z_clean, M.avail); b = M.wls(z, M.avail)
    ra = np.sum(((sc.z_clean - M.h(a.x)) / M.sigma)[M.avail] ** 2)
    rb = np.sum(((z - M.h(b.x)) / M.sigma)[M.avail] ** 2)
    assert abs(ra - rb) / ra < 1e-3


def test_live_path_never_touches_truth():
    src = inspect.getsource(g.run_pipeline)
    tree = ast.parse(src)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not (names & {"x_true", "z_clean", "true_error", "Scenario", "apply_attack", "AttackInfo"})
    assert list(inspect.signature(g.run_pipeline).parameters)[:2] == ["model", "z"]


def test_seed_reproducibility():
    a = g.run_gridsentinel(seed=5, attack_mode="multi_coordinated", model=M, calibration=_cal())
    b = g.run_gridsentinel(seed=5, attack_mode="multi_coordinated", model=M, calibration=_cal())
    assert a["true_error"] == b["true_error"] and a["isolated"] == b["isolated"]


_CAL = None
def _cal():
    global _CAL
    if _CAL is None:
        _CAL = g.build_calibration(M, 120, 120, seed=3)
    return _CAL


def test_gate_bound_is_finite_and_ordered():
    r = g.run_gridsentinel(seed=6, attack_mode="none", model=M, calibration=_cal())
    assert r["bound_pu"] > 0 and 0 <= r["conf"] <= 100
    assert r["level"] in ("green", "yellow", "red")


def test_conformal_coverage_sanity():
    rng = np.random.default_rng(11)
    cases = []
    for sc in g.make_scenarios(M, 120, rng):
        z, _ = g.apply_attack(M, sc, str(rng.choice(list(g.IN_MODEL_MIX))), rng, CFG)
        res = g.run_pipeline(M, z, CFG)
        cases.append((res.fvec, g.true_error(M, sc.x_true, res.rec_V)))
    cov = np.mean([e <= _cal().bound(f) for f, e in cases])
    assert cov > 0.75   # small calibration set -> loose check; batch_eval reports the real figure


def test_calibration_json_roundtrip():
    c = _cal(); c2 = g.GateCalibration.from_json(c.to_json())
    f = np.zeros(len(g.FEATURE_NAMES))
    assert abs(c.predict_log(f) - c2.predict_log(f)) < 1e-9


if __name__ == "__main__":
    import pytest, sys
    sys.exit(pytest.main(["-q", __file__]))
