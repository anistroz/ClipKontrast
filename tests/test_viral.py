"""Viral moments, and telling people when their AI stops.

1. The stream's chat replay: what viewers wrote, read from yt-dlp's live_chat file (also while it's still coming),
   turned into a per-second "viewers reacted" signal (spam counted once, laughing and "clip it" counted more, moved
   back to the moment that caused it), used to pick the parts to listen to, shown to the AI with what viewers wrote,
   and used with no AI too.
2. A stricter idea of viral in the prompt, and a final pick over every candidate side by side, which can drop a
   moment that needs outside context and move a start earlier for the setup.
3. When the AI key stops (out of credit, say): a notice that the free AI on the PC took over, or, without it, that
   clips won't be the best and how to get it; the dashboard banner and Settings say the same.

The AI, YouTube and Ollama are replaced; nothing outside this machine is contacted."""
import json, os, sys, tempfile, time
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-viral-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0",
                  CLIPKONTRAST_PUBLIC_URL="http://127.0.0.1:8765", CLIPKONTRAST_OLLAMA_URL="http://127.0.0.1:9")
sys.path.insert(0, ".")
import numpy as np  # noqa: E402
from studio import ai, auth, brain, config, ctx, db, jobs, media, notices  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


# ================================================================ 1. the chat replay
def line(t, who, *runs, paid=False):
    r = {"message": {"runs": list(runs)}, "authorName": {"simpleText": who}}
    item = {"liveChatPaidMessageRenderer" if paid else "liveChatTextMessageRenderer": r}
    return json.dumps({"replayChatItemAction": {"actions": [{"addChatItemAction": {"item": item}}],
                                                "videoOffsetTimeMsec": str(int(t * 1000))}})


check("a viewer's message is read: when, who, what", media._chat_line(line(12.5, "amy", {"text": "LMAO "}, {"emoji": {"emojiId": "😂"}})),
      (12.5, "amy", "LMAO  😂"))
check("...a channel emote by its name", media._chat_line(line(3, "b", {"emoji": {"emojiId": "UCxyz/abc", "shortcuts": [":_kekw:"]}}))[2], ":_kekw:")
check("...a Super Chat is marked", media._chat_line(line(5, "c", {"text": "W stream"}, paid=True))[2], "$ W stream")
check("...anything that isn't a message is skipped", [media._chat_line(x) for x in ("{}", "not json", json.dumps({"replayChatItemAction": {"actions": [{"addLiveChatTickerItemAction": {}}], "videoOffsetTimeMsec": "1"}}))],
      [None, None, None])
check("not a YouTube link: no chat replay, nothing fetched", media.ChatReplay("https://kick.com/x/videos/1", Path(tempfile.mkdtemp())).messages(), [])

wrote = []


def fake_fetch(self):
    f = self.dir / "c.live_chat.json.part"                      # still coming: yt-dlp's .part file
    with open(f, "w", encoding="utf-8") as fh:
        for i in range(5):
            fh.write(line(10 + i, f"u{i}", {"text": "haha"}) + "\n")
        fh.write("{half a line")
    wrote.append(1)
    self.done = True


real_fetch = media.ChatReplay._fetch
media.ChatReplay._fetch = fake_fetch
cr = media.ChatReplay("https://www.youtube.com/watch?v=abcdefghijk", Path(tempfile.mkdtemp()), budget=30)
got = cr.messages(wait=5)
check("a YouTube stream's chat is fetched in the background and read while it's still coming", (wrote, len(got), got[0][2]), ([1], 5, "haha"))
cr.stop()
check("...and its files go when it's done", cr.dir.exists(), False)
media.ChatReplay._fetch = real_fetch

# ---- chat as a signal
rs = np.random.RandomState(7)
msgs = [(float(t), f"v{rs.randint(300)}", rs.choice(["hi", "gg", "nice", "what game is this", "lol"])) for t in range(0, 1800, 3)]
msgs += [(606 + i * 0.25, f"fan{i}", rs.choice(["LMAO 😂😂", "NO WAY 💀", "clip it", "KEKW", "bro what"])) for i in range(60)]
msgs += [(300 + i * 0.1, "spammer", "LMAO LMAO LMAO") for i in range(100)]           # one person, a hundred times
z = brain.chat_signal(msgs, 1800)
check("chat: the moment viewers went wild stands out", float(z[595:615].max()) > 3)
check("...moved back to what caused it (chat reacts a few seconds late)", 594 <= int(np.argmax(z)) <= 612)
check("...one person spamming counts far less than many people reacting", float(z[290:310].max()) < 0.5 * float(z[595:615].max()))
check("too little chat to tell: no signal", brain.chat_signal(msgs[:5], 1800), None)
check("past what's been fetched: unknown, not quiet", float(brain.chat_signal(msgs[:300], 1800)[1000:].max()), 0.0)
check("what viewers wrote at a moment, the loudest first", brain.chat_says(msgs, 598, 605)[0] in ("LMAO 😂😂", "NO WAY 💀", "clip it"))

# ---- used with no AI, and to choose what to listen to
db_ = np.full(1800, -30.0, dtype=np.float32) + rs.normal(0, 0.4, 1800).astype(np.float32)
words = [{"w": "talking", "s": float(s), "e": s + 0.5} for s in range(0, 1800, 2)]
c = brain.moment_candidates(db_, words, 1, 15, 45, 1800.0, None, "x", z)
check("no AI, flat sound: the moment viewers reacted to is the one picked", c[0]["start"] <= 600 <= c[0]["end"])
hot = jobs._hot_regions(db_, 2, 90, 1, z)
check("long video: the part viewers reacted to is among the parts listened to", any(a <= 600 <= b for a, b in hot))

# ================================================================ 2. the prompt and the final pick
asked = []
words = []
for t in range(0, 900, 3):
    words += [{"w": w, "s": t + i * 0.4, "e": t + i * 0.4 + 0.3} for i, w in enumerate("so we are just walking here.".split())]
words = sorted(words, key=lambda w: w["s"])


def fake_ask(prompt, schema=None, purpose="", timeout=None):
    asked.append((purpose, prompt))
    if purpose == "Video: final pick":
        return ([{"id": 0, "keep": True, "start": 585.0, "end": 625.0, "score": 92, "hook": "CHAT LOST IT"},
                 {"id": 1, "keep": False, "start": 300.0, "end": 330.0, "score": 40},
                 {"id": 2, "keep": True, "start": 120.0, "end": 150.0, "score": 70}], "m1", 50)
    return ([{"start": 597, "end": 625, "score": 85, "hook": "WAIT", "title": "t", "description": "", "hashtags": [], "reason": "r"},
             {"start": 300, "end": 330, "score": 72, "hook": "HM", "title": "t", "description": "", "hashtags": [], "reason": "r"},
             {"start": 120, "end": 150, "score": 66, "hook": "OK", "title": "t", "description": "", "hashtags": [], "reason": "r"},
             {"start": 450, "end": 480, "score": 40, "hook": "MEH", "title": "t", "description": "", "hashtags": [], "reason": "r"}], "m1", 100)


real_ask = brain.ask_ai
brain.ask_ai = fake_ask
brain.config.ai_ready = lambda: True
brain._down.update(until=0.0, why=None)
chat = {"z": z[:900], "msgs": [m for m in msgs if m[0] < 900], "offset": 0.0}
found, info = brain.find_clips(words, db_[:900], 900.0, "GTA", "Mizo", max_clips=3, min_len=15, max_len=45, log=lambda m: None, chat=chat)
scout = next(p for k, p in asked if k == "Video: finding clips")
check("the AI is told what goes viral, and what doesn't", "What goes viral" in scout and "What does NOT go viral" in scout and "Below 60: don't return it" in scout)
check("...and sees what viewers wrote where they reacted", '(CHAT: "' in scout and any(x in scout for x in ("LMAO", "NO WAY", "clip it", "KEKW")))
final = next(p for k, p in asked if k == "Video: final pick")
check("a final pick over all the candidates side by side, each with what came before it", "<candidate id=0" in final and ">>" in final)
check("...the scouts' weak ones (under 60) aren't judged", "start=450.0" not in final)
check("a moment the final pick says needs outside context, or is just normal, is dropped", all(not (c["start"] <= 310 <= c["end"]) for c in found))
best = next(c for c in found if c["start"] <= 600 <= c["end"])
check("...the start moved earlier for the setup it needs", best["start"] < 590)
check("...its hook from the final pick", best["hook"], "CHAT LOST IT")
check("...the tokens of both rounds are counted (two parts of the video, then the final pick)", info["tokens"], 250)

asked.clear()


def no_final(prompt, schema=None, purpose="", timeout=None):
    if purpose == "Video: final pick":
        raise RuntimeError("The AI did not answer")
    return fake_ask(prompt, schema, purpose, timeout)


brain.ask_ai = no_final
found, info = brain.find_clips(words, db_[:900], 900.0, "GTA", "Mizo", max_clips=3, min_len=15, max_len=45, log=lambda m: None, chat=chat)
check("the final pick couldn't be asked: the scouts' own picks are used, the best (85) among them",
      len(found) >= 2 and any(c["start"] <= 600 <= c["end"] for c in found))
brain.ask_ai = real_ask

# ---- the whole pipeline: a YouTube stream with a chat replay
import shutil, subprocess  # noqa: E402
work = Path(tempfile.mkdtemp(prefix="pc-viral-work-"))
src = work / "stream.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x223344:size=640x360:rate=15", "-f", "lavfi",
                "-i", "sine=f=300:sample_rate=48000", "-t", "240", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)], check=True)
URL = "https://www.youtube.com/watch?v=abcdefghijk"
media.info = lambda url: {"title": "Day 2 stream", "uploader": "Mizo Plays", "duration": 240.0, "is_live": False, "thumbnail": "",
                          "kind": "video", "channel_url": "", "live_status": "was_live", "handle": "Mizoplays", "platform": "youtube"}
media.save_thumb = lambda *a, **k: False
media.youtube_words = lambda url: None


def fake_audio(url, d, on_progress=None):
    out = Path(d) / "audio_src.mp4"
    shutil.copyfile(src, out)
    return out


def fake_video(url, d, height=720):
    out = Path(d) / "source.mp4"
    shutil.copyfile(src, out)
    return out


media.download_audio, media.download = fake_audio, fake_video
started_chat = []


class FakeChat:
    def __init__(self, url, out_dir, budget=300):
        started_chat.append(url)

    def messages(self, wait=0.0):
        return [(float(t), f"v{t % 50}", "hi") for t in range(0, 240, 2)] + \
               [(126 + i * 0.2, f"fan{i}", "LMAO 💀") for i in range(50)]

    def stop(self):
        started_chat.append("stopped")


media.ChatReplay = FakeChat
from studio import transcribe  # noqa: E402
transcribe.model_ready = lambda: True
transcribe.transcribe = lambda audio, on_progress=None: [{"w": w, "s": t + i * 0.4, "e": t + i * 0.4 + 0.3}
                                                         for t in range(0, 236, 3) for i, w in enumerate("bro what is this.".split())]
jobs._pick_language = lambda job, o, yt, audio, resuming=False: (job.__setitem__("lang", "en"), ("en", yt))[1]
seen_prompts = []


def pipe_ask(prompt, schema=None, purpose="", timeout=None):
    seen_prompts.append(prompt)
    if purpose == "Video: final pick":
        return ([{"id": 0, "keep": True, "start": 115.0, "end": 140.0, "score": 90}], "m1", 10)
    return ([{"start": 118, "end": 140, "score": 88, "hook": "CHAT LOST IT", "title": "t", "description": "", "hashtags": [], "reason": "r"}], "m1", 10)


brain.ask_ai = pipe_ask
with ctx.as_user(auth.local_user().id):
    job = jobs.create({"type": "url", "url": URL, "name": URL}, {"max_clips": 2, "min_len": 15, "max_len": 45, "layout": "blur", "zoom": False}, enqueue=False)
    jobs._run_job(job)
check("a YouTube stream that was live: its chat replay is read alongside", started_chat[:1], [URL])
check("...the AI sees what viewers wrote where they reacted", any('(CHAT: "LMAO' in p for p in seen_prompts))
check("...the clip is made from there", (job["status"], [c["status"] for c in job["clips"]], job["clips"][0]["start"] <= 126 <= job["clips"][0]["end"]),
      ("done", ["done"], True))
check("...it says the chat was read, and the chat's files are cleared away", (any("chat replay was read" in x for x in job["ai"].get("log", [])),
                                                                              started_chat[-1]), (True, "stopped"))
brain.ask_ai = real_ask

# ================================================================ 3. telling people their AI stopped
from unittest.mock import patch  # noqa: E402
user = auth.local_user()
with ctx.as_user(user.id), patch.object(config, "ai_ready", return_value=True), patch.object(ai, "models", return_value=["m1"]), \
        patch.object(ai, "call", side_effect=RuntimeError("HTTP 429 RESOURCE_EXHAUSTED: You exceeded your current quota")):
    brain._down.update(until=0.0, why=None)
    brain._LOCAL.update(at=9e12, model=None, models=[])
    try:
        brain.ask_ai("x", purpose="t")
    except RuntimeError:
        pass
    items = notices.mine()["items"]
    n1 = [n for n in items if n["kind"] == "ai"]
    check("the AI key ran out, no free AI: a notice says clips won't be the best, and how to get the free AI",
          len(n1) == 1 and "won't be the best" in n1[0]["title"] and "free AI" in n1[0]["body"] and n1[0]["link"] == "/app/settings/ai")
    brain._down.update(until=0.0, why=None)
    try:
        brain.ask_ai("x", purpose="t")
    except RuntimeError:
        pass
    check("...not again and again", len([n for n in notices.mine()["items"] if n["kind"] == "ai"]), 1)
    brain._down.update(until=0.0, why=None)
    brain._LOCAL.update(at=9e12, model="llama3.2:3b", models=["llama3.2:3b"])
    try:
        brain.ask_ai("x", purpose="t")
    except RuntimeError:
        pass
    n2 = [n for n in notices.mine()["items"] if n["kind"] == "ai" and "now using the free AI" in n["title"]]
    check("with the free AI on the PC: a notice that it took over", len(n2) == 1 and "llama3.2:3b" in n2[0]["body"])
    from studio import usage  # noqa: E402
    usage._brief.clear()
    b = usage.brief()
    check("the dashboard knows the key is resting and which free AI took over", (b["resting"], b["local"], bool(b["problem"])), (True, "llama3.2:3b", True))
brain._down.update(until=0.0, why=None)
brain._LOCAL.update(at=0.0, model=None, models=[])

page = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
check("the banner: running on the free AI, or clips won't be the best with a Set up free AI button",
      all(x in page for x in ("vb ok-bar", "vb warn-bar", "free AI on your PC is making your clips now", "Set up free AI")))
check("Settings, AI starts with who picks the clips right now", all(x in page for x in ("ai-who", "data-act=\"tolocalai\"", "takes over by itself")))
check("the bell shows these with the AI icon", 'ai: "bolt"' in page)
import re as _re, shutil as _sh, subprocess as _sp  # noqa: E402
if _sh.which("node"):
    js = Path(tempfile.mkdtemp(prefix="pc-js-")) / "app.mjs"
    js.write_text(max(_re.findall(r"<script[^>]*>(.*?)</script>", page, _re.S), key=len), encoding="utf-8")
    p = _sp.run(["node", "--check", str(js)], capture_output=True, text=True)
    check("the page's script has no syntax errors", p.returncode == 0 or p.stderr[-300:], True)

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
