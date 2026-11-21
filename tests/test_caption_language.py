"""English captions stay English: the language is told only from stretches where someone talks, by what Whisper
writes (Hindi in Hindi or Urdu letters, English in English letters), and each clip of a video taken for Hindi is
checked on its own sound, so an English clip (or a whole English stream heard wrong) is captioned by the English
model, never by the Hindi one.

This is the case that broke: an English stream with game noise in two of the three stretches listened to, where
Whisper named Urdu for the noise and the whole stream was taken for Hindi.

The speech models and the AI are replaced; ffmpeg runs for real. Nothing outside this machine is contacted."""
import os, subprocess, sys, tempfile
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-caplang-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_UPDATE_CHECK="0", CLIPKONTRAST_PUBLIC_URL="http://127.0.0.1:8765")
sys.path.insert(0, ".")
import numpy as np  # noqa: E402
from studio import brain, jobs, transcribe, whisper  # noqa: E402
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


EN = ({"en": 0.92, "hi": 0.03, "ur": 0.02}, " Oh my God, Jason, what are you doing over there?")
NOISE_UR = ({"ur": 0.78, "hi": 0.1, "en": 0.05}, "")                          # game sound: no words, Urdu named anyway
NOISE_HI = ({"hi": 0.6, "en": 0.2}, " ...")
check("an English stream with game noise in two stretches: English (the case that broke)", whisper.decide([EN, NOISE_UR, NOISE_HI])[0], "en")
DEVA = ({"hi": 0.8, "en": 0.15}, " अरे भाई ये क्या हो गया यार चलो")
check("Hindi, written in Hindi letters: Hindi", whisper.decide([DEVA, EN, DEVA])[0], "hi")
HINGLISH_EN_TOP = ({"en": 0.55, "hi": 0.4}, " भाई ये तो कमाल है bro what")
check("Hinglish where English came out on top, but Hindi was written: Hindi", whisper.decide([HINGLISH_EN_TOP, HINGLISH_EN_TOP, NOISE_UR])[0], "hi")
HI_LATIN = ({"hi": 0.5, "ur": 0.05, "en": 0.4}, " let's go let's go come on")
check("Whisper half-says Hindi but writes English: English", whisper.decide([HI_LATIN, EN])[0], "en")
check("one English, one Hindi stretch: English (the safer captions)", whisper.decide([EN, DEVA])[0], "en")
check("no talking anywhere, nothing clearly Hindi: not Hindi", whisper.decide([NOISE_HI, ({"ur": 0.3, "en": 0.3}, "")])[0], "en")


# ---- detect() reads what Whisper wrote, not just its guesses
class Seg:
    def __init__(self, text):
        self.text = text


class FakeInfo:
    def __init__(self, probs):
        self.all_language_probs = sorted(probs.items(), key=lambda kv: -kv[1])
        self.language, self.language_probability = self.all_language_probs[0]


class FakeModel:
    def __init__(self, answers):
        self.answers, self.i, self.kw = answers, 0, []

    def transcribe(self, audio, **kw):
        self.kw.append(kw)
        p, t = self.answers[self.i % len(self.answers)]
        self.i += 1
        return iter([Seg(t)] if t else []), FakeInfo(p)


whisper.installed = lambda: True
whisper.ENABLED = True
m = FakeModel([EN, NOISE_UR, NOISE_HI])
whisper._get = lambda note=None, name=None: m
audio = (np.random.RandomState(1).normal(0, 3000, 16000 * 200)).astype(np.int16)
check("detect: three stretches, what was written decides", (whisper.detect(audio)[0], m.i), ("en", 3))
check("...only a few words of each are written (quick)", all(k.get("max_new_tokens") == 40 for k in m.kw))
check("the video's language: English, not Hindi", jobs._detect_language({}, audio), "en")

# ---- each clip of a video taken for Hindi is checked on its own sound
work = Path(tempfile.mkdtemp(prefix="pc-caplang-work-"))
src = work / "s.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:size=320x180:rate=15", "-f", "lavfi", "-i",
                "sine=f=300:sample_rate=48000", "-t", "40", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)], check=True)
calls = {"lang": 0, "hinglish": 0, "english": 0}
whisper.clip_language = lambda a: (calls.__setitem__("lang", calls["lang"] + 1), lang_now[0])[1]
whisper.hinglish_ready = lambda: True


def fake_hinglish(a):
    calls["hinglish"] += 1
    return [{"w": w, "s": 1.0 + i * 0.4, "e": 1.3 + i * 0.4} for i, w in enumerate("bhai ye kya hai".split())]


def fake_parakeet(a, on_progress=None):
    calls["english"] += 1
    return [{"w": w, "s": 1.0 + i * 0.4, "e": 1.3 + i * 0.4} for i, w in enumerate("Oh my God, Jason?".split())]


whisper.hinglish = fake_hinglish
transcribe.transcribe = fake_parakeet
told = []
brain.english_captions = lambda raw, lang, *a, **k: (told.append(lang), raw)[1]
lang_now = ["en"]
job = {"id": "j", "dir": str(work), "lang": "hi", "options": {"caption_lang": "auto"}, "creator": None, "title": "t"}
hindi_words = [{"w": "ओ", "s": 11.0, "e": 11.3}, {"w": "माय", "s": 11.4, "e": 11.7}]
got = jobs._caption_words(job, {"id": "c1", "start": 10.0, "end": 25.0}, hindi_words, 0.0, src)
check("an English clip in a video taken for Hindi: captioned from the English model", [w["w"] for w in got], ["Oh", "my", "God,", "Jason?"])
check("...not the Hindi one", (calls["hinglish"], calls["english"]), (0, 1))
check("...and tidied as English", told[-1:], ["en"])
check("...timed on the video's clock", got[0]["s"], 10.0)
lang_now = ["hi"]
got = jobs._caption_words(job, {"id": "c2", "start": 10.0, "end": 25.0}, hindi_words, 0.0, src)
check("a Hindi clip: the Hinglish model", ([w["w"] for w in got], calls["hinglish"]), ("bhai ye kya hai".split(), 1))
clip = {"id": "c3", "start": 10.0, "end": 25.0}
lang_now = ["en"]
jobs._caption_words(job, clip, hindi_words, 0.0, src)
n = dict(calls)
jobs._caption_words(job, clip, hindi_words, 0.0, src)
check("remaking a clip (another style) doesn't listen again", (calls["lang"], calls["english"]), (n["lang"], n["english"]))
before = dict(calls)
en_job = dict(job, lang="en")
got = jobs._caption_words(en_job, {"id": "c4", "start": 10.0, "end": 25.0}, [{"w": "hello", "s": 11.0, "e": 11.5}], 0.0, src)
check("an English video (Whisper here): one quick look at the clip's language, then its own words, nothing heard again",
      ([w["w"] for w in got], calls["lang"] - before["lang"], calls["english"] - before["english"], calls["hinglish"] - before["hinglish"]),
      (["hello"], 1, 0, 0))
lang_now = ["hi"]
got = jobs._caption_words(en_job, {"id": "c6", "start": 10.0, "end": 25.0}, [{"w": "bro", "s": 11.0, "e": 11.5}], 0.0, src)
check("an 'English' video whose clip is Hindi (a Hinglish streamer heard wrong): the Hinglish model writes it",
      [w["w"] for w in got], "bhai ye kya hai".split())

# ---- the Hinglish model won't run on this computer: the clip is heard again by Hindi Whisper, word by word
def broken(a):
    raise RuntimeError("won't load")


whisper.hinglish = broken
heard_hi = []
whisper.transcribe = lambda a, lang=None, **k: (heard_hi.append(lang), [{"w": w, "s": 1.0 + i * 0.4, "e": 1.3 + i * 0.4}
                                                                        for i, w in enumerate("भाई ये क्या".split())])[1]
lang_now = ["hi"]
rough = [{"w": "रफ", "s": 10.0 + i, "e": 10.5 + i} for i in range(10)]          # a long video's quick pass, timings guessed
got = jobs._caption_words(job, {"id": "c5", "start": 10.0, "end": 25.0}, rough, 0.0, src)
check("Hinglish model broken: the clip is heard again by Hindi Whisper, not left to the quick rough pass",
      (heard_hi, [w["w"] for w in got]), (["hi"], ["bhai", "ye", "kya"]))

# ---- the main AI is the small free model on this computer (Ollama chosen in Settings)
from unittest.mock import patch  # noqa: E402
from studio import ai, config as _cfg  # noqa: E402
import importlib  # noqa: E402
real_brain = importlib.reload(brain)          # the real caption functions (replaced above for the clip tests)
asked_ai = []
words_en = [{"w": w, "s": i * 0.4, "e": i * 0.4 + 0.3} for i, w in enumerate("oh my god Jason what are you doing".split())]
with patch.object(ai, "provider", return_value="ollama"), patch.object(_cfg, "ai_ready", return_value=True), \
        patch.object(real_brain, "ask_ai", side_effect=lambda *a, **k: asked_ai.append(1) or (["X"] * len(words_en), "llama3.1", 1)):
    got = real_brain.fix_caption_words(words_en, "GTA", "en")
    check("Ollama as the main AI: English captions are the speech model's words, never rewritten by it",
          ([w["w"] for w in got], asked_ai), ("oh my god Jason what are you doing".split(), []))
    rated = []
    with patch.object(ai, "models", return_value=["llama3.1"]), \
            patch.object(real_brain, "_rate_locally", side_effect=lambda c, *a, **k: (rated.append(len(c)), (c, 5))[1]):
        db_ = np.full(600, -30.0, dtype=np.float32)
        db_[300:306] += 8
        wl = [{"w": "bro", "s": float(t), "e": t + 0.4} for t in range(0, 600, 2)]
        found, info = real_brain.find_clips(wl, db_, 600.0, "t", "u", max_clips=2, min_len=15, max_len=40, log=lambda m: None)
    check("...the moments: picked from the sound and the words, then scored by it a few at a time (not whole transcripts)",
          (bool(rated), asked_ai, info["model"], "free AI on this computer" in info["note"]), (True, [], "ollama:llama3.1", True))

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
