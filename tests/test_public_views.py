"""The view numbers the public sees (the Earn page, its leaderboard, the launch page) count only clips that can be
trusted: approved and paid clips in full, clips not reviewed yet unless one claims an outsized number. Admins see all."""
import os, sys, tempfile, time
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="ck-views-"), DATABASE_URL="", CLIPKONTRAST_PENDING_VIEW_CAP="300000")
sys.path.insert(0, ".")
from studio import auth, db, earn  # noqa: E402
db.init()
fails = []


def check(n, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


camp = earn.save_campaign({"title": "Test Launch", "platforms": ["youtube", "instagram"], "budget": 100000, "rate_per_1k": 30,
                           "status": "live"})
cid = camp["id"]
users = {}
for name in ("big", "honest", "approved"):
    u = auth._create(f"{name}@example.com", name.title(), auth.hash_password("Testpass123!"))
    users[name] = u[0].id        # (the new account, whether it was the first)
now = time.time()
rows = [("big", 25_000_000, "pending"), ("big", 80_000, "pending"),          # one claim far too big to show before review
        ("honest", 120_000, "pending"), ("honest", 40_000, "pending"),
        ("approved", 900_000, "approved"), ("approved", 5_000, "rejected")]
with db.engine.begin() as c:
    for i, (who, views, status) in enumerate(rows):
        c.execute(db.earn_submissions.insert().values(campaign_id=cid, user_id=users[who], platform="youtube", url=f"https://youtu.be/v{i}",
                                                      video_key=f"youtube:v{i}", submitted_at=now, views=views, status=status,
                                                      amount=27000 if status == "approved" else 0))

pub = earn.campaign(cid)
adm = earn.campaign(cid, admin=True)
check("the public count leaves out the unreviewed 2.5 Cr claim and the rejected clip", pub["views"], 80_000 + 160_000 + 900_000)
check("...the admin sees every view that wasn't rejected", adm["views"], 25_000_000 + 80_000 + 160_000 + 900_000)
check("...clip counts stay the same for both", (pub["clips"], adm["clips"]), (5, 5))
check("the Earn page's total views are the trusted ones", earn.overview()["views"], 1_140_000)
lb = earn.leaderboard()
check("the public leaderboard ranks by trusted views: the approved clipper first, the big claim last",
      [(r["name"][:2], r["views"]) for r in lb], [("ap", 900_000), ("ho", 160_000), ("bi", 80_000)])
check("...with what each has earned", [r["earned"] for r in lb], [27000.0, 0.0, 0.0])
with db.engine.begin() as c:
    u0 = auth._create("waiting@example.com", "Waiting", auth.hash_password("Testpass123!"))[0].id
    c.execute(db.earn_submissions.insert().values(campaign_id=cid, user_id=u0, platform="youtube", url="https://youtu.be/w", video_key="youtube:w",
                                                  submitted_at=now, views=9_000_000, status="pending"))
check("someone whose only clip waits for review isn't ranked with 0 views", len(earn.leaderboard()), 3)
check("the admin's leaderboard shows the claim as sent", earn.leaderboard(public=False)[0]["views"], 25_080_000)
with db.engine.begin() as c:
    c.execute(db.earn_submissions.update().where(db.earn_submissions.c.views == 25_000_000).values(status="approved", amount=2000))
check("once an admin approves the big clip, the public total counts it too", earn.campaign(cid)["views"], 25_000_000 + 80_000 + 160_000 + 900_000)
before = earn.overview()["views"]
earn.save_campaign({"title": "Diwali Cup", "platforms": ["youtube"], "budget": 200000, "rate_per_1k": 20, "status": "ended",
                    "results": {"views": 4500000, "clips": 500, "clippers": 230}})
check("a finished campaign adds the results it was reported with", earn.overview()["views"], before + 4_500_000)
page = open("web/launch.html", encoding="utf-8").read()
check("the launch page says 'Clippers behind ... views' only with a counted number (hidden until then)",
      ('id="proof" hidden' in page, "s.views >= 100000" in page), (True, True))
print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
