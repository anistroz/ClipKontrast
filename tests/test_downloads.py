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
        out.write_bytes(b"v" * 4096)


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
    seen.clear(); FakeYDL.fail_first = 99
    try:
        media.download_section("https://www.youtube.com/watch?v=abcdefghijk", d, "clip02.src", 0, 30)
        check("when every way fails, it says so", False)
    except RuntimeError as e:
        msg = str(e)
        check("when every way fails, the reason is kept, without colour codes",
              ("3199971767" in msg, "\x1b" not in msg, "fragment 3 not found" in msg), (True, True, True))
        check("every one of YouTube's apps was asked, each for every kind of file", len(seen), len(media.YT_CLIENTS) * 3)


class AudioYDL:
    """YouTube's default answer gives an empty file; asked as the Android VR app, it gives the sound."""
    def __init__(self, opts):
        self.opts = opts
        seen.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def download(self, urls):
        out = Path(self.opts["outtmpl"].replace("%(ext)s", "m4a"))
        client = (self.opts.get("extractor_args") or {}).get("youtube", {}).get("player_client")
        out.write_bytes(b"x" * 4096 if client == ["android_vr"] else b"")


url = "https://www.youtube.com/watch?v=zzzzzzzzzzz"
with patch.object(yt_dlp, "YoutubeDL", AudioYDL):
    seen.clear()
    got = media.download_audio(url, d)
    check("an empty download is tried again as another of YouTube's apps", (got.stat().st_size, len(seen)), (4096, 2))
    seen.clear()
    media.download_audio(url, d)
    check("the app that worked is asked first next time", (len(seen), seen[0]["extractor_args"]["youtube"]["player_client"]), (1, ["android_vr"]))
    seen.clear()
    try:
        media.download_audio("https://www.twitch.tv/videos/123", d)
    except RuntimeError as e:
        check("other sites are asked once, and an empty file says so", (len(seen), "empty" in str(e)), (1, True))

# ---- a fetched piece that doesn't hold its clip's moment is fetched again, never sent to the encoder empty
from studio import jobs
job = {"source": {"type": "url", "url": "https://www.youtube.com/watch?v=abcdefghijk"}, "dir": str(d), "duration": 9000,
       "options": {"quality": 720}, "width": 1280, "height": 720}
ok_clip = {"id": "c1", "start": 7210.0, "end": 7240.0, "src": str(d / "c1.mp4"), "src_offset": 7200.0}
with patch.object(media, "probe", return_value={"duration": 48.0, "width": 1280, "height": 720}):
    src_, meta = jobs._clip_source(job, dict(ok_clip))
    check("a piece that holds the clip is used as it is", (src_.name, meta["width"]), ("c1.mp4", 1280))
bad = dict(ok_clip, src_offset=7300.0)          # the piece starts after the clip ends
refetched = []


def again(job_, clip_):
    refetched.append(clip_["id"])
    clip_.update(src=str(d / "c1b.mp4"), src_offset=7202.0)


with patch.object(media, "probe", return_value={"duration": 48.0, "width": 640, "height": 360}), \
        patch.object(jobs, "_piece_again", side_effect=again):
    src_, meta = jobs._clip_source(job, bad)
    check("a piece that misses the clip is fetched again, cut at the clip's time", (refetched, src_.name, meta["width"]), (["c1"], "c1b.mp4", 640))
with patch.object(media, "probe", return_value={"duration": 2.0, "width": 640, "height": 360}), \
        patch.object(jobs, "_piece_again", side_effect=lambda j, c: c.update(src=str(d / "c1c.mp4"), src_offset=7300.0)):
    try:
        jobs._clip_source(job, dict(bad))
        check("still missing: the clip says so plainly", False)
    except RuntimeError as e:
        check("still missing: the clip says so plainly", "re-make" in str(e))

if fails:
    print(f"{len(fails)} FAILED"); sys.exit(1)
print("ALL PASSED")
