"""The AI hears a decided clip (Gemini only; from PeakCut upstream, adapted): the cut moves onto sentence boundaries
and keeps the payoff, the heading fits that cut, English captions come from the sound; Hindi keeps the Hinglish
model's words; any other AI (or a failing answer) makes the clip exactly as before. Gemini is stood in for."""
import json, os, subprocess, sys, tempfile
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-listen-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0")
sys.path.insert(0, ".")
from unittest.mock import patch  # noqa: E402
from studio import ai, auth, brain, ctx, db, jobs  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


work = Path(tempfile.mkdtemp())
src = work / "s.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x223344:size=1280x720:rate=15", "-f", "lavfi", "-i",
                "sine=f=300:sample_rate=48000", "-t", "90", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)], check=True)
# sentences of four words with a pause between them, like real talk
words = [{"w": "so", "s": round(20 + k * 3.0 + j * 0.5, 2), "e": round(20 + k * 3.0 + j * 0.5 + 0.4, 2)} for k in range(14) for j in range(4)]
asked = {}


def gemini(model, prompt, schema, timeout=None, audio=None, temperature=None):
    asked.update(audio=audio, prompt=prompt)
    # the audio given starts 8 s before the clip (clip at 30-50 s -> audio from 22 s); the payoff lands at 55 s
    return ({"start": 6.0, "end": 28.0, "payoff": "he finally lands the jump", "payoff_end": 33.0, "spoken": "en",
             "hook": "He tried the jump one more time",
             "phrases": [{"text": "okay one more", "start": 6.2, "end": 7.5}, {"text": "time let's go", "start": 8.0, "end": 9.4},
                         {"text": "he did it!", "start": 30.0, "end": 31.5}]}, 900, 120)


user = auth.local_user()


def make(provider="gemini", answer=gemini, lang="en"):
    brain._down.update(until=0.0, why=None)          # an earlier failure here rests the AI a while: not for this one
    ai.save(provider, ["gemini-flash-latest" if provider == "gemini" else "gpt-x"], "", "k")
    with ctx.as_user(user.id):
        job = jobs.create({"type": "file", "path": str(src), "name": "jump"}, {"min_len": 15, "max_len": 60}, enqueue=False)
    job.update(source_path=str(src), duration=90.0, width=1280, height=720, lang=lang, title="Jump attempts")
    clip = {"id": "clip01", "start": 30.0, "end": 50.0, "hook": "WAIT FOR IT", "title": "t", "status": "queued", "captions": True,
            "style": "bounce", "layout": "blur", "score": 80, "description": "", "hashtags": [], "highlight_words": [],
            "reason": "the jump", "category": "funny"}
    job["clips"] = [clip]
    (Path(job["dir"]) / "words.json").write_text(json.dumps(words))
    with patch.object(brain.config, "ai_ready", return_value=True), patch.object(ai, "_gemini", answer):
        jobs.render_one(job, clip, words)
    return clip


c = make()
check("Gemini hears the clip's sound (with 8 s before and 20 s after)", (asked["audio"][1] in ("audio/ogg", "audio/wav"), len(asked["audio"][0]) > 1000), (True, True))
check("the clip is made", c["status"], "done")
check("the end moves to just after the payoff it heard (past the first cut)", c["end"], lambda e: 54.5 <= e <= 56.0)
check("the start stays on the setup", c["start"], lambda s: 27.0 <= s <= 29.0)
check("the heading is written for this cut", c["hook"], "HE TRIED THE JUMP ONE MORE TIME")
check("English captions come from what it heard, inside the new cut", (c.get("caption_by"), [w["w"] for w in c["heard"]["words"]]),
      lambda g: g[0] == "ai-listened" and g[1][-3:] == ["he", "did", "it!"] and "time" in g[1])
check("the page isn't sent the heard words", "heard" not in jobs.public({"source": {}, "clips": [c], "ai": {}, "status": "done"})["clips"][0])

c2 = make(answer=lambda *a, **k: (_ for _ in ()).throw(ai.AIError("HTTP 500 oops")))
check("the AI failing to listen: the clip is made exactly as before", (c2["status"], c2["start"], c2["end"], c2["hook"], bool(c2.get("listen_error"))),
      ("done", 30.0, 50.0, "WAIT FOR IT", True))

asked.clear()
c3 = make(provider="openai")
check("another AI (not Gemini): nothing is sent, the clip is made as before", (asked, c3["start"], c3["end"], c3["status"]), ({}, 30.0, 50.0, "done"))


def hindi(model, prompt, schema, timeout=None, audio=None, temperature=None):
    out = gemini(model, prompt, schema, timeout, audio, temperature)[0]
    return dict(out, spoken="hi", phrases=[{"text": "bhai ye kya", "start": 6.2, "end": 7.5}, {"text": "ho gaya", "start": 8.0, "end": 9.0}]), 900, 120


c4 = make(answer=hindi, lang="hi")
check("Hindi: the cut and the heading are taken, but not its words (the Hinglish model's stay)",
      (c4["end"] > 50, c4.get("caption_by") != "ai-listened"), (True, True))
check("listening never runs on a re-make (someone's own trim stays)", "not clip.get(\"version\")" in (Path("studio/jobs.py").read_text()))

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
