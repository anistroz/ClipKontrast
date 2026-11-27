"""Problems reported by themselves, for people who turn it on (Settings, off by default).

When a video or a clip fails in the ClipKontrast app on someone's computer, the same report "Report a problem" sends
(what failed, where in the code, and the app's technical details: version, system, the last errors) goes to the
ClipKontrast website's bug reports, so it can be fixed without anyone writing in. Like Sentry, but to ClipKontrast's
own server and nobody else.

What's sent never has the computer's user name in it (diagnose.py cuts paths down), never a video or a picture, and
never anything from a website's shared server (only the app on someone's own computer sends). At most a few a day, and
the same problem only once a day."""
import hashlib
import json
import threading
import time

from . import config

MAX_A_DAY = 5
_lock = threading.Lock()


def _log_file():
    return config.DATA_DIR / "autoreport.json"


def enabled(uid) -> bool:
    if config.ACCOUNTS or not config.EARN_URL:
        return False
    from . import accounts, ctx
    try:
        with ctx.as_user(uid):
            return bool(accounts.settings().get("auto_reports"))
    except Exception:  # noqa: BLE001
        return False


def _allowed(key: str) -> bool:
    """Not more than MAX_A_DAY a day, and each problem once a day (kept in a small file)."""
    today = time.strftime("%Y-%m-%d")
    with _lock:
        try:
            log = json.loads(_log_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log = {}
        if log.get("day") != today:
            log = {"day": today, "sent": []}
        if key in log["sent"] or len(log["sent"]) >= MAX_A_DAY:
            return False
        log["sent"].append(key)
        try:
            _log_file().write_text(json.dumps(log), encoding="utf-8")
        except OSError:
            pass
        return True


def report(uid, what: str, error: str, where: str = "", send=None) -> bool:
    """Send one problem, in the background, if this person turned it on. True when it was handed over to be sent."""
    if not enabled(uid):
        return False
    key = hashlib.sha1(f"{what}|{str(error)[:160]}|{where}".encode("utf-8", "replace")).hexdigest()[:16]
    if not _allowed(key):
        return False
    from . import diagnose
    form = {"message": diagnose._scrub(f"Automatic report: {what}: {str(error)[:600]}"), "steps": "", "contact": "",
            "context": diagnose._scrub(f"Where: {where}" if where else "")[:1000], "source": "app", "app": diagnose.app_line(),
            "diag": diagnose.details()}

    def go():
        try:
            if send:
                send(form)
                return
            import httpx
            httpx.post(config.EARN_URL + "/api/public/bug-report", data=form, timeout=45,
                       headers={"User-Agent": "ClipKontrast-auto-report"})
        except Exception:  # noqa: BLE001 - a report that can't go now isn't worth retrying: the next problem will
            pass
    threading.Thread(target=go, daemon=True).start()
    return True
