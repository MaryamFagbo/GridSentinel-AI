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