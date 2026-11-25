"""Fixes brought in from PeakCut upstream (MIT), checked on ClipKontrast's code:

- the visitor's address: X-Forwarded-For believed only from a proxy on a private address, and only a real IP
- a downloaded clip is saved under its title, not "clip01.mp4"
- an upload left behind (tab closed) stops counting against uploads at once after 15 minutes
- YouTube's transcript in the language the video says it's in, never a translation

Everything outside this machine is replaced."""
import contextlib, json, os, sys, tempfile, time
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-up1-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0", CLIPKONTRAST_TRUST_PROXY="1")
sys.path.insert(0, ".")
from unittest.mock import patch  # noqa: E402
from studio import account, auth, ctx, db, media, server  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


class Req:
    def __init__(self, host, xff=None):
        self.client = type("C", (), {"host": host})()
        h = {"x-forwarded-for": [xff] if xff else []}
        self.headers = type("H", (), {"getlist": lambda s, k: h.get(k, []), "get": lambda s, k, d=None: (h.get(k) or [d])[0]})()


check("through the proxy in front (a private address): the visitor's address is the proxy's last entry",
      server._ip(Req("172.18.0.5", "6.6.6.6, 1.2.3.4")), "1.2.3.4")
check("a request straight from the internet can't pick its own address with the header",
      server._ip(Req("203.0.113.9", "9.9.9.9")), "203.0.113.9")
check("an entry that isn't an IP address is not believed", server._ip(Req("127.0.0.1", "evil<script>")), "127.0.0.1")
with patch.dict(os.environ, {"CLIPKONTRAST_TRUST_PROXY": "0"}):
    check("CLIPKONTRAST_TRUST_PROXY=0 means off", server._ip(Req("127.0.0.1", "1.2.3.4")), "127.0.0.1")

check("a downloaded clip is named after its title", account.clip_title_name({"title": "GTA 6: ye kya hua?! 😂", "hook": "x"}, "clip01"), "GTA 6 ye kya hua")
check("...its hook when it has no title, its id when neither", (account.clip_title_name({"hook": "WAIT FOR IT"}, "c"), account.clip_title_name({}, "clip02")),
      ("WAIT FOR IT", "clip02"))

user = auth.local_user()
root = server._up_root()
with ctx.as_user(user.id):
    old = root / "up-old"; old.mkdir(parents=True, exist_ok=True)
    (old / "meta.json").write_text(json.dumps({"user": user.id}))
    fresh = root / "up-fresh"; fresh.mkdir(exist_ok=True)
    (fresh / "meta.json").write_text(json.dumps({"user": user.id}))
    other = root / "up-other"; other.mkdir(exist_ok=True)
    (other / "meta.json").write_text(json.dumps({"user": "someone-else"}))
    gone = time.time() - 20 * 60
    for d in (old, other):
        for f in (d, d / "meta.json"):
            os.utime(f, (gone, gone))
    server._up_sweep()
check("your own upload left behind 15+ minutes ago is cleared, one still moving stays, someone else's stays",
      (old.exists(), fresh.exists(), other.exists()), (False, True, True))


class Ydl:
    def __init__(self, auto, lang):
        self.auto, self.lang = auto, lang

    def extract_info(self, url, download=False):
        return {"automatic_captions": self.auto, "language": self.lang}

    def urlopen(self, u):
        return type("R", (), {"read": lambda s, n: json.dumps({"events": [{"tStartMs": 0, "segs": [{"utf8": u}]}]}).encode()})()


def track(auto, lang):
    with patch.object(media, "_ydl", lambda opts: contextlib.nullcontext(Ydl(auto, lang))):
        got = media.youtube_words("https://www.youtube.com/watch?v=abcdefghijk")
    return got and got[1]


j3 = lambda u: [{"ext": "json3", "url": u}]  # noqa: E731
check("the transcript in the language the video says it's in", track({"en-orig": j3("en"), "hi-orig": j3("hi"), "hi": j3("hi-t")}, "hi"), "hi")
check("'en-IN' finds the English original", track({"en-orig": j3("en"), "fr": j3("fr")}, "en-IN"), "en")
check("no language said: any original", track({"es": j3("es"), "hi-orig": j3("hi")}, ""), "hi")
check("only translations: none (never a translation)", track({"en": j3("en"), "fr": j3("fr")}, ""), None)

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
