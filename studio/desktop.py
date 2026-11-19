"""ClipKontrast as a desktop app on Windows: its own window, and no black console window behind it.

The desktop and Start menu shortcuts run `pythonw -m studio.desktop` (pythonw has no console). This starts the
ClipKontrast server hidden, with its output in data/logs/clipkontrast.log, and opens ClipKontrast in a window of its
own: Microsoft Edge's app mode (no address bar or tabs; Edge comes with every Windows 10 and 11), or Chrome's, with a
separate profile so it never mixes with the person's own browsing. Closing that window stops ClipKontrast.

It also does what the console launcher (ClipKontrast.cmd, kept for troubleshooting) did: swaps in an update that was
downloaded (app.new) and starts again, or runs the downloaded installer. See studio/selfupdate.py.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

INSTALL = Path(__file__).resolve().parents[2]           # <install>\app\studio\desktop.py
APP = INSTALL / "app"
DATA = INSTALL / "data"
PORT = int(os.environ.get("CLIPKONTRAST_PORT") or 8765)
URL = f"http://127.0.0.1:{PORT}/app"
LOG = DATA / "logs" / "clipkontrast.log"
RESTART_CODE, INSTALLER_CODE = 75, 76                     # the same as studio/selfupdate.py
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _env() -> dict:
    env = dict(os.environ)
    env.update({"CLIPKONTRAST_INSTALLED": "1", "CLIPKONTRAST_INSTALL_DIR": str(INSTALL),
                "CLIPKONTRAST_DEFAULT_DATA": str(DATA), "CLIPKONTRAST_STORAGE_FILE": str(INSTALL / "storage.json"),
                "CLIPKONTRAST_AUTO_RELOAD": "0", "CLIPKONTRAST_OPEN_BROWSER": "0", "PYTHONUTF8": "1",
                "PYTHONUNBUFFERED": "1", "PYTHONWARNINGS": "ignore::DeprecationWarning"})
    env["PATH"] = os.pathsep.join([str(INSTALL / "ffmpeg" / "bin"), str(INSTALL / "python"),
                                   str(INSTALL / "python" / "Scripts"), env.get("PATH", "")])
    return env


def _message(text: str, error: bool = False):
    """A plain Windows message box (there is no console to print to)."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "ClipKontrast", 0x10 if error else 0x40)
    else:
        print(text)


def _tail(lines: int = 12) -> str:
    try:
        return "\n".join(LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def _up() -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/healthz", timeout=2)
        return True
    except Exception:  # noqa: BLE001
        return False


def _swap():
    """An update downloaded while ClipKontrast ran: put the new code in place (the old one kept aside)."""
    new, old = INSTALL / "app.new", INSTALL / "app.old"
    if (new / "studio" / "server.py").is_file():
        try:
            if old.exists():
                shutil.rmtree(old, ignore_errors=True)
            APP.rename(old)
            new.rename(APP)
        except OSError:
            pass
    if not (APP / "studio" / "server.py").is_file() and (old / "studio" / "server.py").is_file():
        shutil.rmtree(APP, ignore_errors=True)     # the swap couldn't finish: the old code goes back
        old.rename(APP)


def _browser():
    """Microsoft Edge or Google Chrome, which can show a page as an app window."""
    roots = [os.environ.get(k, "") for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
        for r in roots:
            if r and Path(r, rel).is_file():
                return str(Path(r, rel))
    return shutil.which("msedge") or shutil.which("chrome")


def _open_window(url: str):
    """ClipKontrast's own window. Returns its process (to know when it is closed), or None if none could be opened."""
    fake = os.environ.get("CLIPKONTRAST_WINDOW_CMD")         # the build's test stands in a process for the window
    if fake:
        return subprocess.Popen(fake, creationflags=NO_WINDOW)
    exe = _browser()
    if not exe:
        return None
    profile = DATA / "window"
    profile.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
                             "--no-default-browser-check", "--window-size=1380,880", "--hide-crash-restore-bubble",
                             "--disable-features=Translate"])


def _start_server():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if LOG.is_file() and LOG.stat().st_size > 5_000_000:
        LOG.replace(LOG.with_suffix(".old.log"))
    out = open(LOG, "a", encoding="utf-8", errors="replace")
    out.write(f"\n---- ClipKontrast starting {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    out.flush()
    py = INSTALL / "python" / "python.exe"
    return subprocess.Popen([str(py if py.is_file() else sys.executable), "-m", "studio.server"], cwd=str(INSTALL),
                            env=_env(), stdout=out, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)


def _stop(p):
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(15)
        except subprocess.TimeoutExpired:
            p.kill()


def main():
    if _up():                      # already running (the icon was clicked again): just open its window
        if not _open_window(URL):
            webbrowser.open(URL)
        return
    window = None
    while True:
        _swap()
        server = _start_server()
        began = time.time()
        while not _up() and server.poll() is None and time.time() - began < 600:
            time.sleep(0.5)
        if server.poll() is not None and server.returncode not in (RESTART_CODE, INSTALLER_CODE):
            _message("ClipKontrast couldn't start.\n\n" + _tail(), error=True)
            return
        if window is None and server.poll() is None:
            window = _open_window(URL)
            if window is None:     # no Edge or Chrome: the usual browser, and this box to close ClipKontrast
                webbrowser.open(URL)
                _message("ClipKontrast is open in your browser.\n\nPress OK when you're done to close ClipKontrast.")
                _stop(server)
                return
        while server.poll() is None:
            if window and window.poll() is not None:   # the window was closed: ClipKontrast closes with it
                _stop(server)
                return
            time.sleep(0.5)
        code = server.returncode
        if code == RESTART_CODE:   # updated: the new code is swapped in, and the open window reconnects by itself
            continue
        if code == INSTALLER_CODE:
            setup = INSTALL / "update" / "ClipKontrast-Setup.exe"
            _stop(window)
            subprocess.Popen([str(setup), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
            return
        _stop(window)
        _message("ClipKontrast stopped unexpectedly.\n\n" + _tail(), error=True)
        return


if __name__ == "__main__":
    main()
