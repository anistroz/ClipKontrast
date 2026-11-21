"""The speech-to-text model: downloaded once, by itself, the first time it is needed.

Nothing has to be run by hand. (python -m studio.fetch_model still works, for getting it ahead of time.) It is
about 480 MB, so the download is made to survive real home internet:

- it gives up on a connection that stops sending (instead of waiting forever) and tries again;
- a download that was cut off carries on from where it stopped, also after ClipKontrast is restarted;
- if GitHub can't be reached, the same model comes from Hugging Face instead;
- it uses its own list of trusted certificates (a fresh Windows often lacks the one GitHub's downloads need), and
  falls back to Windows' own list for antivirus programs that check secure connections.

It is unpacked next to where it will live and moved into place only when it is whole, so a half download can never
be mistaken for the model."""
import shutil
import ssl
import tarfile
import threading
import time
import urllib.request

from . import config

URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{config.ASR_MODEL_NAME}.tar.bz2"
# The same model, as separate files (not packed), on Hugging Face.
HF = f"https://huggingface.co/csukuangfj/{config.ASR_MODEL_NAME}/resolve/main/"
HF_FILES = ("tokens.txt", "decoder.int8.onnx", "joiner.int8.onnx", "encoder.int8.onnx")
NEED_FREE = 1300 * 1024 * 1024       # the packed download and the unpacked model, side by side for a moment
TRIES = 4
UA = {"User-Agent": "ClipKontrast"}
_lock = threading.Lock()
state = {"doing": False, "percent": 0, "error": ""}


def ready() -> bool:
    """Is the whole model there: the word list and all three parts?"""
    d = config.ASR_MODEL_DIR
    if not (d / "tokens.txt").is_file():
        return False
    return all(any(d.glob(f"{part}*.onnx")) for part in ("encoder", "decoder", "joiner"))


class Problem(Exception):
    """A reason the person can act on."""


def _why(e: BaseException) -> str:
    """What went wrong, in words someone without a technical background can act on."""
    import httpx
    t = f"{type(e).__name__}: {e}"
    if isinstance(e, Problem):
        return str(e)
    if isinstance(e, OSError) and getattr(e, "errno", None) == 28 or "No space left" in t or "disk is full" in t.lower():
        return "The drive is full. Free up about 1.5 GB and try again."
    if isinstance(e, PermissionError):
        return "Windows didn't let ClipKontrast write its files (an antivirus may be blocking it)."
    if "CERTIFICATE" in t.upper() or isinstance(e, ssl.SSLError):
        return ("The secure connection was refused (an antivirus or office network that checks secure connections can "
                "cause this).")
    if isinstance(e, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
        return "The internet connection was too slow or stopped."
    if isinstance(e, httpx.ConnectError):
        return "Couldn't connect to the download server. Check the internet connection."
    if isinstance(e, httpx.HTTPStatusError):
        return f"The download server answered {e.response.status_code}."
    if isinstance(e, (httpx.RemoteProtocolError, httpx.ReadError)):
        return "The connection was cut off in the middle."
    return t[:160]


def _proxy():
    """Windows' own proxy setting, if there is one (httpx only reads the HTTPS_PROXY variable by itself)."""
    try:
        p = urllib.request.getproxies()
        return p.get("https") or p.get("http") or None
    except Exception:  # noqa: BLE001
        return None


def _client(windows_certs: bool = False):
    import httpx
    verify = ssl.create_default_context() if windows_certs else True       # True: httpx's own list (certifi)
    return httpx.Client(headers=UA, timeout=httpx.Timeout(60, connect=20), follow_redirects=True, verify=verify,
                        proxy=_proxy())


def _download(url: str, dest, share: tuple = (0, 100), progress: dict = None) -> None:
    """Fetch `url` into `dest`, carrying on from what is already in `dest`. Tries again a few times, then raises.
    `share` is the part of the progress bar this file fills; `progress` the dict whose "percent" it fills (the speech
    model's own, unless another download says otherwise)."""
    progress = state if progress is None else progress
    import httpx
    last = None
    windows_certs = False
    for attempt in range(TRIES):
        if attempt:
            time.sleep(min(20, 3 * attempt))
        have = dest.stat().st_size if dest.exists() else 0
        try:
            with _client(windows_certs) as c, c.stream("GET", url, headers={"Range": f"bytes={have}-"} if have else {}) as r:
                if r.status_code == 416:                 # already whole
                    return
                r.raise_for_status()
                if have and r.status_code != 206:        # the server started again from the start
                    have = 0
                total = have + int(r.headers.get("content-length") or 0)
                with open(dest, "ab" if have else "wb") as f:
                    got = have
                    for chunk in r.iter_bytes(1024 * 1024):
                        f.write(chunk)
                        got += len(chunk)
                        if total:
                            progress["percent"] = min(99, int(share[0] + (share[1] - share[0]) * got / total))
                if total and got < total:
                    raise httpx.RemoteProtocolError("ended early")
                return
        except Exception as e:  # noqa: BLE001
            last = e
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (403, 404):
                break                                    # not there: no point asking again
            if ("CERTIFICATE" in str(e).upper() or isinstance(e, ssl.SSLError)) and not windows_certs:
                windows_certs = True                     # an antivirus that checks secure connections: use Windows' list
            if isinstance(e, OSError) and not isinstance(e, (httpx.HTTPError, ssl.SSLError)):
                break                                    # the drive, not the internet
    raise last


def _from_github(part):
    tmp = config.MODELS_DIR / "speech-model.tar.bz2"     # kept if cut off, so the next try carries on
    _download(URL, tmp, (0, 90))
    try:
        with tarfile.open(tmp, "r:bz2") as t:
            for m in t.getmembers():  # only plain files and folders that stay inside the unpacking folder
                if (m.isfile() or m.isdir()) and not m.name.startswith(("/", "..")) and ".." not in m.name.split("/"):
                    t.extract(m, part)
    except (tarfile.TarError, EOFError, OSError) as e:
        tmp.unlink(missing_ok=True)                      # a broken download: next time from the start
        if isinstance(e, OSError) and getattr(e, "errno", None) == 28:
            raise
        raise Problem("The download was damaged. It will be downloaded again.") from e
    tmp.unlink(missing_ok=True)
    got = part / config.ASR_MODEL_NAME
    if not got.is_dir():
        raise Problem("The download did not contain the model.")
    return got


def _from_huggingface(part):
    got = part / config.ASR_MODEL_NAME
    got.mkdir(parents=True, exist_ok=True)
    held = config.MODELS_DIR / "speech-model.hf"         # the files fetched so far, kept if cut off
    held.mkdir(exist_ok=True)
    shares = {"tokens.txt": (0, 1), "decoder.int8.onnx": (1, 3), "joiner.int8.onnx": (3, 4), "encoder.int8.onnx": (4, 99)}
    for name in HF_FILES:
        _download(HF + name, held / name, shares[name])
    for name in HF_FILES:
        shutil.copyfile(held / name, got / name)
    return got


def _wait_for(on_progress) -> bool:
    """Take the lock, telling `on_progress` how far the download another part of ClipKontrast started has got."""
    while not _lock.acquire(timeout=2):
        if on_progress and state["doing"]:
            on_progress(state["percent"])
    return True


def ensure(on_progress=None) -> None:
    """Make sure the model is on this computer, downloading it if it is not. One download at a time: anything else
    that needs the model meanwhile waits for it here (and hears how far it has got through `on_progress`)."""
    if ready():
        return
    _wait_for(on_progress)
    try:
        if ready():
            return
        state.update(doing=True, percent=0, error="")
        print("\n  Downloading the speech model (one time, about 480 MB)...\n", flush=True)
        config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
        part = config.MODELS_DIR / "speech-model.unpacking"
        reasons = []
        try:
            free = shutil.disk_usage(config.MODELS_DIR).free
            if free < NEED_FREE:
                raise Problem(f"The drive has only {free / 1e9:.1f} GB free. Free up about 1.5 GB and try again.")
            for name, source in (("GitHub", _from_github), ("Hugging Face", _from_huggingface)):
                shutil.rmtree(part, ignore_errors=True)
                part.mkdir()
                try:
                    got = source(part)
                except Exception as e:  # noqa: BLE001
                    reasons.append(f"{name}: {_why(e)}")
                    print(f"  Speech model from {name} didn't work: {type(e).__name__}: {str(e)[:200]}", flush=True)
                    if _why(e).startswith(("The drive", "Windows didn't")):
                        break                            # trying another server won't help
                    continue
                shutil.rmtree(config.ASR_MODEL_DIR, ignore_errors=True)        # a half-finished one from before
                got.rename(config.ASR_MODEL_DIR)
                shutil.rmtree(config.MODELS_DIR / "speech-model.hf", ignore_errors=True)
                print("  Speech model ready.\n", flush=True)
                return
            raise Problem(" ".join(dict.fromkeys(r.split(": ", 1)[1] for r in reasons)) if reasons else "unknown")
        except Exception as e:  # noqa: BLE001
            why = _why(e)
            state["error"] = why
            raise RuntimeError("ClipKontrast couldn't download its speech model (about 480 MB, needed once). " + why +
                               " What was downloaded is kept: make the clips again and it carries on from there.") from e
        finally:
            state["doing"] = False
            shutil.rmtree(part, ignore_errors=True)
    finally:
        _lock.release()


def main():
    if ready():
        print("Speech model already present.")
        return
    ensure()


if __name__ == "__main__":
    main()
