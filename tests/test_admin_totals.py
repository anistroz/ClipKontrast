"""The admin overview's headline numbers are counted over every account, not just the newest 2,000 the list shows:
with more, it said "2,000 signed up this week" and "0 admins" (the admin's own account being older)."""
import os, sys, tempfile, time, uuid
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-admintot-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="1",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0", CLIPKONTRAST_VERIFY_EMAIL="1")
sys.path.insert(0, ".")
from studio import admin, config, db  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


now = time.time()
boss = "u_" + uuid.uuid4().hex[:12]
rows = [dict(id=boss, email="boss@example.com", name="Boss", is_admin=True, created_at=now - 60 * 86400, last_seen=now - 3600)]
for i in range(2100):                                   # 2,100 newer accounts: 2,000 this week, 100 a fortnight ago
    rows.append(dict(id=f"u_{i:06d}", email=f"c{i}@example.com", name="", is_admin=False,
                     created_at=now - (i * 200 if i < 2000 else 15 * 86400), last_seen=(now - 100) if i % 2 else None))
with db.engine.begin() as c:
    c.execute(db.users.insert(), rows)
    c.execute(db.email_ok.insert(), [{"user_id": f"u_{i:06d}", "verified_at": now} for i in range(0, 2100, 3)])
    c.execute(db.admin_log.insert().values(t=now, admin_id=boss, action="disable", target_id="u_000001", detail=""))
t = admin.overview()["totals"]
check("all accounts counted", t["users"], 2101)
check("signed up in the last 7 days: all of them, not the 2,000 the list holds", t["signups_7d"], 2000)
check("signed up in the last 30 days", t["signups_30d"], 2100)
check("the admin is counted, though older than the newest 2,000", t["admins"], 1)
check("active in the last 7 days: everyone who was", t["active_7d"], 1051)
check("confirmed their email", t["verified"], 700)
log = admin.overview()["log"]
check("the activity log names the admin, though their account is old", log[0]["admin"], "boss@example.com")
print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
