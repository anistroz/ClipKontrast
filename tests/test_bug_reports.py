"""Bug reports: from the clip maker on someone's computer (sent on to the website, with the technical details if they
agree), and from the website's report page. Checks what is kept, what is refused, the limits, the screenshot, and who
may see what.

    python tests/test_bug_reports.py local      the clip maker on someone's own computer (no accounts)
    python tests/test_bug_reports.py website    the website: anyone may report, only admins read

Runs against the code directly, with its own empty data folder; nothing outside this machine is contacted."""
import io
import os
import sys
import tempfile
import time
from unittest.mock import patch

MODE = sys.argv[1] if len(sys.argv) > 1 else "website"
BASE = "http://127.0.0.1:8765"
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="ck-bug-"), DATABASE_URL="", CLIPKONTRAST_FETCH_MODEL="0",
                  CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0", CLIPKONTRAST_PUBLIC_URL=BASE,
                  CLIPKONTRAST_ACCOUNTS="0" if MODE == "local" else "1", CLIPKONTRAST_SMTP_HOST="", CLIPKONTRAST_EARN_ONLY="")
sys.path.insert(0, ".")
import sqlalchemy as sa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from studio import auth, config, db, feedback, server  # noqa: E402

db.init()
fails = []
ORIGIN = {"Origin": BASE}
web = TestClient(server.app, base_url=BASE, follow_redirects=False)


def check(n, got, want=True):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


def png(w=1200, h=800, color=(200, 30, 30)):
    b = io.BytesIO(); Image.new("RGB", (w, h), color).save(b, "PNG"); return b.getvalue()


def reset_limits():
    auth._attempts.clear()


# ================================================================ the clip maker on someone's computer
if MODE == "local":
    from studio import diagnose, jobs
    # a log with a path that names the person, and a key, the way a real one might
    (config.DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
    home = os.path.expanduser("~")
    (config.DATA_DIR / "logs" / "clipkontrast.log").write_text(
        "\n".join([f"line {i}" for i in range(300)] + [f"ERROR reading {home}/Videos/stream.mp4", "api_key=AIzaSECRET123 sent",
                                                       r"C:\Users\Rahul\AppData\Local\ClipKontrast failed"]), encoding="utf-8")
    jobs._jobs["jtest"] = {"id": "jtest", "created": 1, "title": "Mizo day 3", "error": "ffmpeg: received no packets",
                           "clips": [{"id": 2, "status": "error", "error": "Out of memory", "layout": "split", "style": "box"}]}
    d = web.get("/api/bug-report/details").json()
    check("the app line says which version and computer", d["app"].startswith("ClipKontrast ") and "CPUs" in d["app"])
    check("the details have the setup, the recent errors and the log's end",
          all(x in d["details"] for x in ("ffmpeg:", "Mizo day 3", "received no packets", "Out of memory", "line 299")))
    check("the log is cut to its last lines", "line 100\n" in d["details"], False)
    check("the person's home folder never leaves the computer", home in d["details"], False)
    check("nor another Windows user name", "Rahul" in d["details"], False)
    check("nor a key from the log", "AIzaSECRET123" in d["details"], False)
    check("the details stay a sensible size", len(d["details"]) <= diagnose.MAX_CHARS)

    sent = {}

    class Ok:
        status_code = 200

        def json(self):
            return {"id": 41}

    def fake_post(url, data=None, files=None, **kw):
        sent.update(url=url, data=data, files=files); return Ok()

    with patch("httpx.post", side_effect=fake_post):
        r = web.post("/api/bug-report", data={"message": "Clips came out blurry", "steps": "Pasted a stream", "contact": "@me",
                                              "details": "1"}, files={"screenshot": ("s.jpg", png(), "image/png")}, headers=ORIGIN)
    check("the app sends the report on and shows its number", (r.status_code, r.json()), (200, {"id": 41}))
    check("it goes to the ClipKontrast website, nowhere else", sent["url"], config.EARN_URL + "/api/public/bug-report")
    check("with the person's words, contact and the technical details",
          (sent["data"]["message"], sent["data"]["contact"], sent["data"]["source"], "Mizo day 3" in sent["data"]["diag"]),
          ("Clips came out blurry", "@me", "app", True))
    check("and the screenshot", bool(sent["files"] and sent["files"]["screenshot"][1]))
    with patch("httpx.post", side_effect=fake_post):
        web.post("/api/bug-report", data={"message": "No details please", "details": "0"}, headers=ORIGIN)
    check("unticked, no technical details go", (sent["data"]["diag"], sent["files"]), ("", None))

    class Busy:
        status_code = 429

        def json(self):
            return {"detail": "Lots of reports were sent from here recently. Try again in a while."}
    with patch("httpx.post", return_value=Busy()):
        r = web.post("/api/bug-report", data={"message": "again"}, headers=ORIGIN)
    check("the website's answer is passed on when it says wait", (r.status_code, r.json()["detail"][:20]), (429, "Lots of reports were"))
    with patch("httpx.post", side_effect=OSError("offline")):
        r = web.post("/api/bug-report", data={"message": "offline"}, headers=ORIGIN)
    check("with no internet it says so", (r.status_code, "internet" in r.json()["detail"]), (502, True))
    check("another website can't make the app send a report",
          web.post("/api/bug-report", data={"message": "x" * 10}, headers={"Origin": "https://evil.example"}).status_code, 403)

# ================================================================ the website
else:
    u = auth.signup("admin@example.com", "test-pass-123", "Admin")[0]
    v = auth.signup("someone@example.com", "test-pass-123", "Someone")[0]
    with db.engine.begin() as c:
        c.execute(db.users.update().where(db.users.c.id == u.id).values(is_admin=True))
        c.execute(db.users.update().where(db.users.c.id == v.id).values(is_admin=False))
    admin_cookie, user_cookie = auth.start_session(u.id), auth.start_session(v.id)

    def post(data, files=None, headers=ORIGIN):
        return web.post("/api/public/bug-report", data=data, files=files, headers=headers)

    reset_limits()
    r = post({"message": "The installer won't open", "steps": "Double clicked it", "contact": "@clipper",
              "app": "ClipKontrast 2026.11.20.1 (installed app) · Windows 10", "diag": "Setup:\n  ffmpeg: yes", "source": "app"},
             files={"screenshot": ("s.png", png(3000, 2000), "image/png")})
    check("anyone can send a report, without signing in", r.status_code, 200)
    fid = r.json()["id"]
    with db.engine.connect() as c:
        row = c.execute(sa.select(db.feedback).where(db.feedback.c.id == fid)).first()
    check("it's kept with everything that came with it",
          (row.kind, row.source, row.contact, row.status, row.shot, "Double clicked it" in row.message, row.diag.startswith("Setup:")),
          ("bug", "app", "@clipper", "new", 1, True, True))
    p = feedback.shot_path(fid)
    im = Image.open(p)
    check("the screenshot is saved again as a plain picture, at most 2000 px", (im.format, max(im.size) <= 2000), ("JPEG", True))
    with db.engine.connect() as c:
        n = c.execute(sa.select(db.notices).where(db.notices.c.user_id == u.id)).all()
    check("the admin gets a notice that leads to the reports", any("/admin/earn/bugs" in str(x._mapping.get("link", "")) for x in n))

    # ---- what is refused
    for name, data, files in (
            ("an empty report", {"message": "  "}, None),
            ("a huge message", {"message": "x" * 4001}, None),
            ("a file that isn't a picture", {"message": "see file"}, {"screenshot": ("a.png", b"MZ\x90\x00 not a picture", "image/png")}),
            ("an SVG pretending to be a picture", {"message": "see file"}, {"screenshot": ("a.svg", b"<svg onload=alert(1)></svg>", "image/svg+xml")})):
        reset_limits()
        check(f"{name} is refused", post(data, files).status_code, 400)
    reset_limits()
    check("a picture over 7 MB is cut off before it's read",
          post({"message": "big"}, {"screenshot": ("a.png", b"\x89PNG" + b"0" * (7 * 1024 * 1024 + 10), "image/png")}).status_code, 413)
    reset_limits()
    r = post({"message": "weird\x00\x07 chars", "contact": "@x\x1b[31m", "source": "<script>"})
    with db.engine.connect() as c:
        row = c.execute(sa.select(db.feedback).where(db.feedback.c.id == r.json()["id"])).first()
    check("control characters are taken out, and an unknown source counts as the website", (row.contact, row.source), ("@x[31m", "website"))
    check("another website can't post reports", post({"message": "spam spam"}, headers={"Origin": "https://evil.example"}).status_code, 403)

    # ---- the limits
    reset_limits()
    codes = [post({"message": f"report {i}"}).status_code for i in range(7)]
    check("six reports an hour from one address, then wait", (codes[:6], codes[6]), ([200] * 6, 429))

    # ---- who sees what
    reset_limits()
    web.cookies.clear()
    check("signed out, the reports can't be read", web.get("/api/admin/feedback").status_code in (401, 404))
    check("...nor a screenshot", web.get(f"/api/admin/feedback/{fid}/shot").status_code in (401, 404))
    web.cookies.set(auth.COOKIE, user_cookie)
    check("a clipper can't read them", web.get("/api/admin/feedback").status_code, 404)
    check("...nor a screenshot", web.get(f"/api/admin/feedback/{fid}/shot").status_code, 404)
    check("...nor the server's log through the app's report window", "line" in web.get("/api/bug-report/details").json()["details"], False)
    web.cookies.set(auth.COOKIE, admin_cookie)
    lst = web.get("/api/admin/feedback").json()
    mine = [x for x in lst["items"] if x["id"] == fid][0]
    check("the admin sees the report with its details", (mine["contact"], mine["shot"], mine["app"][:12], mine["source"]),
          ("@clipper", True, "ClipKontrast", "app"))
    r = web.get(f"/api/admin/feedback/{fid}/shot")
    check("and its screenshot, never kept by a proxy", (r.status_code, r.headers["content-type"], "no-store" in r.headers.get("cache-control", "")),
          (200, "image/jpeg", True))
    check("a report with no screenshot has none", web.get(f"/api/admin/feedback/{fid + 1}/shot").status_code, 404)
    check("the admin marks it fixed", web.post(f"/api/admin/feedback/{fid}", json={"status": "done"}, headers=ORIGIN).status_code, 200)
    check("...and it's counted as fixed", web.get("/api/admin/feedback").json()["counts"]["done"], 1)
    check("the Bug reports tab opens for the admin", web.get("/admin/earn/bugs").status_code, 200)

    # ---- every report as a CSV file, to hand over in one go
    import csv as _csv, io as _io
    with db.engine.begin() as cx:
        cx.execute(db.feedback.insert().values(t=time.time(), kind="bug", message="=HYPERLINK(\"http://evil\")", status="new",
                                               updated_at=time.time(), source="website", contact="+91 99", app="", diag="", shot=0))
    r = web.get("/api/admin/feedback.csv")
    rows = list(_csv.reader(_io.StringIO(r.content.decode("utf-8-sig"))))
    check("the admin downloads every report as a CSV file", (r.status_code, "attachment" in r.headers.get("content-disposition", ""),
                                                             r.headers["content-type"].startswith("text/csv")), (200, True, True))
    check("...with a column for each detail, the technical ones too", rows[0][:3] + rows[0][-2:], ["id", "date", "status", "technical_details", "screenshot"])
    mine = next(x for x in rows[1:] if x[0] == str(fid))
    check("...each report on its row", (mine[2], mine[3], mine[13], "ClipKontrast" in mine[8]), ("done", "app", "yes", True))
    evil = next(x for x in rows[1:] if "HYPERLINK" in x[11])
    check("...text a spreadsheet would run as a formula is kept as text", (evil[11][:1], evil[7][:1]), ("'", "'"))
    only_new = list(_csv.reader(_io.StringIO(web.get("/api/admin/feedback.csv?status=new").content.decode("utf-8-sig"))))
    check("...or just the ones in the list being looked at", all(x[2] == "new" for x in only_new[1:]) and len(only_new) < len(rows))
    web.cookies.set(auth.COOKIE, user_cookie)
    check("a clipper can't download them", web.get("/api/admin/feedback.csv").status_code, 404)
    web.cookies.set(auth.COOKIE, admin_cookie)
    page = (config.ROOT / "web" / "earn-admin.html").read_text(encoding="utf-8")
    check("the Bug reports tab has a Download CSV button", "/api/admin/feedback.csv?status=" in page and "IC.down" in page)
    web.cookies.clear()
    r = web.get("/report")
    check("the report page opens for anyone", (r.status_code, "Report a problem" in r.text), (200, True))

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
