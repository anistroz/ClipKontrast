"""Earn details that are easy to break: handles with dots, and what a campaign's state says."""
import os, sys, tempfile, time
from types import SimpleNamespace as NS
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="ck-states-"), DATABASE_URL="")
sys.path.insert(0, ".")
from studio import earn
fails = []


def check(n, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


for typed, platform, want in [("rahul.clips", "instagram", "@rahul.clips"), ("@Rahul.Clips", "instagram", "@rahul.clips"),
                              ("https://www.instagram.com/rahul.clips/", "instagram", "@rahul.clips"), ("instagram.com/rahul.clips", "instagram", "@rahul.clips"),
                              ("youtube.com/@MizoLive", "youtube", "@mizolive"), ("x.com/rahul_x", "x", "@rahul_x"), ("rahul.tt", "tiktok", "@rahul.tt")]:
    check(f"the handle {typed!r} is read as {want}", earn._clean_handle(typed, platform), want)

now = time.time()
row = lambda **k: NS(**{"status": "live", "budget": 1000.0, "starts_at": None, "ends_at": None, **k})
check("live, started, money left: open", earn._state(row(), 0), "open")
check("live but starting later: starts", earn._state(row(starts_at=now + 3600), 0), "starts")
check("...and it isn't open", earn._is_open(row(starts_at=now + 3600), 0), False)
check("live with the budget used: full", earn._state(row(), 1000), "full")
check("live past its end date: ended", earn._state(row(ends_at=now - 60), 0), "ended")
check("announced: soon", earn._state(row(status="soon"), 0), "soon")
check("...and nobody can join it", earn._is_open(row(status="soon"), 0), False)
check("coming soon is a status the admin can pick", "soon" in earn.STATUSES, True)
print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
