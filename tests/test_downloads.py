"""Fetching one stretch of a long YouTube video: the JavaScript runtime is given to yt-dlp, and when one way of
fetching fails the next is tried, with a readable reason if all of them fail. yt-dlp is replaced by a stand-in.

Runs against the code directly, with its own empty data folder."""
import os, sys, tempfile
from pathlib import Path
from unittest.mock import patch
os.environ["CLIPKONTRAST_DATA"] = tempfile.mkdtemp(prefix="pc-dl-")
sys.path.insert(0, ".")
import yt_dlp
from studio import media
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


seen = []


class FakeYDL:
    fail_first = 2

    def __init__(self, opts):
        self.opts = opts
        seen.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def download(self, urls):
        out = Path(self.opts["outtmpl"].replace("%(ext)s", "mp4"))
        if len(seen) <= FakeYDL.fail_first:
            out.with_suffix(".mp4.part").write_bytes(b"half")
            self.opts["logger"].warning("\x1b[0;33mWARNING:\x1b[0m fragment 3 not found")
            raise yt_dlp.utils.DownloadError("\x1b[0;31mERROR:\x1b[0m ffmpeg exited with code 3199971767")
        out.write_bytes(b"video")


rt = media._js_runtimes()
check("a JavaScript runtime (Deno) is found for YouTube", bool(rt.get("deno", {}).get("path")))
d = Path(tempfile.mkdtemp())
with patch.object(yt_dlp, "YoutubeDL", FakeYDL):
    got = media.download_section("https://www.youtube.com/watch?v=abcdefghijk", d, "clip01.src", 7200, 7230)
    check("after two failed ways, the third fetches the stretch", (got.name, len(seen)), ("clip01.src.mp4", 3))
    check("each try asks for a different kind of file", len({o["format"] for o in seen}), 3)
    check("the streaming (HLS) version is the second try", "m3u8" in seen[1]["format"])
    check("Deno is handed to yt-dlp every time", all(o.get("js_runtimes") == rt for o in seen))
    check("nothing half-written is left", sorted(p.name for p in d.iterdir()), ["clip01.src.mp4"])
    seen.clear(); FakeYDL.fail_first = 9
    try:
        media.download_section("https://www.youtube.com/watch?v=abcdefghijk", d, "clip02.src", 0, 30)
        check("when every way fails, it says so", False)
    except RuntimeError as e:
        msg = str(e)
        check("when every way fails, the reason is kept, without colour codes",
              ("3199971767" in msg, "\x1b" not in msg, "fragment 3 not found" in msg), (True, True, True))

if fails:
    print(f"{len(fails)} FAILED"); sys.exit(1)
print("ALL PASSED")
