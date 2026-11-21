"""Checks the Hinglish caption model right after it is converted, before it is published.

Run by .github/workflows/hinglish-model.yml. The model maker's own sample recordings (from their model page, with the
text they say each one should give) are transcribed by the converted model through faster-whisper, exactly as
ClipKontrast will run it: on the CPU, int8, word timings on. It fails (and nothing is published) if the words come out
in Hindi script, if nothing comes out, if the words don't match the expected text closely enough, or if a word's
timing falls outside its recording.

    python packaging/hinglish_model_check.py <model folder> <Hugging Face repo> <revision>"""
import difflib
import re
import sys
import time

import soundfile as sf
from faster_whisper import WhisperModel
from huggingface_hub import hf_hub_download

folder, repo, rev = sys.argv[1], sys.argv[2], sys.argv[3]
# From the model page: what each recording should give.
SAMPLES = {
    "audios/c0637211-7384-4abc-af69-5aacf7549824_1_2629072_2656224.wav": "Mehnat to poora karte hain.",
    "audios/c0faba11-27ba-4837-a2eb-ccd67be07f40_1_3185088_3227568.wav": "Haan vahi dekh aapko bataen na.",
    "audios/663eb653-d6b5-4fda-b5f2-9ef98adc0a61_0_1098400_1118688.wav": "Aap pandrah log hain.",
    "audios/f5e0178c-354c-40c9-b3a7-687c86240a77_1_2613728_2630112.wav": "Thik hai saal ki.",
    "audios/f5e0178c-354c-40c9-b3a7-687c86240a77_1_1152496_1175488.wav": "Nahin, just thank you, thank you.",
    "audios/c0637211-7384-4abc-af69-5aacf7549824_1_2417088_2444224.wav": "Haan haan, dekhe hain.",
}
INDIC = re.compile(r"[ऀ-ॿ؀-ۿ]")
norm = lambda t: re.sub(r"[^a-z ]", "", t.lower()).split()     # noqa: E731

m = WhisperModel(folder, device="cpu", compute_type="int8")
fails, scores, heard_s, took_s = [], [], 0.0, 0.0
for path, want in SAMPLES.items():
    f = hf_hub_download(repo, path, revision=rev)
    audio, sr = sf.read(f, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != 16000:                                   # the samples are 16 kHz; anything else would be resampled here
        import numpy as np
        audio = np.interp(np.arange(0, len(audio), sr / 16000), np.arange(len(audio)), audio).astype("float32")
    dur = len(audio) / 16000
    t0 = time.time()
    segs, _ = m.transcribe(audio, language="en", task="transcribe", beam_size=1, word_timestamps=True,
                           vad_filter=False, condition_on_previous_text=False)
    words = [w for s in segs for w in (s.words or [])]
    took = time.time() - t0
    heard_s, took_s = heard_s + dur, took_s + took
    text = " ".join(w.word.strip() for w in words)
    score = difflib.SequenceMatcher(None, norm(text), norm(want)).ratio()
    scores.append(score)
    times = [(round(w.start, 2), round(w.end, 2)) for w in words]
    print(f"{dur:5.1f}s in {took:4.1f}s  match {score:.2f}  want: {want!r}\n                          got:  {text!r}\n"
          f"                          times: {times}")
    if not words:
        fails.append(f"{path}: nothing heard")
    if INDIC.search(text):
        fails.append(f"{path}: Hindi or Urdu script in {text!r}")
    if any(s < -0.05 or e > dur + 0.3 or e < s for s, e in times):
        fails.append(f"{path}: a word's timing is outside the recording: {times}")

avg = sum(scores) / len(scores)
print(f"\nAverage match {avg:.2f}. {heard_s:.0f}s of speech in {took_s:.1f}s ({heard_s / max(took_s, 0.01):.1f}x real time).")
if avg < 0.6:
    fails.append(f"the words match the expected text only {avg:.2f} on average")
if fails:
    print("\nFAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("PASSED")
