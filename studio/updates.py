"""Is there a newer ClipKontrast? Compares the version running here with the latest on GitHub, once a minute.

The version here is the git commit this folder was on when ClipKontrast started (read straight from .git, no git
program needed). Each minute, in the background, ClipKontrast asks GitHub which commit the project is on now: one small
request to the same address `git` itself uses, which has no hourly allowance to run out of. Only when that commit
changes does it ask GitHub's API what was added, to show the list. Nothing about this computer or its users is
sent. The owner sees a notice in the dashboard within a minute or two, with no restart.

    CLIPKONTRAST_UPDATE_REPO     where to look (default: the project's own repository; a fork points at itself)
    CLIPKONTRAST_UPDATE_BRANCH   which branch (default: main)
    CLIPKONTRAST_UPDATE_CHECK=0  never look"""
import re
import threading
import time

import httpx

from . import config

REPO = (config.env("CLIPKONTRAST_UPDATE_REPO") or "anistroz/clipkontrast").strip().strip("/")
BRANCH = (config.env("CLIPKONTRAST_UPDATE_BRANCH") or "main").strip()
ON = config.env("CLIPKONTRAST_UPDATE_CHECK", "1") != "0" and bool(re.fullmatch(r"[\w.\-]+/[\w.\-]+", REPO))
EVERY = 60
UA = {"User-Agent": "ClipKontrast-update-check"}
_state = {"checked": 0.0, "result": None, "seen": "", "notes": None, "reached": False}
_now = {"at": 0.0}
_now_lock = threading.Lock()
CHECK_GAP = 15                               # "Check for updates" pressed again sooner: the last answer is given
_lock = threading.Lock()
_started = False


def current() -> str:
    """The commit this folder is on now, or "" when it was not installed with git (a downloaded zip, for example)."""
    g = config.ROOT / ".git"
    try:
        if g.is_file():                      # a worktree or submodule: .git points somewhere else
            g = (config.ROOT / g.read_text(encoding="utf-8").split(":", 1)[1].strip()).resolve()
        head = (g / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head if re.fullmatch(r"[0-9a-f]{40}", head) else ""
        ref = head.split(":", 1)[1].strip()
        f = g / ref
        if f.is_file():
            return f.read_text(encoding="utf-8").strip()
        packed = g / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref:
                    return parts[0]
    except (OSError, IndexError):
        pass
    return ""


RUNNING = current()       # the code in memory: what ClipKontrast is actually running until it is restarted


def newest() -> str:
    """The commit the project is on right now, from the address git itself asks. "" if it cannot be told."""
    r = httpx.get(f"https://github.com/{REPO}.git/info/refs", params={"service": "git-upload-pack"}, headers=UA, timeout=15)
    if r.status_code != 200:
        return ""                            # a private repository, or GitHub is having a moment
    m = re.search(rb"([0-9a-f]{40}) refs/heads/" + re.escape(BRANCH).encode() + rb"[\x00\n]", r.content)
    return m.group(1).decode() if m else ""


def _what_changed(here: str):
    """(how many commits newer, their first lines, newest first), or None if GitHub's API will not say right now."""
    r = httpx.get(f"https://api.github.com/repos/{REPO}/compare/{here}...{BRANCH}", timeout=20,
                  headers={"Accept": "application/vnd.github+json", **UA})
    if r.status_code != 200:
        return None
    d = r.json()
    notes = []
    for c in reversed(d.get("commits") or []):
        # Only lines a change marks "What's new: ..." are shown: a commit's title also covers the website, the admin
        # pages and the build, which are not for the people using the clip maker.
        for line in str((c.get("commit") or {}).get("message") or "").splitlines():
            if line.lower().startswith("what's new:") and line[11:].strip():
                notes.append({"sha": str(c.get("sha") or "")[:7], "title": line[11:].strip()[:140],
                              "date": str(((c.get("commit") or {}).get("committer") or {}).get("date") or "")[:10]})
    return int(d.get("ahead_by") or 0), notes[:20]


def check(force: bool = False):
    """Look once. Returns what the dashboard should say, or None when this copy is up to date (or it cannot be told)."""
    if not ON:
        return None
    with _lock:
        now = time.time()
        if not force and now - _state["checked"] < EVERY:
            return _state["result"]
        _state["checked"] = now
        here, on_disk = RUNNING, current()
        if not here and config.APP_VERSION:
            return _check_zip()                  # a copy from the zip: no git, but it knows its version
        try:
            top = newest() if here else ""
        except Exception:  # noqa: BLE001 - offline: what was known stays, and it is asked again in a minute
            _state["reached"] = False
            return _state["result"]
        _state["reached"] = bool(top)
        if not top or top == here:
            _state.update(result=None, seen=top)
            return None
        if top != _state["seen"] or _state["notes"] is None:      # a commit not seen before: ask what it brought, once
            _state["seen"] = top
            try:
                _state["notes"] = _what_changed(here)
            except Exception:  # noqa: BLE001
                _state["notes"] = None
        got = _state["notes"]
        if got and got[0] == 0:
            _state["result"] = None          # this copy has its own newer commits: nothing to fetch
            return None
        _state["result"] = {"current": here[:7], "latest": top[:7], "behind": got[0] if got else None,
                            "notes": got[1] if got else [], "url": f"https://github.com/{REPO}/commits/{BRANCH}",
                            # the new files are already in the folder (git pull was run): only a restart is left
                            "restart": on_disk == top}
        return _state["result"]


def _version(v: str) -> tuple:
    import re as _re
    parts = _re.findall(r"\d+", str(v or ""))
    return tuple(int(p) for p in parts[:6]) if parts else (0,)


def _check_zip():
    """A copy unzipped from the download (Mac, Linux): the version in latest.json, published with each release, is
    compared with this one's. A newer one is offered as a download (unzipped over this folder, its data folder stays)."""
    import json as _json
    try:
        r = httpx.get(config.UPDATE_MANIFEST, headers=UA, timeout=20, follow_redirects=True)
        m = _json.loads(r.content.decode("utf-8-sig")) if r.status_code == 200 else None
    except Exception:  # noqa: BLE001 - offline: what was known stays
        _state["reached"] = False
        return _state["result"]
    _state["reached"] = isinstance(m, dict) and isinstance(m.get("version"), str)
    if not _state["reached"] or _version(m["version"]) <= _version(config.APP_VERSION):
        _state["result"] = None
        return None
    notes = [{"title": str(n)[:140], "date": ""} for n in (m.get("notes") or [])[:20] if str(n).strip()]
    _state["result"] = {"current": config.APP_VERSION, "latest": m["version"][:40], "behind": None, "notes": notes,
                        "url": config.DOWNLOAD_URL, "restart": False, "zip": True}
    return _state["result"]


def latest():
    """For the pages: what the last look found. Never waits on GitHub."""
    if config.INSTALLED:                     # the Windows app updates itself (studio/selfupdate.py)
        from . import selfupdate
        return selfupdate.latest()
    return _state["result"] if ON else None


def check_now() -> dict:
    """The "Check for updates" button: look right away (at most once every CHECK_GAP seconds) and say what was found.
    {"update": what the dashboard shows, or None; "current": this version; "reached": whether the answer came}"""
    if config.INSTALLED:
        from . import selfupdate
        mod, here = selfupdate, config.APP_VERSION
    else:
        mod, here = None, (RUNNING[:7] if RUNNING else config.APP_VERSION)
    if not (mod.ON if mod else ON and (RUNNING or config.APP_VERSION)):   # never looks, or can't tell
        return {"update": None, "current": here, "reached": False, "off": True}
    with _now_lock:
        due = time.time() - _now["at"] >= CHECK_GAP
        if due:
            _now["at"] = time.time()
    if mod:
        up = mod.check(force=due)
        return {"update": up, "current": here, "reached": mod.reached()}
    up = check(force=due)
    return {"update": up, "current": here, "reached": bool(_state["reached"])}


def start():
    """Look every minute, in the background, for as long as ClipKontrast runs."""
    global _started
    if config.INSTALLED:
        from . import selfupdate
        selfupdate.start()
        return
    if not ON or _started:
        return
    _started = True

    def loop():
        while True:
            try:
                check()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(EVERY)
    threading.Thread(target=loop, daemon=True).start()
