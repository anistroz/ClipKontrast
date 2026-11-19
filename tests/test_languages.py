"""Hindi and other languages: picking the language spoken, Whisper for anything but English, captions in English.

Whisper itself is replaced by a stand-in here (the real model is a 500 MB download), so this checks everything
around it: which model is used when, what its words look like, and what happens when it can't be installed.

Runs against the code directly, with its own empty data folder."""
import os, sys, tempfile, threading, types
from unittest.mock import patch
os.environ["CLIPKONTRAST_DATA"] = tempfile.mkdtemp(prefix="pc-langs-")
os.environ["CLIPKONTRAST_WHISPER"] = "1"      # on, but every install below is stopped before it reaches the internet
sys.path.insert(0, ".")
import numpy as np
from studio import brain, creators, ctx, jobs, live, transcribe, whisper
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


# ---- the settings
check("Hindi is offered", "hi" in whisper.LANGUAGES and "auto" in whisper.LANGUAGES)
check("a video can pick Hindi", jobs.clean_options({"lang": "hi"})["lang"], "hi")
check("an unknown language becomes auto", jobs.clean_options({"lang": "xx"})["lang"], "auto")
check("captions can be always English", jobs.clean_options({"caption_lang": "en"})["caption_lang"], "en")
check("nonsense caption language becomes auto", jobs.clean_options({"caption_lang": "zz"})["caption_lang"], "auto")
check("a creator can pick Hindi", creators._clean({"lang": "hi", "caption_lang": "en"}), {"lang": "hi", "caption_lang": "en"})
check("a creator's nonsense language becomes auto", creators._clean({"lang": "<b>"})["lang"], "auto")
check("new videos default to auto", (jobs.DEFAULTS["lang"], jobs.DEFAULTS["caption_lang"]), ("auto", "auto"))

# ---- picking the language spoken
audio = np.zeros(16000 * 40, dtype=np.int16)
job = {"options": {}}
with patch.object(whisper, "detect", return_value=("ur", 0.9)):
    check("Whisper's \"Urdu\" for spoken Hindi is treated as Hindi", jobs._pick_language(job, {"lang": "auto"}, None, audio)[0], "hi")
with patch.object(whisper, "detect", return_value=("ta", 0.8)):
    check("Tamil is detected", jobs._pick_language(job, {"lang": "auto"}, None, audio)[0], "ta")
with patch.object(whisper, "detect", return_value=None):
    check("no Whisper: treated as English, as before", jobs._pick_language(job, {"lang": "auto"}, None, audio)[0], "en")
with patch.object(whisper, "detect", side_effect=RuntimeError("boom")):
    check("Whisper failing: treated as English", jobs._pick_language(job, {"lang": "auto"}, None, audio)[0], "en")
yt = ([{"w": "नमस्ते", "s": 0, "e": 1}], "hi")
with patch.object(whisper, "detect") as d:
    got = jobs._pick_language(job, {"lang": "auto"}, yt, audio)
    check("YouTube's language is used when it knows, without listening", (got[0], got[1] is yt, d.called), ("hi", True, False))
    got = jobs._pick_language(job, {"lang": "en"}, yt, audio)
    check("a picked language wins, and YouTube's other-language transcript is not used", (got[0], got[1], job["transcript_from"]), ("en", None, "own"))
    got = jobs._pick_language(job, {"lang": "hi"}, None, audio)
    check("picking Hindi doesn't need detection", (got[0], d.called, job["lang"]), ("hi", False, "hi"))
    check("after a restart the language found before is kept", jobs._pick_language({"lang": "bn"}, {"lang": "auto"}, None, audio, True)[0], "bn")


# ---- Whisper's words, with a stand-in for faster-whisper
class FakeModel:
    calls = []

    def __init__(self, *a, **k):
        FakeModel.calls.append(("load", a, k))

    def transcribe(self, audio, language=None, **k):
        FakeModel.calls.append(("run", language, k))
        W = types.SimpleNamespace
        segs = [W(end=1.0, words=[W(word=" भाई", start=0.1, end=0.4), W(word=" ये", start=0.5, end=0.5)]),
                W(end=2.0, words=[W(word=" क्या", start=1.2, end=1.6), W(word="  ", start=1.6, end=1.7)])]
        return iter(segs), W(language=language or "hi", language_probability=0.93)


fake = types.ModuleType("faster_whisper"); fake.WhisperModel = FakeModel
with patch.dict(sys.modules, {"faster_whisper": fake}):
    whisper._model = None
    prog = []
    words = whisper.transcribe(np.zeros(32000, dtype=np.int16), "hi", prog.append)
    check("Whisper's words come out with their times", [w["w"] for w in words], ["भाई", "ये", "क्या"])
    check("a word never ends before it starts", all(w["e"] > w["s"] for w in words))
    check("Whisper asked for word times, in Hindi", FakeModel.calls[-1][1:], ("hi", FakeModel.calls[-1][2]) )
    check("word timestamps are on", FakeModel.calls[-1][2].get("word_timestamps"), True)
    check("progress reaches the end", prog[-1], 1.0)
    check("the model is loaded once, on the processor, compact", sum(1 for c in FakeModel.calls if c[0] == "load"), 1)
    check("detect says the language", whisper.detect(np.zeros(16000 * 50, dtype=np.int16)), ("hi", 0.93))
whisper._model = None

# ---- installing it
with patch.dict(sys.modules, {"faster_whisper": None}):
    with patch.object(whisper.subprocess, "run", return_value=types.SimpleNamespace(returncode=1, stderr="no internet", stdout="")):
        check("no internet: not installed, no crash", whisper.install(), False)
        try:
            whisper.transcribe(np.zeros(100, dtype=np.int16))
            check("transcribing without Whisper raises", False)
        except RuntimeError as e:
            check("transcribing without Whisper raises a clear message", "internet" in str(e))
    with patch.object(whisper, "ENABLED", False), patch.object(whisper.subprocess, "run") as run:
        check("turned off: never installs", (whisper.install(), run.called), (False, False))

# ---- captions: Hinglish as spoken, or always English
with patch.object(brain, "fix_caption_words", return_value=["fixed"]) as fx, \
        patch.object(brain, "translate_caption_words", return_value=[{"w": "what", "s": 0, "e": 1}]) as tr:
    check("Hindi captions stay Hinglish by default", brain.english_captions([], "hi"), ["fixed"])
    check("Hindi captions can be translated to English", brain.english_captions([{"w": "क्या", "s": 0, "e": 1}], "hi", always_english=True)[0]["w"], "what")
    check("English stays English even when always-English is on", brain.english_captions([], "en", always_english=True), ["fixed"])

# ---- live: the right model for the language, and "क्लिप" heard as "clip"
s = live.Session.__new__(live.Session)
s.lock, s.job, s.spoken, s.whisper_ok = threading.RLock(), {}, None, True
chunk = np.zeros(16000 * 6, dtype=np.int16)
with patch.object(whisper, "detect", return_value=("ur", 0.8)), \
        patch.object(whisper, "transcribe", return_value=[{"w": "क्लिप", "s": 1.0, "e": 1.3}]) as wt, \
        patch.object(transcribe, "transcribe", return_value=[]) as pt:
    out = s._hear(chunk)
    check("live: Hindi found and heard by Whisper", (s.spoken, s.job.get("lang"), wt.called, pt.called), ("hi", "hi", True, False))
s2 = live.Session.__new__(live.Session)
s2.lock, s2.job, s2.spoken, s2.whisper_ok = threading.RLock(), {}, None, True
with patch.object(whisper, "detect", return_value=None), patch.object(transcribe, "transcribe", return_value=[{"w": "hi", "s": 0, "e": 1}]) as pt:
    s2._hear(chunk)
    check("live: no Whisper means the English model, as before", (s2.spoken, s2.whisper_ok, pt.called), ("en", False, True))
s3 = live.Session.__new__(live.Session)
s3.lock, s3.job, s3.spoken, s3.whisper_ok = threading.RLock(), {}, "hi", True
with patch.object(whisper, "transcribe", side_effect=RuntimeError("no")), patch.object(transcribe, "transcribe", return_value=[]) as pt:
    s3._hear(chunk)
    check("live: Whisper breaking falls back to the English model", (s3.whisper_ok, pt.called), (False, True))
s.said, s.last_said, s.settings, s.manual, s.last_trigger = None, -999.0, {"trigger_words": ""}, [], -999.0
s._triggers([{"w": "क्लिप", "s": 100.0, "e": 100.4}])
check("live: \"क्लिप\" (clip in Hindi) is heard as clip", bool(s.said))

# ---- English said in Hindi speech: back to English spelling, never "laiph"
from studio import roman
check("English words in Devanagari get their English spelling without the AI", roman.to_roman("माय लाइफ"), "my life")
check("the AI's English spelling of an English word is kept", (brain._sounds_same(roman.to_roman("मैकेनिक"), "mechanic"),
      brain._sounds_same("eksident", "accident"), brain._sounds_same("proparti", "property")), (True, True, True))
check("a translation is still refused", (brain._sounds_same("pani", "water"), brain._sounds_same("chuna", "lime")), (False, False))
with patch.object(brain, "ask_ai", return_value=(["Bhai", "my", "life", "kharab", "kar", "di"], "m", 0)):
    got = brain.fix_caption_words([{"w": x, "s": i, "e": i + 0.5} for i, x in enumerate(["भाई", "माय", "लाइफ", "खराब", "कर", "दी"])], lang="hi")
    check("Hinglish captions: Hindi in Roman letters, English as English", [w["w"] for w in got], ["Bhai", "my", "life", "kharab", "kar", "di"])

# ---- the webcam of a long video is looked for in a clip's own stretch (there is no whole video)
from studio import facecam
import pathlib
piece = pathlib.Path(tempfile.mkdtemp()) / "clip01.src.mp4"
piece.write_bytes(b"x")
with patch.object(facecam, "detect", return_value={"x": 1, "y": 2, "w": 300, "h": 170, "conf": "high"}) as det:
    check("the webcam is found in a clip's stretch", (jobs._facecam({"source_path": None}, str(piece)), det.call_args[0][0]), ([1, 2, 300, 170], str(piece)))
with patch.object(facecam, "detect", return_value={"x": 1, "y": 2, "w": 300, "h": 170, "conf": "low"}):
    check("an unsure webcam is not used", jobs._facecam({}, str(piece)), None)

if fails:
    print(f"{len(fails)} FAILED"); sys.exit(1)
print("ALL PASSED")
