"""GridSentinel AI - Bring-your-own-grid interface (NEW file; nothing existing is changed).
Run:  py -3.12 -m streamlit run gridsentinel_byog_app.py
Pick a grid (built-in or your own MATPOWER .m), build the Trust Gate, load a CSV of meter readings, get a decision per snapshot.
Simulation-validated research prototype."""
import os, tempfile, warnings
import numpy as np
import pandas as pd
import streamlit as st
warnings.filterwarnings("ignore")
import gridsentinel_cli as gc
from gridsentinel_core import PipelineConfig, GateCalibration, build_calibration, run_pipeline, make_scenarios, apply_attack

st.set_page_config(page_title="GridSentinel AI - your grid", page_icon="⚡", layout="wide")
COL = {"PROCEED": "#1b8a3a", "CAUTION": "#c98a00", "VALIDATE": "#c0392b"}
LV = {"green": "PROCEED", "yellow": "CAUTION", "red": "VALIDATE"}
st.title("⚡ GridSentinel AI: bring your own grid")
st.caption("Give it a grid model and meter readings. It scores each meter, isolates suspicious ones, recovers the grid state and says whether to PROCEED, take CAUTION or VALIDATE, with a calibrated error bound. Validated in simulation only.")

with st.sidebar:
    st.header("1 · Grid")
    choice = st.selectbox("Grid model", ["case14", "case30", "case57", "case118", "Upload my own (MATPOWER .m)"])
    grid = choice
    if choice.startswith("Upload"):
        up = st.file_uploader("MATPOWER case file (.m)", type=["m"])
        if up is None:
            st.info("Upload a .m file to continue."); st.stop()
        path = os.path.join(tempfile.gettempdir(), "gs_" + up.name); open(path, "wb").write(up.getvalue()); grid = path
    st.header("2 · Trust Gate")
    tol = st.number_input("Tolerance (pu): error you can accept", 0.005, 0.1, 0.01, 0.005, format="%.3f")
    z_iso = st.number_input("Isolation threshold (z)", 3.5, 8.0, 4.5, 0.5)
    n = st.slider("Calibration scenarios (each split)", 40, 300, 200, 20, help="More is slower and tighter. 14 buses: seconds. 200 buses: tens of minutes.")

@st.cache_resource(show_spinner="Loading grid model...")
def get_model(g):
    return gc.load_model(g)

model = get_model(grid)
cfg = PipelineConfig(tol_pu=tol, z_iso=z_iso, z_zero=z_iso + 2.0)
st.sidebar.success(f"{model.nb} buses · {model.nl} branches · {model.m} meters per snapshot")
key = (grid, tol, z_iso, n)
if st.sidebar.button("Build the Trust Gate", type="primary"):
    bar = st.sidebar.progress(0.0, text="Building from the grid model (no real data needed)...")
    st.session_state["cal"] = (key, build_calibration(model, n, n, 7, cfg, progress=lambda i, t: bar.progress(min(i / t, 1.0))))
    bar.empty()
ok = "cal" in st.session_state and st.session_state["cal"][0] == key
st.sidebar.write("Gate: " + ("✅ ready" if ok else "⚠️ not built for these settings"))

st.header("3 · Meter readings")
src = st.radio("Readings", ["Example snapshots (simulated, with attacks)", "Upload my CSV"], horizontal=True)
cols_df = pd.DataFrame({"column": model.names, "kind": model.kinds})
if src.startswith("Upload"):
    f = st.file_uploader("CSV: one row per snapshot, one column per meter (V in pu, P in MW, Q in MVAr)", type=["csv"])
    df = pd.read_csv(f) if f else None
    rng = np.random.default_rng(5); modes = ["none", "none", "random_single", "multi_coordinated", "stealth_partial"]
    ex = pd.DataFrame([apply_attack(model, sc, m, rng, cfg)[0] for sc, m in zip(make_scenarios(model, 5, rng), modes)], columns=model.names)
    ex.insert(0, "snapshot_id", [f"example_{i}_{m}" for i, m in enumerate(modes)])
    st.download_button("Download a template CSV (exact column names)", ex.to_csv(index=False), "meter_template.csv")
else:
    rng = np.random.default_rng(5); modes = ["none", "none", "random_single", "multi_coordinated", "stealth_partial"]
    df = pd.DataFrame([apply_attack(model, sc, m, rng, cfg)[0] for sc, m in zip(make_scenarios(model, 5, rng), modes)], columns=model.names)
    df.insert(0, "snapshot_id", [f"example_{i}_{m}" for i, m in enumerate(modes)])
if df is not None:
    st.dataframe(df.iloc[:, :9], use_container_width=True, height=180); st.caption(f"{len(df)} snapshot(s), {df.shape[1]} columns")

st.header("4 · Decisions")
if df is None:
    st.info("Upload a CSV or use the example snapshots.")
elif not ok:
    st.warning("Build the Trust Gate first (left panel).")
else:
    missing = [c for c in model.names if c not in df.columns]
    if missing:
        st.error(f"{len(missing)} required columns are missing, for example {missing[:4]}. Download the template to see the exact names."); st.stop()
    cal = st.session_state["cal"][1]; rows, results = [], []
    for k, r in df.iterrows():
        z = r[model.names].to_numpy(float)
        if not np.isfinite(z).all():
            rows.append({"snapshot": r.get("snapshot_id", k), "decision": "VALIDATE", "error_bound_pu": None, "isolated": "missing / NaN readings"}); results.append(None); continue
        res = run_pipeline(model, z, cfg, cal); results.append(res)
        rows.append({"snapshot": r.get("snapshot_id", k), "decision": LV[res.level], "error_bound_pu": round(res.bound_pu, 4),
                     "p_within_tol_%": round(res.conf), "n_isolated": len(res.iso_idx), "isolated": "; ".join(res.iso_names[:6]) + (" ..." if len(res.iso_names) > 6 else "")})
    out = pd.DataFrame(rows)
    c = st.columns(3)
    for col, d in zip(c, ["PROCEED", "CAUTION", "VALIDATE"]):
        col.markdown(f"<div style='background:{COL[d]};color:white;border-radius:12px;padding:12px;text-align:center'><b style='font-size:26px'>{(out.decision == d).sum()}</b><br>{d}</div>", unsafe_allow_html=True)
    st.dataframe(out.style.map(lambda v: f"background-color:{COL.get(v, 'white')};color:white" if v in COL else "", subset=["decision"]), use_container_width=True)
    st.download_button("Download decisions (CSV)", out.to_csv(index=False), "decisions.csv")
    pick = st.selectbox("Look inside one snapshot", [str(x) for x in out.snapshot])
    i = [str(x) for x in out.snapshot].index(pick); res = results[i]
    if res is not None:
        st.subheader(f"{pick}: {LV[res.level]}")
        st.write(f"Calibrated error bound **{res.bound_pu:.4f} pu** · chance the error is within {tol} pu: **{res.conf:.0f}%** · isolated meters: **{len(res.iso_idx)}**")
        if res.reasons: st.write("Reasons: " + " | ".join(res.reasons))
        st.bar_chart(pd.DataFrame({"recovered voltage (pu)": res.rec_V}, index=[f"bus {b + 1}" for b in range(len(res.rec_V))]))
st.caption("Research prototype validated in simulation. A pilot on utility data is the next step.")
