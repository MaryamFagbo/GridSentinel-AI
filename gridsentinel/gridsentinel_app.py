"""GridSentinel AI - Streamlit demo.  Run:  streamlit run gridsentinel_app.py"""
import os
import numpy as np
import pandas as pd
import streamlit as st

from gridsentinel_core import (GridModel, PipelineConfig, GateCalibration, make_scenarios, apply_attack,
                               run_pipeline, recovery_table, consequence_view, hardening_plan,
                               get_default_calibration, true_error, K_MAX)

st.set_page_config(page_title="GridSentinel AI", page_icon="⚡", layout="wide")
CAL_PATH = os.environ.get("GS_CAL", "gate_calibration.json")


@st.cache_resource(show_spinner="Loading grid model and calibrated gate (first run builds it, ~1 min)...")
def load():
    model, cfg = GridModel(), PipelineConfig()
    return model, cfg, get_default_calibration(model, path=CAL_PATH, cfg=cfg)


model, cfg, cal = load()
COLORS = {"green": "#1b8a3a", "yellow": "#c98a00", "red": "#c0392b", "grey": "#666"}

st.title("⚡ GridSentinel AI")
st.caption("Self-protecting state estimation for smart grids: detect, isolate, recover - and say when NOT to trust the result. "
           "IEEE 14-bus simulation, 122 AC measurements.")

with st.sidebar:
    st.header("Operator panel")
    seed = st.number_input("Seed", min_value=0, max_value=10**9, value=42, step=1)
    fixed = st.checkbox("Fixed seed", value=True, help="Unchecked = a new random scenario on every run")
    scenario = st.selectbox("Scenario", ["none", "random single", "multi", "stealth (partial)",
                                         "adaptive attacker", "custom voltage injection", "custom stealth"])
    bus = size = None
    if scenario.startswith("custom"):
        bus = st.number_input("Target bus", 1, model.nb, 9) - 1
        size = st.number_input("Size (pu)", -0.2, 0.2, 0.08, 0.01)
    run = st.button("Run scenario", type="primary")

MODE = {"none": "none", "random single": "random_single", "multi": "multi_coordinated",
        "stealth (partial)": "stealth_partial", "adaptive attacker": "adaptive",
        "custom voltage injection": "custom_voltage", "custom stealth": "custom_stealth"}[scenario]

if "case" not in st.session_state or run:
    s = int(seed) if fixed else int(np.random.default_rng().integers(10**9))
    rng = np.random.default_rng(s)
    sc = make_scenarios(model, 1, rng)[0]
    z, info = apply_attack(model, sc, MODE, rng, cfg, bus=bus, size=size)
    res = run_pipeline(model, z, cfg, cal)          # LIVE path: z only
    st.session_state.case = dict(seed=s, mode=MODE, sc=sc, z=z, info=info, res=res)
c = st.session_state.case
res, sc, z, info = c["res"], c["sc"], c["z"], c["info"]

# --- Attack status (separate from the Trust Gate) -------------------------------------------
from scipy.stats import chi2 as _chi2
from gridsentinel_core import FEATURE_NAMES
_dof = int(model.avail.sum() - len(model.flat_start()))
_j_raw = 10 ** res.features["log_J_raw"] if "log_J_raw" in res.features else 10 ** res.fvec[FEATURE_NAMES.index("log_J_raw")]
_j_thr = _chi2.ppf(0.99, _dof) / _dof
if len(res.iso_idx) or res.blocked:
    st_txt, st_col = f"ATTACK / BAD DATA DETECTED - {len(res.iso_idx)} meter(s) isolated", "#c0392b"
elif not res.converged or _j_raw > _j_thr:
    st_txt, st_col = "SUSPICIOUS DATA - measurements disagree, no single meter to blame", "#c98a00"
else:
    st_txt, st_col = "NO ATTACK INDICATORS - all measurements are consistent", "#1b8a3a"
st.markdown(f"<div style='background:{st_col};color:white;padding:10px 18px;border-radius:10px;font-size:1.15rem;margin-bottom:8px'>"
            f"<b>Attack status:</b> {st_txt}</div>", unsafe_allow_html=True)

col = COLORS[res.level]
st.markdown(f"<div style='background:{col};color:white;padding:14px 18px;border-radius:10px;font-size:1.3rem'>"
            f"<b>{res.label}</b> &nbsp;|&nbsp; P(error ≤ {cfg.tol_pu} pu) = {res.conf:.0f}% &nbsp;|&nbsp; "
            f"calibrated error bound = {res.bound_pu:.4f} pu</div>", unsafe_allow_html=True)
if st_col == "#1b8a3a" and res.level != "green":
    st.info("Why not PROCEED? No alarm was raised, but a perfectly stealthy attack would look exactly like this. "
            "The Trust Gate only says PROCEED when it can bound the error from calibrated evidence - that is the point: "
            "it refuses to be overconfident.")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Estimator converged", "yes" if res.converged else "NO")
m2.metric("Meters isolated", len(res.iso_idx))
m3.metric("Residual (chi²/dof, log10)", f"{res.features['log_J']:.2f}")
m4.metric("Runtime", f"{res.ms:.0f} ms")
st.caption(f"Scenario: {c['mode']} | seed {c['seed']}  (the operator view above uses measurements only)")

t1, t2, t3, t4 = st.tabs(["Sensor trust", "Recovery Accuracy Evaluation", "Consequence", "Hardening"])

with t1:
    st.subheader("Trust per sensor station (S01-S14)")
    tb = pd.DataFrame({"Sensor": [f"S{b + 1:02d}" for b in range(model.nb)],
                       "Bus": [f"B{b + 1}" for b in range(model.nb)],
                       "Trust %": np.round(res.bus_trust, 0)})
    tb["Status"] = np.where(tb["Trust %"] >= 75, "trusted", np.where(tb["Trust %"] >= 40, "suspect", "isolated"))
    st.dataframe(tb, hide_index=True, use_container_width=True)
    if len(res.iso_idx):
        st.write("Isolated measurements:", ", ".join(res.iso_names))
    with st.expander("Measurement-level detail"):
        d = pd.DataFrame({"Measurement": res.names, "Trust %": np.round(res.trust, 0), "z-score": np.round(res.z_score, 2),
                          "Isolated": res.iso})
        st.dataframe(d.sort_values("Trust %").head(40), hide_index=True, use_container_width=True)

with t2:
    st.subheader("Recovery Accuracy Evaluation")
    st.warning("EVALUATION ONLY. The true voltage is stored only to score the result. "
               "It is never used by the system in any live decision.")
    rows, summ = recovery_table(model, res, z, sc.x_true, info, cfg)
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, use_container_width=True)
    a, b, cc = st.columns(3)
    a.metric("Max reconstruction error", f"{summ['max_error']:.4f} pu", f"naive {summ['naive_max_error']:.4f}", delta_color="off")
    b.metric("Mean reconstruction error", f"{summ['mean_error']:.4f} pu")
    cc.metric("Improvement vs naive", f"{summ['naive_max_error'] / max(summ['max_error'], 1e-9):.1f}x")
    (st.success if summ["max_error"] <= cfg.tol_pu else st.info if summ["max_error"] <= 3 * cfg.tol_pu else st.error)(summ["note"])
    st.line_chart(df.set_index("Bus")[["True voltage (pu)", "Attacked reading (pu)", "Reconstructed (pu)"]])

with t3:
    cv = consequence_view(model, res, sc.x_true, cfg)
    st.subheader("What the operator would conclude (voltage limits 0.95-1.05 pu)")
    st.table(pd.DataFrame({"State": ["True grid", "Naive estimator", "GridSentinel recovered"],
                           "Buses outside limits": [cv["true"], cv["naive"], cv["recovered"]],
                           "Wrong action?": ["-", "YES" if cv["naive_wrong_action"] else "no",
                                             "YES" if cv["recovered_wrong_action"] else "no"]}))

with t4:
    st.subheader("Hardening ranking")
    st.write(f"Attacker budget modelled: up to {K_MAX} compromised meters. Protecting these meters makes every single-bus "
             "stealth attack require control of a protected meter:")
    st.dataframe(pd.DataFrame([{"Meter to protect": n, "Covers buses": ", ".join(cv_)} for _, n, cv_ in hardening_plan(model)]),
                 hide_index=True, use_container_width=True)
    st.caption("Limits: perfect stealth beyond the budget cannot be detected by any estimator-side method.")
