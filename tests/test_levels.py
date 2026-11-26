"""Levels, premium campaigns, badges and the weekly leaderboard of Earn: who may clip a premium campaign, what each
level is paid, how a level goes up by itself, the views that aren't paid, and what the leaderboard shows.

Runs against the code directly, with its own empty data folder."""
import os, sys, tempfile, time
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="ck-levels-"), DATABASE_URL="", CLIPKONTRAST_ELITE_SLOTS="2")
sys.path.insert(0, ".")
from studio import auth, db, earn, levels  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


def refused(n, fn, err=(earn.EarnError, levels.LevelError), has=""):
    try:
        fn()
        check(n, "accepted", "refused")
    except err as e:
        check(n, (not has) or has in str(e))


def user(name):
    return auth._create(f"{name}@example.com", name.title(), auth.hash_password("Testpass123!"))[0].id


def profile(uid, yt):
    earn.save_profile(uid, {"display_name": "", "whatsapp": "+919876543210", "upi": "clipper@okaxis", "youtube": yt})


A, B, C, D = user("asha"), user("bilal"), user("chirag"), user("dev")
for u, h in ((A, "@asha"), (B, "@bilal"), (C, "@chirag"), (D, "@dev")):
    profile(u, h)

# ---- a premium campaign
refused("level rates must be three numbers, each at least the one before", lambda: earn.save_campaign(
    {"title": "Bad rates", "platforms": ["youtube"], "budget": 70000, "premium": True, "tier_rates": "100,75,50"}), has="Silver, Gold, Elite")
camp = earn.save_campaign({"title": "Premium edits", "platforms": ["youtube"], "budget": 70000, "premium": True, "tier_rates": "50,75,100",
                           "free_views": 2000, "max_per_clip": 5000, "status": "live", "hold_days": 0})
cid = camp["id"]
check("a premium campaign says so, with each level's rate", (camp["premium"], camp["tier_rates"]), (True, {"silver": 50.0, "gold": 75.0, "elite": 100.0}))
check("...and is shown as paying up to the Elite rate", camp["rate_per_1k"], 100.0)
check("everyone starts as a Starter", levels.info(A)["level"], "starter")
check("...whose next step is to apply", levels.info(A)["next"]["level"], "silver")
refused("a Starter can't join a premium campaign", lambda: earn.join(A, cid), has="approved clippers")
refused("...or send a clip to it", lambda: earn.submit(A, cid, "https://youtube.com/shorts/aaaaaaaaaaa"), has="approved clippers")

# ---- applying, and the answer
refused("an application needs a real page link", lambda: levels.apply(A, {"page_url": "hello", "recording_url": "https://drive.google.com/x", "sample_url": "https://youtu.be/x"}))
refused("...on Instagram, YouTube, X or TikTok", lambda: levels.apply(A, {"page_url": "https://example.com/me", "recording_url": "https://drive.google.com/x", "sample_url": "https://youtu.be/x"}),
        has="Instagram")
got = levels.apply(A, {"page_url": "youtube.com/@asha", "recording_url": "https://drive.google.com/file/d/rec", "sample_url": "https://youtu.be/best",
                       "niche": "gaming", "followers": "12,000", "avg_views": 18000, "note": "<b>hi</b>"})
check("an application is waiting for review, its link made https", (got["application"]["status"], got["application"]["page_url"]), ("pending", "https://youtube.com/@asha"))
check("...with no HTML kept in the note", got["application"]["note"], "bhi/b")
apps = levels.applications("pending")
check("the admin sees it, with what was claimed", (len(apps["items"]), apps["items"][0]["followers"], apps["items"][0]["avg_views"]), (1, 12000, 18000))
levels.apply(B, {"page_url": "https://instagram.com/bilal", "recording_url": "https://drive.google.com/r2", "sample_url": "https://instagram.com/reel/x"})
levels.decide(B, "reject", note="Your page gets too few views yet.")
check("a rejected clipper hears why", levels.info(B)["application"]["review_note"], "Your page gets too few views yet.")
refused("...and can apply again only after a week", lambda: levels.apply(B, {"page_url": "https://instagram.com/bilal", "recording_url": "https://drive.google.com/r2",
                                                                          "sample_url": "https://instagram.com/reel/x"}), has="apply again from")
levels.decide(A, "approve", "silver")
check("approved as Silver", (levels.info(A)["level"], levels.info(A)["rate"]), ("silver", 50.0))
check("...a Silver's next level is Gold, with how far there is to go", (levels.info(A)["next"]["level"], levels.info(A)["next"]["steps"][0]["have"]), ("gold", 0))
refused("approving twice is refused", lambda: levels.apply(A, {"page_url": "https://youtube.com/@asha", "recording_url": "https://drive.google.com/x", "sample_url": "https://youtu.be/x"}),
        has="already approved")
check("an approved clipper can join", earn.join(A, cid)["member"], True)

# ---- what a clip earns: the level's rate, after the views that aren't paid, up to the cap
now = time.time()
def clip(uid, views, key, status="pending", at=None):
    with db.engine.begin() as c:
        return c.execute(db.earn_submissions.insert().values(campaign_id=cid, user_id=uid, platform="youtube", url=f"https://youtu.be/{key}",
                                                             video_key=f"youtube:{key}", submitted_at=at or now, views=views, status=status,
                                                             reviewed_at=(at or now) if status != "pending" else None)).inserted_primary_key[0]
s1 = clip(A, 52_000, "a1")
check("a Silver's clip: (52,000 - 2,000 views not paid) at ₹50", earn.submission(s1)["estimate"], 2500.0)
earn.decide(s1, "approve")
check("...approved for exactly that", earn.submission(s1)["amount"], 2500.0)
s2 = clip(A, 1_500, "a2")
check("a clip under the views that aren't paid earns nothing (no reason to buy views up to a line)", earn.submission(s2)["estimate"], 0.0)
s3 = clip(A, 400_000, "a3")
check("a big clip stops at the most per clip", earn.submission(s3)["estimate"], 5000.0)

# ---- going up a level by itself
earn.decide(clip(A, 60_000, "a4"), "approve")
check("2 clips past 50K this month: still Silver", levels.info(A)["level"], "silver")
check("...the progress says 2 of 3", levels.info(A)["next"]["steps"][0]["have"], 2)
earn.decide(clip(A, 75_000, "a5"), "approve")
check("the 3rd clip past 50K this month makes them Gold", levels.info(A)["level"], "gold")
check("...and Gold is paid ₹75", earn.submission(clip(A, 12_000, "a6"))["estimate"], 750.0)
check("old clips don't count for Gold: last month's don't", levels._earned_level([(90_000, levels.month_start() - 86400)] * 3), "silver")
earn.decide(clip(A, 600_000, "a7"), "approve")
check("a clip past 5 lakh makes them Elite", levels.info(A)["level"], "elite")
check("...with the Elite badge, and the 5 lakh one", {b["key"] for b in levels.info(A)["badges"] if b["earned"]} >= {"elite", "lakh5", "viral", "first_clip", "approved"})
check("...not the 1M one yet", [b["earned"] for b in levels.info(A)["badges"] if b["key"] == "million"], [False])

# ---- Elite places run out
for u, h in ((C, "c"), (D, "d")):
    levels.apply(u, {"page_url": f"https://youtube.com/@{h}", "recording_url": "https://drive.google.com/r", "sample_url": "https://youtu.be/s"})
    levels.decide(u, "approve", "silver")
levels.decide(C, "level", "elite")          # the team can set a level by hand
check("the team can move a clipper to a level", levels.info(C)["level"], "elite")
earn.decide(clip(D, 700_000, "d1"), "approve")
check("with every Elite place taken (2 here), a clip past 5 lakh makes Gold, not Elite", levels.info(D)["level"], "gold")
levels.decide(C, "level", "gold", note="Botted views on two clips.")
check("...and the team can move someone down", levels.info(C)["level"], "gold")

# ---- the weekly leaderboard
board = levels.weekly_board()
check("this week's board ranks by checked views (approved clips only)", [r["name"][:2].lower() for r in board["rows"]], ["as", "de"])
check("...with each one's level and badges", (board["rows"][0]["level"], "💎" in board["rows"][0]["badges"]), ("elite", True))
check("...and a pending clip doesn't count", all(r["views"] < 1_400_000 for r in board["rows"]))
clip(B, 900_000, "b_old", status="approved", at=levels.week_start() - 3 * 86400)
check("last week's clips aren't on this week's board", "bi" not in [r["name"][:2].lower() for r in levels.weekly_board()["rows"]])
levels._TOP10["at"] = 0
check("being in a finished week's top 10 earns the Top 10 badge", [b["earned"] for b in levels.info(B)["badges"] if b["key"] == "top10"], [True])
check("a normal campaign is unchanged: one rate for everyone", earn.save_campaign({"title": "Normal", "platforms": ["youtube"], "budget": 1000, "rate_per_1k": 30})["premium"], False)
print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
