import subprocess, time, socket, re, os, urllib.request, stat
os.chdir("/content/gridsentinel") if os.path.exists("/content/gridsentinel") else None
subprocess.run("pkill -f streamlit; pkill -f cloudflared", shell=True)
log = open("streamlit.log", "w")
subprocess.Popen(["streamlit","run","gridsentinel_app.py","--server.port","8501","--server.headless","true",
                  "--server.enableCORS","false","--server.enableXsrfProtection","false"], stdout=log, stderr=log)
# wait until Streamlit really listens (this was the cause of "connection refused")
for _ in range(120):
    try:
        socket.create_connection(("127.0.0.1", 8501), timeout=1).close(); break
    except OSError: time.sleep(1)
else:
    print(open("streamlit.log").read()); raise SystemExit("Streamlit did not start - see log above")
if not os.path.exists("cloudflared"):
    urllib.request.urlretrieve("https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64", "cloudflared")
    os.chmod("cloudflared", 0o755)
tun = subprocess.Popen(["./cloudflared","tunnel","--url","http://127.0.0.1:8501","--no-autoupdate"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
t0 = time.time()
for line in tun.stdout:
    m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
    if m: print("OPEN THIS LINK:", m.group(0)); break
    if time.time()-t0 > 90: print("no URL yet; check connection"); break
