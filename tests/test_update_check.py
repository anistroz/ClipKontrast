"""The "Check for updates" button and the "What's new" line at the top of the app.

The button asks right away (instead of waiting for the next look, every few hours in the Windows app) and says which
of three things happened: a new version is out, this is the newest, or the answer couldn't be got. GitHub is replaced
by stand-ins, so nothing leaves this machine."""
import json, os, re, sys, tempfile
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-updchk-"), CLIPKONTRAST_UPDATE_CHECK="1", DATABASE_URL="",
                  CLIPKONTRAST_ACCOUNTS="0", CLIPKONTRAST_PUBLIC_URL="http://127.0.0.1:8765", CLIPKONTRAST_AI_KEY="",
                  CLIPKONTRAST_AI_MODELS="", CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0")
sys.path.insert(0, ".")
from fastapi.testclient import TestClient  # noqa: E402
from studio import config, db, selfupdate, server, updates  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


web = TestClient(server.app, base_url="http://127.0.0.1:8765")
O = {"Origin": "http://127.0.0.1:8765"}
updates.CHECK_GAP = 0                       # every press asks again, here


# ---------------------------------------------------------------- a git folder
updates.RUNNING = "a" * 40
gh = {"top": "a" * 40, "boom": False}
asked = []


def fake_newest():
    asked.append(1)
    if gh["boom"]:
        raise OSError("offline")
    return gh["top"]


updates.newest = fake_newest
updates._what_changed = lambda here: (2, [{"sha": "bbbbbbb", "title": "Fix facecam", "date": "2026-11-21"}])
r = web.post("/api/update/check", headers=O).json()
check("up to date: it says so, and that the answer came", (r["update"], r["reached"], r["current"]), (None, True, "a" * 7))
gh["top"] = "b" * 40
r = web.post("/api/update/check", headers=O).json()
check("a newer version: it's found at once, with what it brings", (r["update"]["latest"], r["update"]["notes"][0]["title"]), ("b" * 7, "Fix facecam"))
check("...and the dashboard shows it too", web.get("/api/status").json()["update"]["latest"], "b" * 7)
gh["boom"] = True
r = web.post("/api/update/check", headers=O).json()
check("offline: it says it couldn't check (not 'you have the newest')", r["reached"], False)
gh["boom"] = False
updates.CHECK_GAP = 3600
n = len(asked)
web.post("/api/update/check", headers=O)
web.post("/api/update/check", headers=O)
check("pressed again and again: GitHub isn't asked every time", len(asked) - n <= 1)
updates.CHECK_GAP = 0
check("a page on another site can't make it check", web.post("/api/update/check", headers={"Origin": "https://evil.example"}).status_code,
      lambda c: c in (403, 404))
updates.RUNNING = ""
check("a downloaded zip (no version to compare): it says it doesn't check", web.post("/api/update/check", headers=O).json().get("off"), True)

# ---------------------------------------------------------------- the Windows app
config.INSTALLED, config.APP_VERSION, selfupdate.ON = True, "2026.11.20.14", True
man = {"version": "2026.11.21.1", "app_zip": "https://x/app.zip", "installer": "https://x/setup.exe",
       "app_sha256": "a" * 64, "installer_sha256": "b" * 64, "notes": ["Check for updates", "What's new"]}


class R:
    def __init__(self, code, body):
        self.status_code, self.content = code, body


net = {"r": R(200, json.dumps(man).encode()), "boom": False}


def fake_get(url, timeout=30):
    if net["boom"]:
        raise OSError("offline")
    return net["r"]


selfupdate._get = fake_get
r = web.post("/api/update/check", headers=O).json()
check("Windows app: a newer version is found right away", (r["update"]["latest"], r["update"]["installed"], r["current"]),
      ("2026.11.21.1", True, "2026.11.20.14"))
check("...with its notes", [x["title"] for x in r["update"]["notes"]], ["Check for updates", "What's new"])
man["version"] = "2026.11.20.14"
net["r"] = R(200, json.dumps(man).encode())
r = web.post("/api/update/check", headers=O).json()
check("Windows app: the newest already", (r["update"], r["reached"]), (None, True))
net["boom"] = True
r = web.post("/api/update/check", headers=O).json()
check("Windows app offline: it couldn't check", r["reached"], False)
net["boom"] = False
net["r"] = R(404, b"")
check("Windows app, the file isn't there: it couldn't check", web.post("/api/update/check", headers=O).json()["reached"], False)
config.INSTALLED = False

# ---------------------------------------------------------------- the page
page = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
check("the page has the Check for updates button and what it does", all(x in page for x in ('data-act="updcheck"', "async function checkUpdates", "/api/update/check")))
check("...it tells all three answers apart", all(x in page for x in ("You have the newest version", "Couldn't check right now", "updateHow()")))
check("the What's new line sits at the very top, above the title bar", page.index('id="newsbar"') < page.index('<header class="topbar">'))
m = re.search(r"const NEWS = \{id: \"([\w-]+)\", items: \[(.*?)\n\]\};", page, re.S)
check("What's new has an id and a list", bool(m))
items = re.findall(r'\{e: "[^"]+", t: "([^"]+)"', m.group(2)) if m else []
check("...with the newest features in it", {"Fix facecam", "Free AI on your PC", "Check for updates"} <= set(items))
check("...shown again whenever the list changes, until closed", all(x in page for x in ("clipkontrast_news_seen", "newsHide()", "drawNews()")))
acts = re.findall(r'act: "(\w+)"', m.group(2)) if m else []
check("...and every button in it does something", all(f'a === "{a}"' in page for a in acts) and len(acts) >= 3)
check("...nothing in it about the website, the admin pages or the build",
      not re.search(r"admin page|website|workflow|build|github|server", (m.group(2) if m else "").lower()))

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
