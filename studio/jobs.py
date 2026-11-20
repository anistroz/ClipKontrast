"""Job pipeline: get video -> audio -> transcript -> AI picks -> rendered clips. One heavy task at a time."""
import collections
import json
import os
import math
import queue
import re
import shutil
import threading
import time
import traceback
import uuid

import numpy as np
from pathlib import Path

from . import brain, config, creators, ctx, facecam, games, load, media, quality, render, roman, safe, transcribe, usage, whisper

class _FairQueue:
    """Whose video is next. Each person has their own line and the lines take turns, so someone who adds ten
    videos does not make everyone else wait behind all ten. Small tasks (re-making one clip) go first."""

    def __init__(self):
        self.cv = threading.Condition()
        self.quick = collections.deque()
        self.lines = {}                       # user -> their waiting videos, oldest first
        self.turn = collections.deque()       # users with something waiting, in the order they will be served
        self.epoch = 0                        # goes up whenever the line moves
        self._pos = (0.0, {})
        self.running = 0                      # videos being worked on right now
        self.last_start = 0.0
        self.held = False                     # videos are waiting only because the machine is near full

    def _room(self) -> bool:
        """May one more video start? One always may. More only while the machine has room, and a few seconds
        after the last one started, so its weight is already showing in the measurements."""
        if self.running == 0:
            return True
        return self.running < config.JOB_WORKERS and time.time() - self.last_start > 6 and not load.busy()

    def done(self):
        with self.cv:
            self.running = max(0, self.running - 1)
            self.cv.notify_all()

    def put(self, item, user=None):
        with self.cv:
            if user is None:
                self.quick.append(item)
            else:
                if user not in self.lines:
                    self.lines[user] = collections.deque()
                    self.turn.append(user)
                self.lines[user].append(item)
            self.epoch += 1
            self.cv.notify()

    def get(self, quick_only=False):
        with self.cv:
            while True:
                if self.quick:
                    self.epoch += 1
                    return self.quick.popleft()
                if not quick_only and self.turn:
                    if self._room():
                        break
                    if not self.held:
                        self.held = True
                        self.epoch += 1
                elif self.held:
                    self.held = False
                    self.epoch += 1
                self.cv.wait(1.0)             # looked at again every second: the line moves the moment there is room
            self.epoch += 1
            self.held = False
            self.running += 1
            self.last_start = time.time()
            user = self.turn.popleft()
            item = self.lines[user].popleft()
            if self.lines[user]:
                self.turn.append(user)
            else:
                del self.lines[user]
            return item

    def ahead(self) -> dict:
        """job id -> how many videos will start before it. Worked out at most once a second."""
        with self.cv:
            if time.time() - self._pos[0] < 1:
                return self._pos[1]
            out, lines, order, n = {}, {u: list(q) for u, q in self.lines.items()}, list(self.turn), 0
            depth = 0
            while order:
                nxt = []
                for u in order:
                    if depth < len(lines[u]):
                        out[lines[u][depth][1]] = n
                        n += 1
                        if depth + 1 < len(lines[u]):
                            nxt.append(u)
                order, depth = nxt, depth + 1
            self._pos = (time.time(), out)
            return out


_q = _FairQueue()
_live_q: "queue.Queue" = queue.Queue()   # live clips never wait behind a long video
_jobs: dict = {}
_by_user: dict = {}                       # user -> {job id: job}: listing one person's videos never scans everyone's
_lock = threading.RLock()
on_clip_ready: list = []   # callbacks (job, clip), run once when a clip first finishes

DEFAULTS = {"max_clips": 6, "min_len": 15, "max_len": 60, "style": "bounce", "layout": "blur", "quality": 720,
            "range_start": None, "range_end": None, "captions": True, "lang": "auto", "caption_lang": "auto",
            "zoom": True, "watermark": ""}
CLIP_LOOK = ("style", "layout", "captions", "zoom", "watermark")     # what each clip carries from its video's settings


def clean_watermark(v) -> str:
    """The clipper's @handle drawn on their clips: plain text, short, nothing that could change the captions."""
    import re as _re
    return _re.sub(r"[\x00-\x1f\x7f{}\\]", "", str(v or "")).strip()[:40]


LIMITS = {"max_clips": (1, 20), "min_len": (5, 120), "max_len": (10, 180), "quality": (360, 1080)}


def clean_options(options) -> dict:
    """Only known settings, each inside its allowed range. Raises ValueError on nonsense."""
    out = {}
    for k, v in (options if isinstance(options, dict) else {}).items():
        if k in ("captions", "zoom"):
            if not isinstance(v, bool):
                raise ValueError("Captions must be on or off." if k == "captions" else "Auto zoom must be on or off.")
            out[k] = v
            continue
        if k == "watermark":
            out[k] = clean_watermark(v)
            continue
        if k not in DEFAULTS or v in ("", None):
            continue
        if k in LIMITS:
            lo, hi = LIMITS[k]
            v = max(lo, min(hi, int(float(v))))
        elif k == "style":
            v = v if v in render.STYLES else DEFAULTS["style"]
        elif k == "layout":
            v = v if v in render.LAYOUTS else DEFAULTS["layout"]
        elif k == "lang":
            v = v if v in whisper.LANGUAGES else "auto"
        elif k == "caption_lang":
            v = v if v in whisper.CAPTION_LANGS else "auto"
        else:                                    # range_start, range_end: seconds into the video
            v = float(v)
            if not math.isfinite(v) or v < 0:
                raise ValueError("That part of the video isn't valid.")
        out[k] = v
    if out.get("range_end") is not None and out["range_end"] <= out.get("range_start", 0):
        raise ValueError("The end of the chosen part must be after its start.")
    return out


def job_dir(jid) -> Path:
    return Path(_jobs[jid]["dir"])


HIDDEN = ("dir", "user", "source_path", "recover")


def public(job) -> dict:
    """What the browser may see: no server paths, no owner id."""
    out = {k: v for k, v in job.items() if k not in HIDDEN}
    out["source"] = {k: v for k, v in job["source"].items() if k != "path"}
    out["clips"] = [{k: v for k, v in c.items() if k not in ("src", "fixed_words", "fixed_for")} for c in job["clips"]]
    ai = job.get("ai") or {}
    out["ai"] = {"tokens": ai.get("tokens", 0), "note": ai.get("note", ""), "used": bool(ai.get("model"))}   # never the model, never raw errors
    if job.get("status") == "queued":
        n = _q.ahead().get(job["id"])
        if n:
            out["stage"] = (f"High demand right now: {n} video{'s' if n != 1 else ''} ahead of yours" if _q.held else
                            f"Waiting in line: {n} video{'s' if n != 1 else ''} ahead of yours")
        elif n == 0 and _q.held:
            out["stage"] = "High demand right now: yours is next"
    return out


def save(job):
    ctx.bump(job.get("user"))
    with _lock:
        d = Path(job["dir"])
        for _ in range(5):
            try:
                text = json.dumps(job, indent=1)
                break
            except RuntimeError:  # changed mid-dump by another thread
                time.sleep(0.05)
        else:
            return
        tmp = d / "job.json.tmp"
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(d / "job.json")


def _set(job, **kw):
    with _lock:
        job.update(kw)
    save(job)


def _remap(path, folder: Path):
    """Paths saved before data moved into per-user folders (or on another machine): find the file by name."""
    if path and not Path(path).exists():
        cand = folder / Path(str(path).replace("\\", "/")).name
        if cand.exists():
            return str(cand)
    return path


def _load_file(f: Path, uid: str):
    try:
        job = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    job.update(dir=str(f.parent), user=uid)
    job.setdefault("kind", "video")
    job.setdefault("creator", None)
    job.setdefault("options", {}).setdefault("captions", True)
    if job.get("source_path"):
        job["source_path"] = _remap(job["source_path"], f.parent)
    if job.get("source", {}).get("path"):
        job["source"]["path"] = _remap(job["source"]["path"], f.parent)
    if job.get("status") in ("queued", "running") and job.get("kind") != "live":
        # Picked up again as soon as the server is back (jobs.start), from the last finished part of the transcript.
        job.update(status="queued", stage="Picking up where it stopped", error=None, resume=True)
    if job.get("status") == "live":
        job.update(status="done", stage="Recording paused by a server update", was_live=True)
    buffered = job.get("kind") == "live" and any((f.parent / "buffer").glob("*.ts"))
    for c in job.get("clips", []):
        c.setdefault("captions", job["options"]["captions"])
        if c.get("src"):
            c["src"] = _remap(c["src"], f.parent / "clips")
        if c.get("status") in ("rendering", "queued"):
            if buffered and not c.get("src"):
                c["status"] = "queued"  # the stream is still on disk: live.recover() finishes these
                job["recover"] = True
            elif job.get("resume"):
                c["status"] = "queued"  # the video is being picked up again: this clip is made then
            elif job.get("kind") != "live" and (f.parent / "words.json").is_file():
                c["status"] = "queued"  # a single clip being re-made: jobs.start() makes it again
                job.setdefault("remake", []).append(c["id"])
            else:
                c.update(status="error", error="Interrupted by a restart. Open it and press Save and re-make.")
    _jobs[job["id"]] = job
    _by_user.setdefault(uid, {})[job["id"]] = job


def load_user(uid: str):
    d = config.USERS_DIR / uid
    for f in list((d / "jobs").glob("*/job.json")) + list((d / "creators").glob("*/*/*/job.json")):
        _load_file(f, uid)


def load_all():
    for d in config.USERS_DIR.iterdir():
        if d.is_dir():
            load_user(d.name)


def all_jobs() -> list:
    """Every user's jobs. Only for background work; never send this to a browser."""
    with _lock:
        return list(_jobs.values())


def list_jobs():
    u = ctx.uid()
    with _lock:
        return sorted((dict(j) for j in _by_user.get(u, {}).values()), key=lambda j: -j["created"])


def get(jid):
    """The job, only if it belongs to whoever this code is running for."""
    job = _jobs.get(jid)
    return job if job and job["user"] == ctx.uid() else None


def busy_count() -> int:
    u = ctx.uid()
    return sum(1 for j in list(_by_user.get(u, {}).values()) if j["kind"] == "video" and j["status"] in ("queued", "running"))


def waiting_total() -> int:
    return sum(1 for j in list(_jobs.values()) if j["kind"] == "video" and j["status"] == "queued")


def queue_epoch() -> int:
    return _q.epoch


def running_now() -> int:
    return _q.running


def create(source: dict, options: dict, enqueue=True, creator=None, kind="video") -> dict:
    jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:10]
    c = creators.get(creator) if creator else None
    if c:
        d = creators.root(c["id"]) / ("live" if kind == "live" else "videos") / jid
        base = {**DEFAULTS, **{k: c[k] for k in ("max_clips", "min_len", "max_len", "style", "layout", "captions", "lang", "caption_lang",
                                                 "zoom", "watermark") if k in c}}
    else:
        d, base, creator = config.user_dir(ctx.uid()) / "jobs" / jid, dict(DEFAULTS), None
    opts = {**base, **clean_options(options)}
    if opts["min_len"] >= opts["max_len"]:
        opts["min_len"] = max(5, opts["max_len"] - 5)
    job = {"id": jid, "user": ctx.uid(), "kind": kind, "creator": creator, "dir": str(d), "created": time.time(), "source": source,
           "options": opts, "status": "queued", "stage": "Waiting", "progress": 0.0,
           "title": source.get("name", ""), "uploader": "", "duration": 0, "clips": [], "error": None, "ai": {}}
    d.mkdir(parents=True)
    with _lock:
        _jobs[jid] = job
        _by_user.setdefault(job["user"], {})[jid] = job
    save(job)
    if enqueue:
        _q.put(("job", jid, None), user=job["user"])
    return job


def enqueue(job):
    save(job)
    _q.put(("job", job["id"], None), user=job["user"])


def submit(fn):
    """Run any heavy task (a render, a cleanup) on the single worker, in order."""
    _q.put(("fn", ctx.bind(fn), None))


def submit_live(fn):
    """Live-stream renders and cleanups: their own worker, so a long video can never hold them up."""
    _live_q.put(ctx.bind(fn))


def _live_worker():
    while True:
        fn = _live_q.get()
        try:
            fn()
        except Exception:  # noqa: BLE001
            traceback.print_exc()


def delete(jid):
    with _lock:
        job = _jobs.pop(jid, None)
        if job:
            _by_user.get(job["user"], {}).pop(jid, None)
    if job:
        ctx.bump(job["user"])
        shutil.rmtree(job["dir"], ignore_errors=True)
    return bool(job)


def request_render(jid, cid, changes: dict):
    job = _jobs[jid]
    clip = next(c for c in job["clips"] if c["id"] == cid)
    new = dict(clip)
    for k in ("captions", "zoom", "watermark"):
        if k in changes:
            new.update(clean_options({k: changes[k]}))
    for k in ("start", "end"):
        if k in changes:
            new[k] = round(float(changes[k]), 2)
    if "src_offset" in clip:  # live clip: can only move inside the saved piece of stream
        new["start"] = max(new["start"], clip["src_offset"])
        new["end"] = min(new["end"], clip["src_end"])
    if not (math.isfinite(new["start"]) and math.isfinite(new["end"])) or new["start"] < 0:
        raise ValueError("Those times aren't valid.")
    if not 3 <= new["end"] - new["start"] <= 180:
        raise ValueError("A clip can be 3 to 180 seconds long.")
    for k in ("hook", "title", "description", "style", "layout"):
        if k in changes:
            new[k] = str(changes[k])[:{"hook": 60, "title": 100, "description": 2000}.get(k, 20)]
    if new.get("style") not in render.STYLES:
        new["style"] = DEFAULTS["style"]
    if new.get("layout") not in render.LAYOUTS:
        new["layout"] = DEFAULTS["layout"]
    clip.update(new, status="queued")
    save(job)
    _q.put(("clip", jid, cid))


def render_one(job, clip, words):
    d = Path(job["dir"])
    clip["status"] = "rendering"
    save(job)
    try:
        if not clip.get("src") and not job.get("source_path"):
            _piece_again(job, clip)
        src, meta = _clip_source(job, clip)
        off = clip.get("src_offset", 0.0) if clip.get("src") else 0.0
        local = dict(clip, start=clip["start"] - off, end=clip["end"] - off, hook=roman.to_roman(clip.get("hook") or ""))
        near = _caption_words(job, clip, words, off) if clip.get("captions", True) else []
        # the size of the file this clip is really cut from (a piece can come in another size than the first one)
        out = render.render_clip(src, d / "clips", clip["id"], local, near, meta["width"] or job["width"],
                                 meta["height"] or job["height"])
        # The layout chosen stays the clip's choice; what was really used is kept beside it, with why if they differ.
        used = out.pop("layout", clip.get("layout"))
        note = ""
        if clip.get("layout") in render.FACECAM_LAYOUTS and used not in render.FACECAM_LAYOUTS:
            note = ("The camera fills the picture in this part of the stream, so the clip is zoomed onto it."
                    if clip.get("camera") == "full" else
                    "No webcam was found in this part of the stream, so the whole picture is shown.")
        clip.update(out, layout_used=used, layout_note=note, status="done", version=clip.get("version", 0) + 1, error=None)
        post = {k: clip[k] for k in ("title", "description", "hashtags", "hook", "start", "end", "score")}
        (d / "clips" / f"{clip['id']}.json").write_text(json.dumps(post, indent=1), encoding="utf-8")
        if clip["version"] == 1:
            clip.setdefault("made_at", time.time())
            creators.log(job["creator"], f"Clip ready (score {clip['score']}): {clip['title'] or clip['hook']}")
            save(job)
            for fn in on_clip_ready:
                try:
                    fn(job, clip)
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
    except Exception as e:  # noqa: BLE001
        clip.update(status="error", error=safe.friendly(e, 400))
        creators.log(job["creator"], f"Clip failed: {safe.friendly(e, 200)}")
    save(job)


def _pick_language(job, o, yt, audio, resuming=False):
    """(the language spoken, YouTube's transcript if it is still the one to use). Sets job["lang"]."""
    want = o.get("lang") or "auto"
    if want != "auto" and yt and yt[1].split("-")[0].lower() != want:
        yt = None                                  # YouTube's transcript is in another language: ours is written
        job["transcript_from"] = "own"
    if want != "auto":
        spoken = want
    elif yt:
        spoken = yt[1]
    elif resuming and job.get("lang"):
        spoken = job["lang"]
    else:
        spoken = _detect_language(job, audio)
    job["lang"] = spoken
    return spoken, yt


def _detect_language(job, audio) -> str:
    """Which language is spoken, told by Whisper from the liveliest half minute. English if it can't tell."""
    try:
        got = whisper.detect(audio, note=lambda t: _set(job, stage=t))
    except Exception:  # noqa: BLE001 - no Whisper: treated as English, as before
        got = None
    if not got:
        return "en"
    lang, _sure = got
    # Spoken Hindi and spoken Urdu sound the same; Whisper often calls Hindi "Urdu" and writes it in Urdu script,
    # which spells badly in Roman letters. A person who really wants Urdu can pick it.
    return "hi" if lang == "ur" else lang


def _caption_words(job, clip, words, off):
    want = (job.get("options") or {}).get("caption_lang")
    if want == "deva":
        # Hindi in its own script, as it was heard: no English fixing and no Roman letters. English words said in
        # it stay in English letters.
        return [dict(w, s=w["s"] - off, e=w["e"] - off) for w in words if clip["start"] - 1 <= w["s"] <= clip["end"] + 1]
    always_en = want == "en"
    span = [round(clip["start"], 2), round(clip["end"], 2), "en3" if always_en else "en2"]      # "en2": captions made always-English
    if clip.get("fixed_for") == span and clip.get("fixed_words") and not any(
            roman.needs_roman(w.get("w", "")) for w in clip["fixed_words"]):
        raw = clip["fixed_words"]          # already tidied for this exact span: no second AI call
    else:
        raw = [w for w in words if clip["start"] - 1 <= w["s"] <= clip["end"] + 1]
        try:
            usage.set_context(job.get("creator"), job.get("title") or "")
            raw = brain.english_captions(raw, job.get("lang") or "", job.get("title") or "",
                                         youtube_english=lambda: _english_part(job, clip), always_english=always_en)
            clip.update(fixed_words=raw, fixed_for=span)
        except Exception:  # noqa: BLE001 - captions still render with the words as heard
            pass
    # the last word on it: whatever was said, nothing is drawn in Hindi or Urdu script
    return [dict(w, s=w["s"] - off, e=w["e"] - off) for w in roman.words(raw)]


CLIP_MINUTES = float(config.env("CLIPKONTRAST_CLIP_MINUTES", "15"))     # the longest one clip may take to make


def _wait_for_clips(job, futures, began, workers):
    """Wait for a video's clips, but not for ever. A clip that hangs (a download that stalls, an encoder that
    freezes) used to keep the whole video "in progress", and no other clip could be re-made. Now it is marked as
    failed after CLIP_MINUTES and the video finishes with the clips that did work."""
    left, given_up = list(futures), 0
    late = "This clip took too long and was stopped. Open it and press Save and re-make to try again."
    while left:
        still = []
        for f, clip in left:
            if f.done():
                f.result()
                continue
            t = began.get(clip["id"])
            if (t and time.time() - t > CLIP_MINUTES * 60) or (not t and given_up >= workers):
                given_up += 1
                clip.update(status="error", error=late)
                creators.log(job["creator"], f"Clip stopped after {CLIP_MINUTES:g} minutes: {clip.get('title') or clip.get('hook') or clip['id']}")
                save(job)
                continue
            still.append((f, clip))
        left = still
        if left:
            time.sleep(1)


def _english_part(job, clip):
    """YouTube's English captions for just this clip, for a video in another language. Fetched once per video."""
    if (job.get("source") or {}).get("type") != "url":
        return None
    f = Path(job["dir"]) / "words_en.json"
    if f.is_file():
        en = json.loads(f.read_text(encoding="utf-8"))
    else:
        try:
            en = media.youtube_english_words(job["source"]["url"]) or []
        except Exception:  # noqa: BLE001 - YouTube often refuses its translations: the AI translates instead
            en = []
        f.write_text(json.dumps(en), encoding="utf-8")       # asked once per video, refused or not
    return [w for w in en if clip["start"] - 0.5 <= w["s"] <= clip["end"] + 0.5]


LONG_VIDEO = 40 * 60   # above this, fetch only the pieces that become clips
PAD = 8                # seconds kept either side of a fetched piece, so clips can be re-trimmed


def _clip_source(job, clip):
    """The file this clip is cut from, and its size. A fetched piece that doesn't hold the clip's moment (YouTube sent
    another stretch, or a short one) used to reach the encoder with nothing to cut ("received no packets"): it is
    fetched again, cut exactly at the clip's time, and only if that still fails does the clip say so."""
    for attempt in (1, 2):
        src = Path(clip["src"]) if clip.get("src") else Path(job["source_path"])
        try:
            meta = media.probe(src)
        except Exception:  # noqa: BLE001 - an unreadable piece is fetched again below; the whole video, as known
            meta = ({"duration": 0, "width": 0, "height": 0} if clip.get("src") else
                    {"duration": job.get("duration") or clip["end"], "width": job.get("width") or 0,
                     "height": job.get("height") or 0})
        off = clip.get("src_offset", 0.0) if clip.get("src") else 0.0
        start, end = clip["start"] - off, min(clip["end"] - off, meta["duration"] or 0)
        if end - start >= 1.0 and start >= -0.5:
            clip["end"] = round(end + off, 2)
            return src, meta
        print(f"  Clip {clip['id']}: its piece doesn't hold its moment (piece {off:.1f}s + {meta['duration']:.1f}s, "
              f"clip {clip['start']:.1f}-{clip['end']:.1f}s); fetching it again", flush=True)
        if attempt == 2 or not clip.get("src"):
            break
        clip.pop("src", None)
        _piece_again(job, clip)
    raise RuntimeError("The part of the video downloaded for this clip doesn't hold its moment. "
                       "Press Save and re-make clip to try again.")


def _piece_again(job, clip):
    """Remaking a clip whose own piece of the video was never fetched (its first try failed) and whose whole video
    is not here: fetch the piece now, cut exactly at the asked time, so no sound matching is needed."""
    src = job.get("source") or {}
    if src.get("type") != "url" or not src.get("url"):
        raise RuntimeError("The original video is no longer here, so this clip can't be made again. Add the video again.")
    d = Path(job["dir"])
    want = max(0.0, clip["start"] - PAD)
    until = clip["end"] + PAD if not job.get("duration") else min(job["duration"], clip["end"] + PAD)
    try:
        piece = media.download_section(src["url"], d / "clips", f"{clip['id']}.src", want, until,
                                       int(job["options"]["quality"]), exact=True)
        meta = media.probe(piece)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Could not fetch this part of the video: {safe.friendly(e, 250)}") from e
    clip.update(src=str(piece), src_offset=round(want, 2), src_end=round(want + meta["duration"], 2))
    clip["end"] = min(clip["end"], clip["src_end"])
    job.setdefault("width", meta["width"])
    job.setdefault("height", meta["height"])


def _fetch_piece(job, clip, full_audio):
    """Long videos: download just this clip's stretch and pin down exactly where it starts."""
    d = Path(job["dir"])
    o = job["options"]
    try:
        want = max(0.0, clip["start"] - PAD)
        piece = media.download_section(job["source"]["url"], d / "clips", f"{clip['id']}.src", want,
                                       min(job["duration"], clip["end"] + PAD), int(o["quality"]))
        wav = d / "clips" / f"{clip['id']}.wav"
        media.extract_audio(piece, wav)
        part = media.load_audio(wav)
        wav.unlink(missing_ok=True)
        meta = media.probe(piece)
        off = media.find_offset(full_audio, part, want)
        clip.update(src=str(piece), src_offset=round(off, 2), src_end=round(off + meta["duration"], 2))
        clip["start"], clip["end"] = max(clip["start"], clip["src_offset"]), min(clip["end"], clip["src_end"])
        job.setdefault("width", meta["width"])
        job.setdefault("height", meta["height"])
    except Exception as e:  # noqa: BLE001
        clip.update(status="error", error=f"Could not fetch this part of the video: {safe.friendly(e, 250)}")


BLOCK = 10 * 60         # long videos are transcribed and clipped one block at a time
SECTION_PAD = 20        # seconds downloaded either side of a part of a long video asked for
PROGRESSIVE_FROM = 20 * 60
SCAN_REGION = 150       # scan mode: seconds of audio listened to around each lively moment
WHISPER_REGION = 90     # ...when Whisper listens (Hindi and other languages), which is slower


def render_workers() -> int:
    """How many clips are made at once. Each one is mostly waiting (its piece downloading, the AI tidying its
    captions) and then one ffmpeg, so a few at a time is quicker on any computer; fewer when memory is short."""
    cpus = os.cpu_count() or 4
    n = max(2, min(6, (cpus + 1) // 3))
    ram = getattr(transcribe, "RAM_GB", 0) or 0
    if ram and ram < 8:
        n = 2
    return n


def _mmss(t: float) -> str:
    t = max(0, int(t))
    return f"{t // 60}:{t % 60:02d}"
SCAN_SLICE = 15 * 60    # scan mode: every slice this long gets at least its liveliest moment


def _hot_regions(db, max_clips: int, region: int = None, per_clip: int = 3) -> list:
    """Scan mode: the lively parts of a long video, picked from its loudness alone (seconds from its start).

    The liveliest moment of every 15 minutes is taken, so no part of the video is skipped, and then the liveliest
    moments of the whole video until there are about three for every clip wanted. Only these parts are transcribed,
    which is far quicker than the whole video, and the AI then picks the best clips out of all of them at once."""
    region = region or SCAN_REGION
    n = len(db)
    if n < region * 2:
        return [(0, n)]
    z = brain.loud_zscore(np.asarray(db, dtype=np.float32))
    k = 20                                              # how lively the 20 seconds around each second are
    live = np.convolve(z, np.ones(k) / k, mode="same")
    half = region // 2
    want = max(int(np.ceil(n / SCAN_SLICE)), max_clips * per_clip)
    want = min(want, max(1, int(n * 0.45) // region))      # never more than about half the video
    picked = []

    def free(c):
        return all(abs(c - p) >= region // 2 for p in picked)

    for s in range(0, n, SCAN_SLICE):                  # the liveliest moment of each slice
        part = live[s: s + SCAN_SLICE]
        if len(part) >= 30:
            c = s + int(np.argmax(part))
            if free(c):
                picked.append(c)
    for c in np.argsort(-live):                        # then the liveliest of the whole video
        if len(picked) >= want:
            break
        if free(int(c)):
            picked.append(int(c))
    regions = []
    for c in sorted(picked):
        a, b = max(0, c - half), min(n, c + half)
        if regions and a <= regions[-1][1] + 5:        # touching parts are listened to as one
            regions[-1] = (regions[-1][0], b)
        else:
            regions.append((a, b))
    return regions


def _covers(words: list, start: float, end: float) -> bool:
    """Is a borrowed transcript good enough to find clips with? It has to reach the end of the part being clipped
    and have a normal amount of talking in it; otherwise our own model writes the transcript."""
    inside = [w for w in words if start <= w["s"] <= end]
    minutes = max(0.5, (end - start) / 60)
    return len(inside) >= 25 * minutes and inside[-1]["s"] >= start + 0.85 * (end - start)


def _camera(job, clip):
    """How the streamer's camera shows in this clip: [x, y, w, h] of a webcam box (facecam on top), "full" when the
    camera fills the picture ("just chatting": zoomed onto it), or None (no camera: the whole picture is shown).
    Decided for each clip, because a stream changes: talking to the camera, then a game with the webcam in a corner."""
    path, span = clip.get("src"), None
    if not path:
        path, span = job.get("source_path"), (clip["start"], clip["end"])
    if not path or not Path(path).is_file():
        return None
    try:
        box = facecam.detect(path, ask=brain.look_for_facecam, span=span)
    except Exception:  # noqa: BLE001 - not knowing is not a failure: the whole picture is shown
        return None
    if not box or box.get("conf") != "high":
        return None
    if box.get("full"):
        return "full"
    return [box["x"], box["y"], box["w"], box["h"]]


# ---------------------------------------------------------------- where each streamer's webcam is, remembered
# A streamer's webcam sits in the same place in every clip, stream after stream. Looking for it in one clip alone can
# be fooled (a game character's face in a cutscene, a cinematic bar), so the place found in most clips is remembered
# per channel, and a clip whose own answer disagrees uses the remembered place instead.
CAM_AGREE = 0.5            # how much two boxes must overlap to be the same place


def _iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _cam_key(job) -> str:
    """Whose webcam: the creator's workspace, else the channel the video is from."""
    if job.get("creator"):
        return "creator:" + job["creator"]
    up = re.sub(r"\s+", " ", str(job.get("uploader") or "")).strip().lower()
    return "channel:" + up if up else ""


def _cam_file():
    return config.user_dir(job_user()) / "facecams.json"


def job_user():
    return ctx.uid()


def _cams() -> dict:
    try:
        return json.loads(_cam_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _remembered(job):
    """The remembered webcam box for this job's channel, as fractions of the picture [x, y, w, h], or None."""
    key = _cam_key(job)
    got = _cams().get(key) if key else None
    box = (got or {}).get("box")
    return box if isinstance(box, list) and len(box) == 4 else None


def _remember(job, frac_box, n: int):
    key = _cam_key(job)
    if not key:
        return
    cams = _cams()
    cams[key] = {"box": [round(float(v), 4) for v in frac_box], "seen": int(n), "at": time.time()}
    if len(cams) > 500:                                  # never grows without limit
        for k in sorted(cams, key=lambda k: cams[k].get("at", 0))[:len(cams) - 500]:
            cams.pop(k, None)
    try:
        f = _cam_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(cams), encoding="utf-8")
    except OSError:
        pass


def _frac(box, w, h):
    return [box[0] / w, box[1] / h, box[2] / w, box[3] / h] if w and h else None


def _px(frac, w, h):
    return [int(round(frac[0] * w)), int(round(frac[1] * h)), int(round(frac[2] * w)), int(round(frac[3] * h))]


def _src_size(job, clip):
    """The size of the picture this clip is cut from."""
    path = clip.get("src") or job.get("source_path")
    if clip.get("src_w") and clip.get("src_h"):
        return clip["src_w"], clip["src_h"]
    try:
        meta = media.probe(path)
        return meta.get("width") or job.get("width"), meta.get("height") or job.get("height")
    except Exception:  # noqa: BLE001
        return job.get("width"), job.get("height")


def _learn(job, frac_box):
    """Each clip's own answer is counted; once two clips agree on a place that isn't the remembered one (or none
    is remembered yet), that place is remembered."""
    seen = job.setdefault("cam_seen", [])
    seen.append([round(v, 4) for v in frac_box])
    del seen[:-30]
    agree = [b for b in seen if _iou(b, frac_box) >= CAM_AGREE]
    mem = _remembered(job)
    if len(agree) >= 2 and (not mem or _iou(mem, frac_box) < CAM_AGREE):
        med = [float(np.median([b[i] for b in agree])) for i in range(4)]
        _remember(job, med, len(agree))


def _use_camera(job, clip):
    """Find the camera for a clip with a facecam layout, and note what was found on it. A box that disagrees with
    where this streamer's webcam is remembered to be (or no box at all) gives way to the remembered place."""
    if clip.get("layout") not in render.FACECAM_LAYOUTS:
        return
    cam = _camera(job, clip)
    clip.pop("facecam", None)
    w, h = _src_size(job, clip)
    mem = _remembered(job)
    if isinstance(cam, list) and w and h:
        _learn(job, _frac(cam, w, h))
        mem = _remembered(job)
    if mem and w and h and cam != "full":
        mem_px = _px(mem, w, h)
        if not (isinstance(cam, list) and _iou(cam, mem_px) >= CAM_AGREE):
            cam = mem_px                                  # this clip's own look was fooled, or found nothing
            clip["camera_from"] = "remembered"
    clip["camera"] = "box" if isinstance(cam, list) else (cam or "none")
    if isinstance(cam, list):
        clip["facecam"] = cam


def _agree_cameras(job, words):
    """After a video's clips are made: the place most clips found the webcam is the webcam. Clips whose own look
    disagreed are made again with it, so one cutscene can't leave a game character in the facecam."""
    boxed = [c for c in job["clips"] if c.get("status") == "done" and c.get("layout") in render.FACECAM_LAYOUTS]
    found = [(c, c["facecam"]) for c in boxed if isinstance(c.get("facecam"), list) and c.get("camera_from") != "remembered"]
    if len(found) < 2:
        return 0
    best = max(found, key=lambda cf: sum(1 for _c, b in found if _iou(b, cf[1]) >= CAM_AGREE))
    group = [b for _c, b in found if _iou(b, best[1]) >= CAM_AGREE]
    if len(group) < 2 or len(group) * 2 < len(found):
        return 0                                          # no clear majority: each clip keeps its own
    cons = [int(np.median([b[i] for b in group])) for i in range(4)]
    w, h = _src_size(job, boxed[0])
    if w and h:
        _remember(job, _frac(cons, w, h), len(group))
    fixed = 0
    for c in boxed:
        if c.get("camera") == "full":
            continue
        if isinstance(c.get("facecam"), list) and _iou(c["facecam"], cons) >= CAM_AGREE:
            continue
        c.update(facecam=cons, camera="box", camera_from="agreed")
        render_one(job, c, words)
        fixed += 1
    return fixed


def _facecam(job, path=None) -> list | None:
    """Where the webcam is in the source: once for the whole video, for every clip of it.

    Only a sure answer is used. A box that is a scoreboard drawn over the game would
    put a picture of a scoreboard in the corner of the clip. One frame is also shown to
    the AI, which tells a person from a game character better than any measurement can;
    what it says is measured again on the picture, so it cannot do any harm."""
    path = path or job.get("source_path")
    if not path or not Path(path).is_file():
        return None
    try:
        box = facecam.detect(path, ask=brain.look_for_facecam)
    except Exception:  # noqa: BLE001 - a missing facecam is not a failure
        return None
    if not box or box.get("conf") != "high":
        return None
    job["facecam"] = [box["x"], box["y"], box["w"], box["h"]]
    return job["facecam"]


def _run_job(job):
    import math
    from concurrent.futures import ThreadPoolExecutor
    d = Path(job["dir"])
    o = job["options"]
    src = job["source"]
    tmark = [time.time()]
    job["timings"] = {}

    def mark(step):
        """How long each step took, in seconds: kept with the video, and sent with a bug report."""
        now = time.time()
        job["timings"][step] = round(now - tmark[0])
        tmark[0] = now
    # Which game this is: what the creator set, or what the title says. It decides the extra rules the AI
    # reads and the tags every post carries.
    game = job.get("game") or ""
    if not game and job.get("creator"):
        try:
            game = (creators.get(job["creator"]) or {}).get("game") or ""
        except Exception:  # noqa: BLE001
            game = ""
    if not game:
        game = games.detect(job["title"], src.get("name"))[0] or ""
    if game and job.get("game") != game:
        job["game"] = game
    t0 = time.time()
    notes = []
    usage.set_context(job["creator"], job["title"] or src.get("name"))
    resuming = bool(job.pop("resume", False)) and (d / "words.json").is_file()
    if resuming:   # after a restart: keep the transcript parts, clips and AI answers already made, and carry on
        _set(job, status="running", stage="Picking up where it stopped", error=None)
    else:
        _set(job, status="running", stage="Getting the audio", progress=0.03, error=None, clips=[], ai={}, done_blocks=0)
    if not transcribe.model_ready() and not transcribe.REMOTE:
        from . import fetch_model
        _set(job, stage="Getting the speech model (one time, about 480 MB)")
        fetch_model.ensure(lambda p: _set(job, stage=f"Getting the speech model (one time, about 480 MB): {p}%"))
        _set(job, stage="Getting the audio")
    fetch = ThreadPoolExecutor(1)
    video = None
    section = tuple(job["section"]) if job.get("section") and job.get("source_path") and Path(job["source_path"]).is_file() else None
    if src["type"] == "url":
        meta = media.info(src["url"])
        if meta["kind"] != "video":
            raise RuntimeError("That link is a channel or playlist, not a single video. Paste the link of one video.")
        if ((o["range_end"] or meta["duration"]) - (o["range_start"] or 0)) > config.MAX_VIDEO_HOURS * 3600:
            raise RuntimeError(f"That is longer than {config.MAX_VIDEO_HOURS:g} hours. Choose a shorter part of it under Options.")
        if meta["is_live"]:
            raise RuntimeError("This link is a live stream, so it would never finish downloading. Open the creator, "
                               "put this link under Setup, and press Start recording instead.")
        _set(job, title=meta["title"], uploader=meta["uploader"], duration=meta["duration"])
        if not job.get("thumb") and media.save_thumb(d, url=src["url"]):
            _set(job, thumb=True)
        usage.set_context(job["creator"], meta["title"])
        span = (o["range_end"] or meta["duration"]) - (o["range_start"] or 0)
        if o["range_end"] and meta["duration"] > 0 and span <= LONG_VIDEO and meta["duration"] - span > 120:
            # Only a part of a long video was asked for (a moment from a campaign's timestamps, say): just that
            # part is downloaded, with a little either side, and made into clips like a file of its own. A minute
            # of a three-hour stream takes seconds instead of downloading the whole stream.
            a_s = max(0.0, (o["range_start"] or 0) - SECTION_PAD)
            b_s = min(meta["duration"], o["range_end"] + SECTION_PAD)
            _set(job, stage="Getting that part of the video")
            part = media.download_section(src["url"], d, "source", a_s, b_s, int(o["quality"]), exact=True)
            info = media.probe(part)
            section = (a_s, b_s)
            _set(job, source_path=str(part), width=info["width"], height=info["height"], section=[a_s, b_s],
                 duration=round(info["duration"] or (b_s - a_s), 2))
            pieces, audio_file = False, part
        else:
            pieces = span > LONG_VIDEO or meta["duration"] <= 0
            if not pieces:  # shorter video: fetch all of it in the background while the audio is worked on
                video = fetch.submit(media.download, src["url"], d, int(o["quality"]))
            audio_file = media.download_audio(src["url"], d, lambda p: _set(job, progress=0.03 + 0.1 * p))
    else:
        pieces, audio_file = False, Path(src["path"])
        info = media.probe(audio_file)
        if info["duration"] > config.MAX_VIDEO_HOURS * 3600:
            raise RuntimeError(f"That video is longer than {config.MAX_VIDEO_HOURS:g} hours, which is the limit.")
        _set(job, source_path=str(audio_file), width=info["width"], height=info["height"], duration=info["duration"])
        if not job.get("thumb") and media.save_thumb(d, video=audio_file):
            _set(job, thumb=True)
    wav = d / "audio.wav"
    media.extract_audio(audio_file, wav)
    audio = media.load_audio(wav)
    wav.unlink(missing_ok=True)
    if src["type"] == "url" and not section:
        audio_file.unlink(missing_ok=True)
    if not job["duration"]:
        job["duration"] = len(audio) / 16000
    sec0 = section[0] if section else 0.0          # with only a part downloaded, times are counted from its start
    lo = max(0, int(((o["range_start"] or 0) - sec0) * 16000))
    hi = min(len(audio), int((o["range_end"] - sec0) * 16000)) if o["range_end"] else len(audio)
    span = (hi - lo) / 16000
    db = media.loudness_per_second(audio[lo:hi])

    vlock, vstate = threading.Lock(), {}
    mark("audio")

    def whole_video():
        """Wait for the background download once; retry it, or give up and use pieces."""
        with vlock:
            if section:                      # only a part was downloaded, and it is the video
                return job.get("source_path")
            if "path" not in vstate:
                path = None
                try:
                    path = video.result()
                except Exception as e:  # noqa: BLE001 - sites sometimes refuse a download
                    notes.append(f"Video download refused once ({str(e)[-80:]}), retrying")
                    try:
                        path = media.download(src["url"], d, int(o["quality"]))
                    except Exception as e2:  # noqa: BLE001
                        notes.append(f"Whole-video download failed ({str(e2)[-80:]}), fetching clip parts instead")
                if path:
                    info = media.probe(path)
                    job.update(source_path=str(path), width=info["width"], height=info["height"])
                vstate["path"] = path
            return vstate["path"]

    exact = {}      # clip id -> (from, to, words): our own model's words for just that clip
    rough = [False]  # the moments were found with the quick model: each clip's captions are written again, properly

    began = {}      # clip id -> when work on it started

    def make(clip, words_now):
        began[clip["id"]] = time.time()
        if src["type"] == "url" and (pieces or not whole_video()):
            _fetch_piece(job, clip, audio)
        if clip["status"] != "error":
            _use_camera(job, clip)          # webcam box, camera filling the picture, or none: for this clip
        yt_en = bool(yt and yt[1].lower().startswith("en"))
        if clip["status"] != "error" and clip.get("captions", True) and (yt_en or rough[0]):
            # The clip was found with YouTube's transcript, or with the quick model. What is shown on screen comes
            # from our own full model, run on just this clip: full punctuation, nothing blanked out, timings to the word.
            a0, b0 = max(lo, int((clip["start"] - 1.5) * 16000)), min(hi, int((clip["end"] + 1.5) * 16000))
            try:
                fine = transcribe.transcribe(audio[a0:b0]) if yt_en else asr(audio[a0:b0])
                tw = [dict(w, s=round(w["s"] + a0 / 16000, 2), e=round(w["e"] + a0 / 16000, 2)) for w in fine]
            except Exception:  # noqa: BLE001 - the clip is still made, with YouTube's words
                tw = []
            if len(tw) >= 3:
                exact[clip["id"]] = (a0 / 16000, b0 / 16000, tw)
                words_now = tw
        if clip["status"] != "error":
            render_one(job, clip, words_now)

    renders = ThreadPoolExecutor(render_workers())
    futures = []
    step = BLOCK * 16000 if span > PROGRESSIVE_FROM else hi - lo
    blocks = [(x, min(hi, x + step)) for x in range(lo, hi, step)] or [(lo, hi)]
    words, tokens, model = [], 0, None
    done_blocks = 0
    yt = None
    if src["type"] == "url" and config.YT_TRANSCRIPT and media.is_youtube(src["url"]):
        try:
            yt = media.youtube_words(src["url"])
        except Exception:  # noqa: BLE001 - no transcript to borrow: ours is written as usual
            yt = None
        if yt and section:                   # counted from the start of the part that was downloaded
            yt = ([dict(w, s=round(w["s"] - section[0], 2), e=round(w["e"] - section[0], 2)) for w in yt[0]
                   if section[0] <= w["s"] <= section[1]], yt[1])
        if yt and not _covers(yt[0], lo / 16000, hi / 16000):
            yt = None
        job["transcript_from"] = "youtube" if yt else "own"
        job["lang"] = yt[1] if yt else ""          # the language spoken, when YouTube says (decides the captions)
    # The language spoken: the one picked for this video, else what YouTube says, else Whisper listens and tells.
    # It decides which speech model writes the transcript (English: Parakeet; anything else: Whisper) and how the
    # captions are written.
    spoken, yt = _pick_language(job, o, yt, audio[lo:hi], resuming)
    use_whisper = [not whisper.is_english(spoken)]

    def asr(part, on_progress=None, quick=False):
        """The transcript of a part of the audio, by the speech model for the language spoken."""
        if use_whisper[0]:
            try:
                return whisper.transcribe(part, spoken.split("-")[0], on_progress, note=lambda t: _set(job, stage=t), quick=quick)
            except Exception as e:  # noqa: BLE001 - the English model still gives something to work with
                use_whisper[0] = False
                notes.append(f"Hindi speech model unavailable ({str(e)[-100:]}), used the English one")
        return transcribe.transcribe(part, on_progress)
    # Scan mode (long videos): look over the whole video first, then pick the best clips of all of it at once,
    # instead of clipping each part as it comes. Without YouTube's transcript only the lively parts are
    # transcribed, found from the loudness of every second, which is much quicker than the whole video.
    scan = span > PROGRESSIVE_FROM and job.get("kind") != "live" and o.get("scan", True)
    if scan and not yt:
        # Whisper (Hindi and other languages) is several times slower than the English model on an ordinary
        # computer, so it listens to shorter stretches around fewer lively moments: the same clips, far sooner.
        hot = _hot_regions(db, int(o["max_clips"]), WHISPER_REGION, 2) if use_whisper[0] else _hot_regions(db, int(o["max_clips"]))
        blocks = [(lo + a * 16000, min(hi, lo + b * 16000)) for a, b in hot]
        rough[0] = bool(use_whisper[0] and whisper.quick_model())
    prog_base, acc = [], 0
    for a_, b_ in blocks:
        prog_base.append(acc)
        acc += b_ - a_
    prog_total = max(1, acc)
    if resuming:
        try:
            words = json.loads((d / "words.json").read_text(encoding="utf-8"))
        except ValueError:
            words = []
        done_blocks = min(int(job.get("done_blocks", 0)), len(blocks)) if words else 0
        tokens, model = int((job.get("ai") or {}).get("tokens", 0)), (job.get("ai") or {}).get("model")
        if done_blocks < len(blocks):     # words past the last finished part are transcribed again
            cut = blocks[done_blocks][0] / 16000
            words = [w for w in words if w["s"] < cut]
        for c in job["clips"]:            # clips found before the restart that were not finished yet
            if c.get("status") not in ("done", "error"):
                c["status"] = "queued"
                futures.append((renders.submit(ctx.bind(make), c, list(words)), c))
        save(job)
    # The transcript of the next part is written while the AI is still reading this one (the AI is a wait on the
    # network, the transcript is work on this machine), so neither waits for the other.
    ahead = ThreadPoolExecutor(2, thread_name_prefix="ahead")
    heard, now_on = {}, [done_blocks]

    def hear(i):
        if i < len(blocks) and i >= done_blocks and i not in heard:
            a_, b_ = blocks[i]
            last = [0.0]

            def tp(p, i=i, a_=a_, b_=b_):
                if now_on[0] == i and p - last[0] > 0.05:      # only the part being shown moves the bar
                    last[0] = p
                    secs = (b_ - a_) / 16000
                    heard_now = f": {_mmss(p * secs)} of {_mmss(secs)} heard" if secs >= 60 else ""
                    stage = job.get("stage", "").split(":")[0] + heard_now     # people can see it's moving
                    _set(job, stage=stage, progress=max(job["progress"], 0.14 + 0.78 * (prog_base[i] + p * (b_ - a_)) / prog_total))
            heard[i] = ahead.submit(ctx.bind(asr), audio[a_:b_], tp, rough[0])

    def take(found, shift):
        """Drop clips in ad breaks or static screens, then queue the rest to be made."""
        if found and statics:
            # A commercial or a "be right back" slate is not a clip. Any clip that sits mostly inside one
            # is dropped.
            keep = []
            for c in found:
                a_s, b_s = c["start"] + shift, c["end"] + shift
                inside = quality.static_overlap(a_s, b_s, statics)
                if inside > 0.5 * max(1.0, b_s - a_s):
                    notes.append(f"A clip from {round(a_s)}s was left out: it sat in an ad break or a static screen.")
                else:
                    keep.append(c)
            found = keep
        for c in found:
            c.update(id=f"clip{len(job['clips']) + 1:02d}", start=round(c["start"] + shift, 2),
                     end=round(c["end"] + shift, 2), style=o["style"], layout=o["layout"],
                     captions=o.get("captions", True), zoom=o.get("zoom", True), watermark=o.get("watermark", ""),
                     status="queued", version=0)
            # Only the facecam layouts use a webcam, so it is only looked for then, and only once: a
            # stream with no webcam is not looked for again on every clip of it.
            job["clips"].append(c)
            futures.append((renders.submit(ctx.bind(make), c, list(words)), c))

    # The ad breaks and static screens of the whole video, found once. It reads the video end to end,
    # so it is done here rather than for each clip, and only when asked for.
    statics = quality.static_ranges(job.get("source_path") or "") if config.SKIP_STATIC else []
    for bi, (a, b) in enumerate(blocks):
        if bi < done_blocks:
            continue                      # transcribed and checked by the AI before the restart
        shift = a / 16000
        where = f" (minute {round((a - lo) / 16000 / 60)} of {round(span / 60)})" if len(blocks) > 1 else ""
        if scan and not yt:
            where = f" (part {bi + 1} of {len(blocks)})"
        if yt:
            _set(job, stage="Reading the transcript" + where)
            bw = [dict(w, s=round(w["s"] - shift, 2), e=round(w["e"] - shift, 2)) for w in yt[0] if a / 16000 <= w["s"] < b / 16000]
        else:
            _set(job, stage=("Listening to the lively parts" if scan else "Writing the transcript") + where)
            now_on[0] = bi
            hear(bi)
            hear(bi + 1)
            bw = heard.pop(bi).result()
        _set(job, progress=max(job["progress"], 0.14 + 0.78 * (prog_base[bi] + (b - a)) / prog_total))
        words += [dict(w, s=round(w["s"] + shift, 2), e=round(w["e"] + shift, 2)) for w in bw]
        (d / "words.json").write_text(json.dumps(words), encoding="utf-8")
        if scan:                          # the clips are picked once the whole video has been looked over
            job["done_blocks"] = bi + 1
            save(job)
            continue
        _set(job, stage="Finding the best moments" + where, word_count=len(words))
        left = int(o["max_clips"]) - len(job["clips"])
        if left <= 0 or len(bw) < 8:
            job["done_blocks"] = bi + 1
            save(job)
            continue
        quota = max(1, math.ceil(left / (len(blocks) - bi)))
        s0 = int((a - lo) / 16000)
        found, ai = brain.find_clips(bw, db[s0: s0 + int((b - a) / 16000) + 1], (b - a) / 16000, job["title"],
                                     job["uploader"], quota, int(o["min_len"]), int(o["max_len"]), notes.append, game=game)
        tokens += ai.get("tokens", 0)
        model = ai.get("model") or model
        if ai.get("note"):
            notes.append(ai["note"])
        take(found, shift)
        job["ai"] = {"model": model, "tokens": tokens, "note": "", "log": notes[-5:]}
        job["done_blocks"] = bi + 1       # a restart from here on carries on with the next part
        save(job)
    mark("transcript")
    if scan and not job["clips"] and words:
        _set(job, stage="Picking the best moments of the whole video", progress=max(job["progress"], 0.9))
        base = lo / 16000
        rel = [dict(w, s=round(w["s"] - base, 2), e=round(w["e"] - base, 2)) for w in words]
        found, ai = brain.find_clips(rel, db, span, job["title"], job["uploader"], int(o["max_clips"]),
                                     int(o["min_len"]), int(o["max_len"]), notes.append, game=game)
        tokens += ai.get("tokens", 0)
        model = ai.get("model") or model
        if ai.get("note"):
            notes.append(ai["note"])
        take(found, base)
        job["ai"] = {"model": model, "tokens": tokens, "note": "", "log": notes[-5:]}
        save(job)
    if not job["clips"] and job.get("kind") != "live" and span >= 5:
        # The safety net: nothing was picked (the AI found nothing that stood out, or too little was heard to ask
        # it), so the liveliest parts are clipped. Someone who asked for clips never gets none back.
        base = lo / 16000
        rel = [dict(w, s=round(w["s"] - base, 2), e=round(w["e"] - base, 2)) for w in words]
        n = min(int(o["max_clips"]), 3, max(1, int(span // max(15, int(o["max_len"])))))
        net = brain.liveliest_clips(rel, db, span, n, int(o["min_len"]), int(o["max_len"]))
        if net:
            notes.append("Nothing stood out to the AI, so the liveliest parts were clipped.")
            job["safety_net"] = True
            take(net, base)
    mark("picking")
    if futures:
        _set(job, stage="Finishing the clips", progress=max(job["progress"], 0.92))
    _wait_for_clips(job, futures, began, renders._max_workers)
    try:
        if _agree_cameras(job, words):
            notes.append("The facecam was set the same in every clip.")
    except Exception:  # noqa: BLE001 - the clips are already made; this only improves them
        traceback.print_exc()
    mark("clips")
    if exact:           # keep our own words for the clips in the saved transcript, so editing a clip later uses them
        for a_s, b_s, tw in exact.values():
            words = [w for w in words if not a_s <= w["s"] < b_s] + tw
        words.sort(key=lambda w: w["s"])
        (d / "words.json").write_text(json.dumps(words), encoding="utf-8")
    renders.shutdown(wait=False)
    ahead.shutdown(wait=False)
    fetch.shutdown(wait=False)
    del audio
    clips = job["clips"]
    job["ai"] = {"model": model, "tokens": tokens, "log": notes[-5:],
                 "note": "Nothing stood out to the AI, so the liveliest parts were clipped." if job.get("safety_net") and model
                 else "The AI was unavailable, so clips were picked by loudness only." if clips and not model else ""}
    stage = "Done" if clips else "Done, but nothing clip-worthy was found"
    _set(job, status="done", stage=stage, progress=1.0, took=round(time.time() - t0))
    try:
        from . import notices
        name = job.get("title") or job["source"].get("name") or "your video"
        notices.add(job.get("user"), "clips", f"{len(clips)} clip{'s' if len(clips) != 1 else ''} ready" if clips else "Nothing clip-worthy found",
                    name, f"/app/creators/{job['creator']}" if job.get("creator") else "/app/videos")
    except Exception:  # noqa: BLE001
        pass
    creators.log(job["creator"], f"Video finished with {len(clips)} clips in {round(time.time() - t0)}s: {job['title']}")


def _worker(quick_only=False):
    while True:
        kind, a, cid = _q.get(quick_only)
        if kind == "fn":
            try:
                a()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            continue
        job = _jobs.get(a)
        if not job:
            if kind == "job":
                _q.done()
            continue
        token = ctx._uid.set(job["user"])  # everything this job does runs as its owner
        try:
            if kind == "job":
                _run_job(job)
            else:
                clip = next(c for c in job["clips"] if c["id"] == cid)
                words = []
                if clip.get("captions", True):
                    words = json.loads((Path(job["dir"]) / "words.json").read_text(encoding="utf-8"))
                if clip.get("layout") in render.FACECAM_LAYOUTS and not clip.get("camera"):
                    _use_camera(job, clip)    # re-made with a facecam layout: how the camera shows in this clip
                render_one(job, clip, words)
        except Exception as e:  # noqa: BLE001
            (Path(job["dir"]) / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
            if kind == "job":
                for c in job["clips"]:
                    if c.get("status") in ("queued", "rendering"):
                        c.update(status="error", error="The video stopped before this clip was made.")
                _set(job, status="error", error=safe.friendly(e), stage="Stopped")
                creators.log(job["creator"], f"Video failed: {safe.friendly(e)[:200]}")
        finally:
            ctx._uid.reset(token)
            if kind == "job":
                _q.done()


def _pick_up_after_restart():
    """Videos and single clips that were being made when the server stopped: queued again, oldest first."""
    waiting = sorted((j for j in all_jobs() if j.get("status") == "queued" and j.get("resume")), key=lambda j: j["created"])
    for j in waiting:
        _q.put(("job", j["id"], None), user=j["user"])
    for j in all_jobs():
        for cid in j.pop("remake", []):
            _q.put(("clip", j["id"], cid))
        if j.get("status") == "done":
            save(j)


def start():
    load.start()
    load_all()
    _pick_up_after_restart()
    for _ in range(max(1, config.JOB_WORKERS)):
        threading.Thread(target=_worker, daemon=True).start()
    threading.Thread(target=_worker, args=(True,), daemon=True).start()   # re-making a single clip never waits behind whole videos
    threading.Thread(target=_live_worker, daemon=True).start()
