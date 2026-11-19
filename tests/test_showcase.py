"""Ended campaigns as a showcase (their numbers, never who clipped what), and the order the admin drags campaigns into.

Runs against the code directly, with its own empty data folder."""
import os, sys, tempfile, time
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="ck-show-"), DATABASE_URL="")
sys.path.insert(0, ".")
from studio import db, earn
db.init()
fails = []


def check(n, got, want=True):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


live = earn.save_campaign({"title": "Mizo stream clips", "status": "live", "rate_per_1k": 30, "budget": 110000, "platforms": ["youtube"],
                           "sources": "Day 1 | https://youtube.com/live/a\nDay 2 | https://youtube.com/live/b"})
soon = earn.save_campaign({"title": "Next big creator", "status": "soon", "platforms": ["youtube"]})
done = earn.save_campaign({"title": "eFootball Diwali", "creator_name": "Jonathan & Shreeman", "status": "ended", "rate_per_1k": 20,
                           "budget": 150000, "platforms": ["youtube", "instagram", "x"], "sources": "https://youtube.com/@secret",
                           "results": {"views": "8981011", "clips": "669", "clippers": "210", "top_views": "2536248", "tiktok": "",
                                       "platforms": {"instagram": "7144717", "youtube": "610118", "x": "1226176", "tiktok": ""}}})
check("a new campaign goes on top", [c["title"] for c in earn.campaigns()][0], "eFootball Diwali")

# ---- the showcase
pub = earn.campaign(done["slug"])
check("an ended campaign is shown as ended", pub["state"], "ended")
check("its showcase has the report's numbers", {k: pub["showcase"][k] for k in ("views", "clips", "clippers", "budget", "top_views")},
      {"views": 8981011, "clips": 669, "clippers": 210, "budget": 150000.0, "top_views": 2536248})
check("its views are split by platform", pub["showcase"]["platforms"], {"instagram": 7144717, "youtube": 610118, "x": 1226176})
check("what the budget bought, per 1,000 views", pub["showcase"]["per_1k"], 16.7)
check("visitors never see who clipped it", pub["leaderboard"], [])
check("nor the streams that were clipped", "sources" in pub, False)
check("the admin still sees everything", ("sources" in earn.campaign(done["id"], admin=True), earn.campaign(done["id"], admin=True)["results"]["views"]),
      (True, 8981011))
check("a live campaign has no showcase", "showcase" in earn.campaign(live["slug"]), False)
for bad in ({"views": "lots"}, {"clips": "-5"}, {"platforms": {"instagram": "1e99"}}):
    try:
        earn.save_campaign({"results": bad}, done["id"])
        check(f"results {bad} are refused", False)
    except earn.EarnError:
        check(f"results {bad} are refused", True)
earn.save_campaign({"results": {"views": "", "platforms": {"instagram": "500", "x": "250"}}}, done["id"])
check("with no total typed, the platforms add up to it", earn.campaign(done["slug"])["showcase"]["views"], 750)
earn.save_campaign({"results": {}}, done["id"])
check("with no results typed, what was counted here is shown", earn.campaign(done["slug"])["showcase"]["views"], 0)

# ---- the order
earn.set_order([live["id"], soon["id"], done["id"], "cm_unknown"])
check("campaigns are shown in the order dragged", [c["title"] for c in earn.campaigns()], ["Mizo stream clips", "Next big creator", "eFootball Diwali"])
earn.set_order([soon["id"], live["id"]])
check("moving two leaves the rest after them", [c["title"] for c in earn.campaigns()][:2], ["Next big creator", "Mizo stream clips"])

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
