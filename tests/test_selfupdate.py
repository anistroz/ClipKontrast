"""The Windows app's "Update now": reading latest.json, downloading and checking the new code, unpacking it next to
the running one, and refusing anything that doesn't match. Served from this computer; nothing is restarted.

Runs against the code directly, with its own empty folders."""
import hashlib, http.server, json, os, sys, tempfile, threading, time, zipfile
from pathlib import Path
from unittest.mock import patch
os.environ["CLIPKONTRAST_DATA"] = tempfile.mkdtemp(prefix="pc-upd-")
sys.path.insert(0, ".")
from studio import config, selfupdate, updates
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


serve = Path(tempfile.mkdtemp(prefix="pc-upd-web-"))
install = Path(tempfile.mkdtemp(prefix="pc-upd-app-"))
(install / "python").mkdir()
(install / "python" / "DEPS").write_text("deps-1")


def make_zip(name, files):
    p = serve / name
    with zipfile.ZipFile(p, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return hashlib.sha256(p.read_bytes()).hexdigest()


good = make_zip("app.zip", {"studio/server.py": "print('new')", "web/index.html": "<html>"})
evil = make_zip("evil.zip", {"studio/server.py": "x", "../outside.txt": "nope"})
(serve / "setup.exe").write_bytes(b"MZ installer")
setup_sha = hashlib.sha256(b"MZ installer").hexdigest()


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(serve), **k)

    def log_message(self, *a):
        pass


httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{httpd.server_address[1]}"


def manifest(**over):
    m = {"version": "2026.11.20.1", "app_zip": f"{base}/app.zip", "app_sha256": good, "installer": f"{base}/setup.exe",
         "installer_sha256": setup_sha, "deps": "deps-1", "notes": ["Faster clips", "Hindi captions"]}
    m.update(over)
    (serve / "latest.json").write_text("﻿" + json.dumps(m), encoding="utf-8")       # with the mark Windows adds


def wait_done():
    for _ in range(100):
        if selfupdate.progress()["phase"] in ("restarting", "error"):
            return selfupdate.progress()
        time.sleep(0.05)
    return selfupdate.progress()


quits = []
with patch.object(selfupdate, "ON", True), patch.object(config, "APP_VERSION", "2026.11.19.1"), \
        patch.object(config, "INSTALL_DIR", install), patch.object(config, "INSTALLED", True), \
        patch.object(config, "UPDATE_MANIFEST", f"{base}/latest.json"), \
        patch.object(selfupdate, "_quit", lambda code: quits.append(code)):
    check("versions compare as numbers", selfupdate._version("2026.11.20.1") > selfupdate._version("2026.11.9.9"))

    manifest()
    r = selfupdate.check(force=True)
    check("a newer version is offered", (r or {}).get("latest"), "2026.11.20.1")
    check("its notes are shown", [n["title"] for n in r["notes"]], ["Faster clips", "Hindi captions"])
    check("same libraries: just the code is downloaded", r["full"], False)
    check("the dashboard sees it through the usual update notice", updates.latest(), r)

    selfupdate.apply()
    p = wait_done()
    check("the update downloads, checks and unpacks", (p["phase"], quits[-1:]), ("restarting", [75]))
    check("the new code is next to the running one, with its version",
          ((install / "app.new" / "studio" / "server.py").read_text(), (install / "app.new" / "VERSION").read_text()),
          ("print('new')", "2026.11.20.1"))

    manifest(version="2026.11.19.1")
    check("the same version is not offered", selfupdate.check(force=True), None)
    manifest(version="2026.11.1.1")
    check("an older version is not offered", selfupdate.check(force=True), None)

    selfupdate._job.update(phase="idle")
    manifest(app_sha256="0" * 64)
    selfupdate.check(force=True)
    selfupdate.apply()
    p = wait_done()
    check("a download that doesn't match is refused, nothing left behind",
          (p["phase"], "didn't match" in p["error"], (install / "app.new").exists()), ("error", True, False))

    selfupdate._job.update(phase="idle")
    manifest(app_zip=f"{base}/evil.zip", app_sha256=evil)
    selfupdate.check(force=True)
    selfupdate.apply()
    p = wait_done()
    check("a zip that would write outside the app folder is refused",
          (p["phase"], (install.parent / "outside.txt").exists(), (install / "app.new").exists()), ("error", False, False))

    selfupdate._job.update(phase="idle")
    manifest(deps="deps-2")
    r = selfupdate.check(force=True)
    check("new libraries: the whole installer is needed", r["full"], True)
    selfupdate.apply()
    p = wait_done()
    check("the installer is downloaded and run by the launcher",
          (p["phase"], quits[-1], (install / "update" / "ClipKontrast-Setup.exe").read_bytes()), ("restarting", 76, b"MZ installer"))

    selfupdate._job.update(phase="idle")
    manifest(app_zip="http://example.com/app.zip")
    check("a plain-http address elsewhere is refused", selfupdate.check(force=True), None)
    (serve / "latest.json").write_text("not json")
    check("a broken latest.json is ignored", selfupdate.check(force=True), None)

check("a copy that isn't the installed app never offers these updates", selfupdate.latest() if not selfupdate.ON else None, None)
httpd.shutdown()
if fails:
    print(f"{len(fails)} FAILED"); sys.exit(1)
print("ALL PASSED")
