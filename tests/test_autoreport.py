"""Problems reporting themselves (studio/autoreport.py): off until the person turns it on, then the same report as
"Report a problem", at most a few a day, each problem once, never with the computer's user name in it."""
import os, sys, tempfile, time
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-autorep-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0")
sys.path.insert(0, ".")
from studio import accounts, autoreport, config, ctx, db  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


uid = "u_local"
sent = []
def send(form):
    sent.append(form)
def wait():
    time.sleep(0.4)

with ctx.as_user(uid):
    check("off by default", accounts.settings()["auto_reports"], False)
check("...so a failure sends nothing", autoreport.report(uid, "a clip failed", "Render failed: boom", "render.py:1", send=send), False)
with ctx.as_user(uid):
    accounts.save_settings({"auto_reports": True})
check("turned on in Settings", autoreport.enabled(uid), True)
home = str(Path.home())
check("a failure is reported, in the background", autoreport.report(uid, "a clip failed", f"Render failed in {home}/videos/x.mp4", "render.py:880 _render_in", send=send), True)
wait()
f = sent[-1] if sent else {}
check("...as the app's own report: what failed, where, and the technical details", f.get("source") == "app" and "Automatic report: a clip failed" in f.get("message", "")
      and "render.py:880" in f.get("context", "") and bool(f.get("app")))
check("...without the computer's user name in its details or its message", (home not in f.get("diag", "") and home not in f.get("message", "")) or len(home) <= 3)
check("the same problem isn't sent twice in a day", autoreport.report(uid, "a clip failed", f"Render failed in {home}/videos/x.mp4", "render.py:880 _render_in", send=send), False)
for i in range(10):
    autoreport.report(uid, "a video failed", f"Different problem {i}", "jobs.py:1", send=send)
wait()
check(f"at most {autoreport.MAX_A_DAY} a day", len(sent), autoreport.MAX_A_DAY)
config.ACCOUNTS = True
check("a website's shared server never sends any", autoreport.enabled(uid), False)
config.ACCOUNTS = False
print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
