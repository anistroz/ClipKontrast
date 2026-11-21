"""Paid campaigns in the app: the website's feed (/api/earn/public/app), the app reading it (/api/campaigns), the
campaign pictures and stream thumbnails through the app, and the Home and Paid campaigns screens in a browser.
Starts two servers: a website (Earn only) with campaigns, and an app that reads it.
Usage: test_campaigns_app.py <project root>"""
import os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
import httpx
ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
SITE_PORT, APP_PORT = 8811, 8812
SITE, APP = f"http://127.0.0.1:{SITE_PORT}", f"http://127.0.0.1:{APP_PORT}"
fails = []
SHOTS = Path(os.environ.get("CK_SHOTS") or tempfile.mkdtemp(prefix="ck-camp-shots-"))


def check(name, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"   got {str(got)[:300]!r}"))
    ok or fails.append(name)


def wait(base):
    for _ in range(60):
        try:
            urllib.request.urlopen(base + "/healthz", timeout=2); return
        except Exception:
            time.sleep(1)


site_data, app_data = tempfile.mkdtemp(prefix="ck-camp-site-"), tempfile.mkdtemp(prefix="ck-camp-app-")
common = {"DATABASE_URL": "", "CLIPKONTRAST_FETCH_MODEL": "0", "CLIPKONTRAST_UPDATE_CHECK": "0", "CLIPKONTRAST_AUTO_RELOAD": "0",
          "CLIPKONTRAST_WHISPER": "0"}
subprocess.run([sys.executable, "tests/campaigns_seed.py"], cwd=ROOT, check=True, env={**os.environ, **common, "CLIPKONTRAST_DATA": site_data,
                                                                                        "CLIPKONTRAST_ACCOUNTS": "1"})
site = subprocess.Popen([sys.executable, "-m", "studio.server"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={
    **os.environ, **common, "CLIPKONTRAST_DATA": site_data, "CLIPKONTRAST_PORT": str(SITE_PORT), "CLIPKONTRAST_PUBLIC_URL": SITE,
    "CLIPKONTRAST_ACCOUNTS": "1", "CLIPKONTRAST_EARN_ONLY": "1", "CLIPKONTRAST_VERIFY_EMAIL": "0", "CLIPKONTRAST_EARN_URL": SITE})
app = subprocess.Popen([sys.executable, "-m", "studio.server"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={
    **os.environ, **common, "CLIPKONTRAST_DATA": app_data, "CLIPKONTRAST_PORT": str(APP_PORT), "CLIPKONTRAST_PUBLIC_URL": APP,
    "CLIPKONTRAST_ACCOUNTS": "0", "CLIPKONTRAST_EARN_URL": SITE})
try:
    wait(SITE); wait(APP)
    # ---- the website's feed
    f = httpx.get(SITE + "/api/earn/public/app", timeout=30).json()
    titles = [c["title"] for c in f["live"]]
    check("the website's feed: the live campaign first, the one coming soon, never a draft",
          (titles, "Draft never shown" in str(f)), (["GTA 6 Launch × Mizo Plays", "Secret next campaign"], False))
    mz = f["live"][0]
    check("...the live campaign has its pool, rate, platforms and end", (mz["budget"], mz["rate_per_1k"], mz["platforms"], bool(mz["ends_at"])),
          (110000, 25, ["youtube", "instagram"], True))
    check("...every stream and video the admin listed, in order, links made plain",
          [(s["name"], s["kind"], s["url"]) for s in mz["streams"]],
          [("Day 1", "youtube", "https://www.youtube.com/watch?v=AAAAAAAAAAA"), ("Day 2", "youtube", "https://www.youtube.com/watch?v=BBBBBBBBBBB"),
           ("Day 3", "youtube", "https://www.youtube.com/watch?v=CCCCCCCCCCC"), ("Kick stream", "kick", "https://kick.com/mizoplays/videos/1234-abcd"),
           ("Teaser video", "youtube", "https://www.youtube.com/watch?v=DDDDDDDDDDD"), ("Raw folder", "drive", "https://drive.google.com/drive/folders/abcdefghijklmn")])
    check("...each stream with the moments marked on it", [len(s["moments"]) for s in mz["streams"]], [1, 0, 2, 0, 0, 0])
    check("...the raw clips folder stays for those who joined, on the website", "secretfolder123" not in str(f))
    soon = f["live"][1]
    check("a campaign coming soon shows its name, not its streams or brief", (soon["state"], soon["streams"], soon["brief"]), ("soon", [], ""))
    check("ended campaigns, for what they paid", [(c["title"], c["budget"], c["views"]) for c in f["ended"]],
          lambda x: sorted(x) == sorted([("Diwali Stream Clips", 75000, 9800000), ("BGMI Finals × Mizo", 50000, 6200000), ("Valorant Week", 25000, 2100000)]))
    check("...and the total of them", (f["totals"]["ended_budget"], f["totals"]["ended_count"]), (150000, 3))
    check("nothing about any clipper is in the feed", not any(k in str(f) for k in ("@example", "upi", "whatsapp")))

    # ---- the app reading it
    a = httpx.get(APP + "/api/campaigns", timeout=30).json()
    check("the app shows the website's campaigns", ([c["title"] for c in a["live"]], len(a["ended"]), a["reached"]),
          (["GTA 6 Launch × Mizo Plays", "Secret next campaign"], 3, True))
    cover = a["live"][0]["cover"]
    check("...the campaign's picture comes through the app (pages here show only pictures from here)", cover.startswith("/api/campaign-cover?p=%2Fearn%2Fcover%2F"))
    r = httpx.get(APP + cover, timeout=30)
    check("...and is the website's picture", (r.status_code, r.headers.get("content-type"), r.content[:3]), (200, "image/jpeg", b"\xff\xd8\xff"))
    check("only the website's own campaign pictures, never another address",
          [httpx.get(APP + "/api/campaign-cover", params={"p": p}, timeout=10).status_code for p in
           ("https://evil.example/x.jpg", "/earn/cover/../../etc/passwd", "//evil.example/earn/cover/abc.jpg", "/api/admin/earn/x")], [404] * 4)
    check("the drive folder is a link, not something to clip; the streams are clippable",
          [s["clip"] for s in a["live"][0]["streams"]], [True, True, True, True, True, False])
    check("stream pictures: only links to the video sites", [httpx.get(APP + "/api/link-thumb", params={"url": u}, timeout=10).status_code
                                                          for u in ("http://127.0.0.1:8811/healthz", "file:///etc/passwd", "https://evil.example/a.jpg")], [404] * 3)
    check("on the website, stream pictures are only for the admin", httpx.get(SITE + "/api/link-thumb", params={"url": "https://youtu.be/AAAAAAAAAAA"}, timeout=10).status_code,
          lambda c: c in (401, 404))

    # ---- the screens, in a browser (Playwright, run by Node)
    import json as _json, shutil as _sh
    has_pw = _sh.which("node") and subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode == 0
    httpx.put(APP + "/api/settings", json={"tour_done": True}, headers={"Origin": APP}, timeout=10)   # the first-run tour, seen
    if has_pw:
        from PIL import Image, ImageDraw
        thumb = SHOTS / "thumb.jpg"                    # a stream's picture, so the browser needs no internet
        im = Image.new("RGB", (480, 270)); dr = ImageDraw.Draw(im)
        for x in range(480):
            dr.line([(x, 0), (x, 270)], fill=(int(20 + x / 480 * 60), int(40 + x / 480 * 90), int(120 - x / 480 * 60)))
        dr.ellipse((190, 85, 290, 185), fill=(255, 255, 255)); dr.text((20, 220), "LIVE STREAM", fill=(255, 255, 255), font_size=28)
        im.save(thumb, "JPEG")
        # an admin on the website, for the campaign editor
        boss = httpx.Client(base_url=SITE, timeout=30)
        boss.post("/api/auth/signup", json={"email": "boss@example.com", "password": "test-pass-123"}, headers={"Origin": SITE})
        subprocess.run([sys.executable, "-m", "studio.admin", "grant", "boss@example.com"], cwd=ROOT, capture_output=True,
                       env={**os.environ, **common, "CLIPKONTRAST_DATA": site_data, "CLIPKONTRAST_ACCOUNTS": "1"})
        ck = next(iter(boss.cookies.jar))
        p = subprocess.run(["node", str(Path(ROOT) / "tests" / "campaigns_ui.cjs"), APP, str(SHOTS), str(thumb), SITE, ck.name, ck.value],
                           capture_output=True, text=True, timeout=240)
        lines = [l for l in p.stdout.splitlines() if l.startswith("{")]
        for l in lines:
            r = _json.loads(l)
            check(r["name"], r["got"], r["want"])
        check("the browser checks ran to the end", (p.returncode, bool(lines), p.stderr[-400:]), (0, True, ""))
    else:
        print("SKIP the screens: Node with Playwright isn't on this machine")

    # ---- the website can't be reached: nothing breaks
    site.terminate(); site.wait(10)
    import json as _j
    r = httpx.get(APP + "/api/campaigns?fresh=1", timeout=30)
    check("the app keeps what it had for a few minutes, and never errors", r.status_code, 200)
finally:
    for p in (site, app):
        if p.poll() is None:
            p.terminate()
print(f"  screenshots: {SHOTS}")
print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
