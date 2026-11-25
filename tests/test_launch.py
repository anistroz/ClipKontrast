"""Launch a campaign (clipkontrast.com/launch): creators, brands and agencies ask for a campaign. Checked: the pricing
(minimum budget, the 30% fee in or on top), what's refused (no name, bad email, under the minimum, robots), the
admins told, the admin's list and statuses, and a campaign made from a request pointing back at it."""
import os, sys, tempfile
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-launch-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="1",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0")
sys.path.insert(0, ".")
from unittest.mock import patch  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from studio import auth, db, leads  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


p = leads.pricing()
check("pricing: campaigns from ₹1,00,000, a 30% management fee, inside the budget", (p["min_budget"], p["fee_pct"], p["fee_mode"]), (100000, 30, "included"))
check("₹1,00,000: ₹70,000 to the clippers, ₹30,000 fee", leads.split(100000), {"pool": 70000.0, "fee": 30000.0, "total": 100000})
with patch.dict(os.environ, {"CLIPKONTRAST_CAMPAIGN_FEE_MODE": "on_top"}):
    check("...or the fee on top, when set so: ₹1,30,000 in all", leads.split(100000), {"pool": 100000, "fee": 30000.0, "total": 130000.0})
check("rupees the Indian way", (leads.inr(100000), leads.inr(2500000)), ("₹1,00,000", "₹25,00,000"))

boss, _ = auth._create("boss@example.com", "Boss", password_hash="x")
with db.engine.begin() as c:
    c.execute(db.users.update().where(db.users.c.id == boss.id).values(is_admin=True))
good = {"name": "Riya Sharma", "email": "riya@brand.in", "role": "brand", "org": "GameFuel", "budget": "5,00,000".replace(",", ""),
        "links": "https://instagram.com/gamefuel\njavascript:alert(1)", "platforms": ["youtube", "instagram", "bogus"], "rate": "30",
        "category": "Gaming", "brief": "Clip our sponsored streams", "whatsapp": "+91 98xxxxxx"}
for bad, why in (({**good, "name": ""}, "Please tell us your name"), ({**good, "email": "nope"}, "email address"),
                 ({**good, "budget": "50000"}, "start at ₹1,00,000"), ({**good, "org": "", "links": ""}, "channel or brand"),
                 ({**good, "website": "http://spam"}, "Something went wrong")):
    try:
        leads.submit(bad); check(f"refused: {why}", False)
    except leads.Refused as e:
        check(f"refused: {why}", why in str(e))
r = leads.submit(good)
got = leads.listing()
x = got["items"][0]
check("a good request is saved, new", (x["id"], x["status"], x["org"], x["budget"], x["role"], isinstance(x["t"], float)), (r["id"], "new", "GameFuel", 500000.0, "brand", True))
import json as _json  # noqa: E402
check("...and the admin's list can be sent to the page (plain JSON)", bool(_json.dumps(got)))
check("...links kept only when they're web links, platforms only known ones", (x["links"], x["platforms"]), (["https://instagram.com/gamefuel"], ["youtube", "instagram"]))
check("...the split shown to the admin", x["split"], {"pool": 350000.0, "fee": 150000.0, "total": 500000.0})
with db.engine.connect() as c:
    told = c.execute(sa.select(db.notices).where(db.notices.c.user_id == boss.id)).all()
check("the admins are told (the bell)", any("campaign request" in (n.title or "").lower() for n in told))
leads.update(r["id"], {"status": "contacted", "notes": "Called, sending deck"})
check("the admin marks it contacted, with notes", (leads.listing()["items"][0]["status"], leads.listing()["items"][0]["notes"]), ("contacted", "Called, sending deck"))
leads.update(r["id"], {"status": "won", "campaign_id": "cm_abc123"})
check("a campaign made from it: won, and pointing at the campaign", (leads.listing("won")["items"][0]["campaign_id"], leads.listing()["counts"]["won"]), ("cm_abc123", 1))
try:
    leads.update(r["id"], {"status": "maybe"}); check("an unknown status is refused", False)
except leads.Refused:
    check("an unknown status is refused", True)
page = open("web/launch.html", encoding="utf-8").read()
check("the page sends to the right address and shows the live pricing", "/api/public/campaign-request" in page and "/api/public/launch" in page)
check("the page shows no fee or pricing (the clip maker is free: nobody should think it became paid)",
      ("management fee" not in page.lower(), ">Pricing<" not in page, "stays free for clippers" in page), (True, True, True))
from studio import server  # noqa: E402
check("the page and its form are open to visitors (no sign-in)", ("/launch" in server.PAGES, server.OPEN[3] == "/api/public"), (True, True))
print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
