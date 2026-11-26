"""The app's pages in a real browser: a throwaway copy of ClipKontrast with one finished video and a made clip
(tests/editor_seed.py); Home, the Editor page, the Library page and Hype Edit all (tests/app_ui.cjs).
Usage: test_app_ui.py <project root>"""
import os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
PORT = 8824
BASE = f"http://127.0.0.1:{PORT}"
data = tempfile.mkdtemp(prefix="ck-app-ui-")
src = Path(data) / "source.mp4"
# a stand-in stream: moving picture and a tone, 40 seconds, landscape like a stream
# (the sound has loud bursts, like a streamer's reactions, so Hype Edit has moments to find)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=40", "-f", "lavfi", "-i",
                "aevalsrc='0.08*sin(2*PI*220*t)*(1+9*gt(mod(t\\,7)\\,5.6))':d=40:s=44100", "-shortest", "-c:v", "libx264",
                "-preset", "ultrafast", "-c:a", "aac", str(src)], check=True)
env = {**os.environ, "CLIPKONTRAST_DATA": data, "DATABASE_URL": "", "CLIPKONTRAST_ACCOUNTS": "0", "CLIPKONTRAST_FETCH_MODEL": "0",
       "CLIPKONTRAST_WHISPER": "0", "CLIPKONTRAST_UPDATE_CHECK": "0", "CLIPKONTRAST_AUTO_RELOAD": "0", "CLIPKONTRAST_OPEN_BROWSER": "0"}
subprocess.run([sys.executable, "tests/editor_seed.py", str(src)], cwd=ROOT, check=True, env=env)
srv = subprocess.Popen([sys.executable, "-m", "studio.server"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       env={**env, "CLIPKONTRAST_PORT": str(PORT)})
try:
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/healthz", timeout=2)
            break
        except Exception:
            time.sleep(1)
    shots = os.environ.get("CK_SHOTS") or tempfile.mkdtemp(prefix="ck-app-shots-")
    # files to add to the library, the way a person would: a font, a sound, a picture and a short video
    lib = Path(tempfile.mkdtemp(prefix="ck-app-lib-"))
    import shutil
    shutil.copyfile(Path(ROOT) / "studio" / "fonts" / "Bangers-Regular.ttf", lib / "font.ttf")
    for args, name in [(["-f", "lavfi", "-i", "sine=f=660:d=0.8"], "boing.wav"),
                       (["-f", "lavfi", "-i", "color=c=red:s=400x300", "-frames:v", "1"], "meme.png"),
                       (["-f", "lavfi", "-i", "testsrc=s=320x240:r=30:d=3", "-f", "lavfi", "-i", "sine=f=900:d=3", "-shortest",
                         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac"], "reaction.mp4")]:
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args, str(lib / name)], check=True)
    r = subprocess.run(["node", "tests/app_ui.cjs", BASE, shots, str(lib)], cwd=ROOT, timeout=900)
    print(f"  screenshots: {shots}")
    code = r.returncode
finally:
    srv.terminate()
    try:
        srv.wait(10)
    except subprocess.TimeoutExpired:
        srv.kill()
sys.exit(code)
