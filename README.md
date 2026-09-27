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


  ____________________
  ## How to Run on Google Colab

Important run order (do not skip):

1. First run the **last cell** (tunnel / public link cell).
2. Then run the **first cell** (install dependencies).
3. After that, run **all cells again from top to bottom** in order.

Why this order?
- The last cell prepares the public link path.
- The first cell installs required libraries.
- Running all cells again ensures Streamlit starts cleanly and the public URL works.

### Cell order after setup
1. Install dependencies  
2. Create `gridsentinel_app.py`  
3. Start Streamlit on port 8501  
4. Open public tunnel link (Cloudflare)

Open the generated `https://....trycloudflare.com` link in a new browser tab.


## How to Run (Local)
```bash
pip install -r requirements.txt
streamlit run gridsentinel_app.py


