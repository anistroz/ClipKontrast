"""Premium campaigns and levels in a real browser, on a throwaway website: a clipper sees the premium campaign, applies,
the admin approves them as Silver, and the clipper's level, badges and next level show; then they join.
Usage: test_levels_ui.py <project root>"""
import os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
import httpx
ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
PORT = 8814
SITE = f"http://127.0.0.1:{PORT}"
data = tempfile.mkdtemp(prefix="ck-levels-ui-")
common = {"DATABASE_URL": "", "CLIPKONTRAST_FETCH_MODEL": "0", "CLIPKONTRAST_UPDATE_CHECK": "0", "CLIPKONTRAST_AUTO_RELOAD": "0",
          "CLIPKONTRAST_WHISPER": "0", "CLIPKONTRAST_DATA": data, "CLIPKONTRAST_ACCOUNTS": "1"}
seed = ("import sys; sys.path.insert(0, '.')\n"
        "from studio import db, earn\n"
        "db.init()\n"
        "earn.save_campaign({'title': 'Premium edits', 'creator_name': 'ClipKontrast', 'platforms': ['youtube', 'instagram'], 'budget': 70000,"
        " 'premium': True, 'tier_rates': '50,75,100', 'free_views': 2000, 'max_per_clip': 5000, 'status': 'live', 'tagline': 'For editors who make clips go viral.'})\n"
        "earn.save_campaign({'title': 'GTA 6 Launch', 'creator_name': 'Mizo Plays', 'platforms': ['youtube'], 'budget': 50000, 'rate_per_1k': 30, 'status': 'live'})\n")
subprocess.run([sys.executable, "-c", seed], cwd=ROOT, check=True, env={**os.environ, **common})
srv = subprocess.Popen([sys.executable, "-m", "studio.server"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={
    **os.environ, **common, "CLIPKONTRAST_PORT": str(PORT), "CLIPKONTRAST_PUBLIC_URL": SITE, "CLIPKONTRAST_EARN_ONLY": "1",
    "CLIPKONTRAST_VERIFY_EMAIL": "0", "CLIPKONTRAST_EARN_URL": SITE})
code = 1
try:
    for _ in range(60):
        try:
            urllib.request.urlopen(SITE + "/healthz", timeout=2); break
        except Exception:
            time.sleep(1)
    def account(email, admin=False):
        cl = httpx.Client(base_url=SITE, timeout=30, headers={"Origin": SITE})
        cl.post("/api/auth/signup", json={"email": email, "password": "test-pass-123"})
        if admin:
            subprocess.run([sys.executable, "-m", "studio.admin", "grant", email], cwd=ROOT, capture_output=True, env={**os.environ, **common})
        return cl
    clipper, boss = account("asha@example.com"), account("boss@example.com", admin=True)
    clipper.put("/api/earn/profile", json={"display_name": "Asha", "whatsapp": "+919876543210", "upi": "asha@okaxis", "youtube": "@asha"})
    ck, bk = next(iter(clipper.cookies.jar)), next(iter(boss.cookies.jar))
    shots = os.environ.get("CK_SHOTS") or tempfile.mkdtemp(prefix="ck-levels-shots-")
    r = subprocess.run(["node", "tests/levels_ui.cjs", SITE, shots, ck.name, ck.value, bk.value], cwd=ROOT, timeout=300)
    print(f"  screenshots: {shots}")
    code = r.returncode
finally:
    srv.terminate()
    try:
        srv.wait(10)
    except subprocess.TimeoutExpired:
        srv.kill()
sys.exit(code)
