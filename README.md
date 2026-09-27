# 🛡️ GridSentinel AI

**Trust-Aware Decision Layer for Resilient Smart Grid Operation**

GridSentinel AI detects False Data Injection Attacks (FDIA) on smart-grid sensor measurements, computes trust scores **without using true clean values**, isolates compromised sensors, reconstructs the state, and issues an operational decision.

## Problem
Smart grids rely on sensor data for state estimation and control.  
False Data Injection Attacks can corrupt measurements and mislead operators.  
Most detectors stop at “attack detected”. Operators still need a safe next action.

## Solution
1. Simulate IEEE-14 bus system  
2. Inject a random FDIA on one sensor  
3. Compute robust trust scores (median/MAD) — no oracle true values  
4. Isolate low-trust sensors  
5. Reconstruct measurements from trusted sensors  
6. Re-run Weighted Least Squares state estimation  
7. Output Decision Confidence + operational recommendation

## Key Features
- Random attack location and magnitude every run  
- Trust computed without ground-truth clean values  
- Focused isolation (clear primary outlier)  
- State recovery + operational decision  
- Live interactive demo (Streamlit)

## Tech Stack
- Python
- pandapower (IEEE-14 + WLS state estimation)
- NumPy / Pandas
- Streamlit

## How to Run (Local)
```bash
pip install -r requirements.txt
streamlit run gridsentinel_app.py
