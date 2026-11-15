# GridSentinel AI - bring-your-own-grid tool (MVP)

Needs: Python 3.12, `pip install -r requirements.txt matpowercaseframes`. Put all files in one folder.

1. `py -3.12 gridsentinel_cli.py template --grid case14 --out meas_template.csv`  -> exact meter columns + 5 example snapshots
2. `py -3.12 gridsentinel_cli.py calibrate --grid case14 --cal cal_case14.json --n 200`  -> builds the Trust Gate from the grid MODEL (offline)
3. `py -3.12 gridsentinel_cli.py run --grid case14 --meas meas_template.csv --cal cal_case14.json --out decisions.csv`

Your own grid: `--grid your_grid.m` (MATPOWER case file). Your own readings: a CSV, one row per snapshot, one column per meter named as in the template (V in pu, P in MW, Q in MVAr, injection positive = generation).
Output per snapshot: PROCEED / CAUTION / VALIDATE, calibrated error bound (pu), isolated meters, min/max recovered voltage.

Assumptions: static AC snapshot; the grid model matches the real grid; meter noise sd 0.004 pu and 1 MW/MVAr (change with --sigma_v / --sigma_pq at calibrate time); the gate is calibrated on SYNTHETIC attacks from the model.
Status: simulation-validated research prototype. Not tested on real utility data. Calibration time grows with grid size (14 buses: under a minute; 200 buses: tens of minutes).
