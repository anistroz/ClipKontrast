"""The errors people hit on a fresh install: ffmpeg not found ("[WinError 2]"), the speech model not downloaded,
and an AI model name the service does not know. Runs against the code directly; nothing is downloaded."""
import io, os, shutil, sys, tarfile, tempfile
from pathlib import Path
os.environ["CLIPKONTRAST_DATA"] = tempfile.mkdtemp(prefix="pc-tools-"); os.environ["DATABASE_URL"] = ""
os.environ.pop("CLIPKONTRAST_MODELS", None)          # this test makes and removes a model: only ever inside its own folder
os.environ.update(CLIPKONTRAST_AI_PROVIDER="gemini", CLIPKONTRAST_AI_MODELS="gemini-old", CLIPKONTRAST_AI_KEY="test-key-123456")
sys.path.insert(0, ".")
from studio import ai, config, fetch_model, safe, tools
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

# ---- ffmpeg
real_path = os.environ.get("PATH", "")
exe = ".exe" if sys.platform == "win32" else ""
hidden = tempfile.mkdtemp(prefix="pc-ff-")
for name in tools.NEEDED:
    f = Path(hidden) / (name + exe); f.write_bytes(b"x"); f.chmod(0o755)
os.environ["PATH"] = tempfile.mkdtemp(prefix="pc-empty-")            # a PATH with no ffmpeg on it
real_places = tools._places
tools._places = lambda: []
check("with ffmpeg nowhere, both programs are reported missing", tools.setup(), ["ffmpeg", "ffprobe"])
err = FileNotFoundError(2, "The system cannot find the file specified")
check("the bare Windows error becomes what to do about it", "ffmpeg" in safe.friendly(err) and "install" in safe.friendly(err), True)
check("...also when it arrives as text", "ffmpeg" in safe.friendly(RuntimeError("[WinError 2] The system cannot find the file specified")), True)
check("an unrelated error is left as it is", safe.friendly(ValueError("That link is a playlist.")), "That link is a playlist.")
tools._places = lambda: [Path(hidden)]
check("installed but not on the PATH yet: found in its folder and used from there", (tools.setup(), bool(shutil.which("ffmpeg"))), ([], True))
os.environ["PATH"] = real_path
os.environ["CLIPKONTRAST_FFMPEG_DIR"] = hidden
tools._places = real_places
check("CLIPKONTRAST_FFMPEG_DIR is looked in first", tools._places()[0], Path(hidden))
tools.setup()

# ---- the speech model
import httpx, ssl as _ssl
d = config.ASR_MODEL_DIR
assert str(d).startswith(os.environ["CLIPKONTRAST_DATA"]), "the test must only touch its own folder"
check("no model to begin with", fetch_model.ready(), False)
d.mkdir(parents=True); (d / "tokens.txt").write_text("a 1")
check("half a model (a download that was cut off) does not count", fetch_model.ready(), False)
shutil.rmtree(d)
NAMES = ("tokens.txt", "encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx")
def packed():
    buf = tempfile.mkdtemp(prefix="pc-tar-")
    src = Path(buf) / config.ASR_MODEL_NAME; src.mkdir()
    for n in NAMES:
        (src / n).write_bytes(os.urandom(40000))          # random: bz2 can't shrink it, so the download has some size
    b = io.BytesIO()
    with tarfile.open(fileobj=b, mode="w:bz2") as t:
        t.add(src, arcname=config.ASR_MODEL_NAME)
    return b.getvalue()
TAR = packed()
net = {"github": "ok", "hf": "ok", "cut": 0, "asked": [], "certs": []}
def handler(req):
    url, rng = str(req.url), req.headers.get("range", "")
    net["asked"].append((url.split("/")[2], rng))
    side = "github" if "github.com" in url else "hf"
    if net[side] == "down":
        raise httpx.ConnectError("getaddrinfo failed")
    if net[side] == "cert":
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate")
    if net[side] == "404":
        return httpx.Response(404)
    body = TAR if side == "github" else b"model file " + url.rsplit("/", 1)[1].encode()
    start = int(rng.split("=")[1].split("-")[0]) if rng else 0
    rest = body[start:]
    if net["cut"]:                                         # the connection drops part way: half the bytes, then nothing
        net["cut"] -= 1
        return httpx.Response(206 if start else 200, headers={"content-length": str(len(rest))}, content=rest[:len(rest) // 2])
    return httpx.Response(206 if start else 200, headers={"content-length": str(len(rest))}, content=rest)
def fake_client(windows_certs=False):
    net["certs"].append(windows_certs)
    if windows_certs and net["github"] == "cert":
        net["github"] = "ok"                               # Windows' own list trusts what the antivirus put in the way
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
fetch_model._client = fake_client
fetch_model.time.sleep = lambda s: None
def run():
    try:
        fetch_model.ensure(); return ""
    except RuntimeError as e:
        return str(e)
def leftovers():
    return sorted(p.name for p in config.MODELS_DIR.iterdir() if p.name != config.ASR_MODEL_NAME)
def reset():
    shutil.rmtree(config.MODELS_DIR, ignore_errors=True); net.update(github="ok", hf="ok", cut=0, asked=[], certs=[])

said = run()
check("the model is downloaded by itself and put in place whole", (said, fetch_model.ready(), sorted(p.name for p in d.iterdir())),
      ("", True, sorted(NAMES)))
check("nothing is left over from the download", leftovers(), [])

reset(); net["cut"] = 1
seen = []
said = run()
check("a connection that drops part way carries on from where it stopped", (said, fetch_model.ready()), ("", True))
check("...asking only for the rest, not starting again", [r for h, r in net["asked"]], ["", f"bytes={len(TAR) // 2}-"])

reset(); net.update(cut=99)
said = run()
check("cut off every time: said in plain words", ("cut off" in said and "carries on" in said, fetch_model.ready()), (True, False))
kept = (config.MODELS_DIR / "speech-model.tar.bz2").stat().st_size
check("...and what was downloaded is kept for next time", kept > 0)
net.update(cut=0, asked=[])
check("the next try carries on from there and finishes", (run(), fetch_model.ready(), net["asked"][0][1]), ("", True, f"bytes={kept}-"))

reset(); net["github"] = "down"
said = run()
check("GitHub can't be reached: the model comes from Hugging Face instead", (said, fetch_model.ready(), sorted(p.name for p in d.iterdir())),
      ("", True, sorted(NAMES)))
check("...each of its files", (d / "encoder.int8.onnx").read_bytes(), b"model file encoder.int8.onnx")
check("...and nothing is left over", leftovers(), [])

reset(); net.update(github="cert")
said = run()
check("a certificate problem (an antivirus checking connections): tried again with Windows' own list, and it works",
      (said, fetch_model.ready(), True in net["certs"]), ("", True, True))

reset(); net.update(github="down", hf="down")
said = run()
check("no internet at all: said in plain words, and no half model left behind",
      ("internet" in said, fetch_model.ready(), d.exists()), (True, False, False))
check("...without saying the same thing twice", said.count("Check the internet connection"), 1)

reset()
real_usage = fetch_model.shutil.disk_usage
fetch_model.shutil.disk_usage = lambda p: type("U", (), {"free": 300 * 1024 * 1024})()
said = run()
fetch_model.shutil.disk_usage = real_usage
check("a nearly full drive: said before downloading anything", ("Free up" in said, net["asked"]), (True, []))

reset(); net.update(github="404")
check("the file moved on GitHub: Hugging Face, without asking GitHub four times",
      (run(), fetch_model.ready(), sum(1 for h, r in net["asked"] if "github" in h)), ("", True, 1))

# ---- the app's window while ClipKontrast starts: says what it's really doing
from studio import desktop
desktop.LOG.parent.mkdir(parents=True, exist_ok=True)
desktop.LOG.write_text("\n---- ClipKontrast starting 2026-11-19 13:58:23\n  Moving ClipKontrast's folder to D:\\old (2 things). x\n  Moved.\n"
                       "\n---- ClipKontrast starting 2026-11-20 13:04:53\n  Moving ClipKontrast's folder to D:\\clipkontrast (12 things). x\n"
                       "  Moved 5 of 12: jobs\n", encoding="utf-8")
text, moving = desktop._starting()
check("moving the folder to another drive: the window says so, and how far it has got (not 'downloading')",
      (moving, "D:\\clipkontrast" in text, "Moved 5 of 12" in text, "download" in text.lower()), (True, True, True, False))
desktop.LOG.write_text(desktop.LOG.read_text() + "  Moved.\n")
check("once moved, it's just starting", desktop._starting()[1], False)

# ---- the AI
check("an unknown model name", ai.explain("HTTP 404 models/gemini-old is not found for API version v1beta"), lambda s: "gemini-old" in s and "Find models" in s)
check("a refused key", ai.explain("HTTP 400 API key not valid. Please pass a valid API key."), lambda s: "refused the key" in s)
check("out of quota", ai.explain("HTTP 429 You exceeded your current quota"), lambda s: "limit" in s)
check("cannot be reached", ai.explain("[Errno 11001] getaddrinfo failed"), lambda s: "couldn't reach" in s)
check("anything else is not guessed at", ai.explain("something odd"), "")
ai.note_problem("HTTP 404 model not found")
check("the reason is kept for the dashboard, and cleared when the AI answers again", (bool(ai.problem["text"]), (ai.clear_problem(), ai.problem["text"])[1]), (True, ""))

print("ALL PASSED" if not fails else f"{len(fails)} failed")
shutil.rmtree(os.environ["CLIPKONTRAST_DATA"], ignore_errors=True); shutil.rmtree(hidden, ignore_errors=True)
sys.exit(1 if fails else 0)
