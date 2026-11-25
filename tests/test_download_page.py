"""The download page, its three links (and nothing else), the app version it shows, a campaign's important note,
and a column added to a table after an older database was made.

Runs against the code directly, with its own empty data folder. Pass a PostgreSQL address as the first argument to
run the database part against PostgreSQL too."""
import os, sys, tempfile
from unittest.mock import patch
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="ck-dl-"), DATABASE_URL=sys.argv[1] if len(sys.argv) > 1 else "",
                  CLIPKONTRAST_ACCOUNTS="1", CLIPKONTRAST_EARN_ONLY="1", CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0")
sys.path.insert(0, ".")
import sqlalchemy as sa
fails = []


def check(n, got, want=True):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


# ---- an older database, made before the "notice" column existed, gets it on start
from studio import config, db
old = sa.MetaData()                    # the campaigns table as the live server has it: everything but "notice"
NEW = ("notice", "sort_order", "results")
sa.Table("earn_campaigns", old, *[c._copy() for c in db.earn_campaigns.columns if c.name not in NEW])
with db.engine.begin() as c:
    c.execute(sa.text("DROP TABLE IF EXISTS earn_campaigns CASCADE" if db.engine.dialect.name == "postgresql" else "DROP TABLE IF EXISTS earn_campaigns"))
old.create_all(db.engine)
with db.engine.begin() as c:
    c.execute(sa.text("INSERT INTO earn_campaigns (id, slug, title, created_at, updated_at) VALUES ('old1', 'old1', 'Made before', 0, 0)"))
check("the older table really has no note column", "notice" in {c["name"] for c in sa.inspect(db.engine).get_columns("earn_campaigns")}, False)
db.init()
cols = {c["name"] for c in sa.inspect(db.engine).get_columns("earn_campaigns")}
check("an older table gets the new columns", {"notice", "sort_order", "results", "accent", "budget", "status"} <= cols)
with db.engine.connect() as c:
    check("its rows keep their data, and the new columns start empty",
          tuple(c.execute(sa.text("SELECT title, notice, sort_order, results FROM earn_campaigns WHERE id = 'old1'")).first()), ("Made before", "", 0, ""))
db.init()
check("starting again changes nothing", {c["name"] for c in sa.inspect(db.engine).get_columns("earn_campaigns")}, cols)
with db.engine.begin() as c:
    c.execute(sa.text("DELETE FROM earn_campaigns"))

# ---- a campaign's important note
from studio import earn
camp = earn.save_campaign({"title": "Mizo stream clips", "creator_name": "Mizo Plays", "status": "live", "rate_per_1k": 30,
                           "budget": 110000, "platforms": ["youtube"],
                           "notice": "Only send clips of Mizo Plays. Clips of other creators will be rejected." + " x" * 800})
check("the note is saved, and kept to 1,000 letters", (camp["notice"].startswith("Only send clips of Mizo Plays."), len(camp["notice"])), (True, 1000))
public = [c for c in earn.campaigns() if c["id"] == camp["id"]][0]
check("clippers see the note", public["notice"][:30], "Only send clips of Mizo Plays.")

# ---- the pages and links
from fastapi.testclient import TestClient
from studio import server
web = TestClient(server.app)
r = web.get("/download")
check("the download page opens without signing in", (r.status_code, "Download for Windows" in r.text), (200, True))
for system, name in (("windows", "ClipKontrast-Setup.exe"), ("mac", "ClipKontrast-Mac-Linux.zip"), ("linux", "ClipKontrast-Mac-Linux.zip")):
    r = web.get(f"/download/{system}", follow_redirects=False)
    check(f"/download/{system} sends the browser straight to the newest file", (r.status_code, r.headers.get("location")),
          (302, config.RELEASES_URL + name))
for bad in ("android", "..%2F..%2Fetc", "https:%2F%2Fevil.example", "WINDOWS"):
    check(f"/download/{bad} goes nowhere", web.get(f"/download/{bad}", follow_redirects=False).status_code, 404)
check("the releases address can't be changed from a request", config.RELEASES_URL.startswith("https://github.com/anistroz/"))


class R:
    status_code = 200
    content = b'\xef\xbb\xbf{"version": "2026.11.20.1", "installer_sha256": "' + b"a" * 64 + b'"}'


with patch("httpx.get", return_value=R()) as got:
    server._APP_VERSION.update(at=0, v=None)
    check("the page shows the newest version and the installer's SHA-256", web.get("/api/public/app-version").json(),
          {"version": "2026.11.20.1", "windows_sha256": "a" * 64})
    web.get("/api/public/app-version")
    check("latest.json is read once an hour, not per visitor", got.call_count, 1)


class Bad:
    status_code = 200
    content = b'{"version": "<script>", "installer_sha256": "nope"}'


with patch("httpx.get", return_value=Bad()):
    server._APP_VERSION.update(at=0, v=None)
    check("a strange latest.json shows nothing", web.get("/api/public/app-version").json(), {})
check("the Earn page's download buttons lead to the download page", web.get("/api/public").json()["download_url"], config.EARN_URL + "/download")
check("the Earn page leads to the app download (its buttons, menu and footer)", 'href="/download"' in web.get("/earn").text)

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
