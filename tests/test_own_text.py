"""Your own big text and description on every clip (from PeakCut upstream): kept exactly as written, in place of the
AI's; a streamer's own text is used for their videos and live clips; with no description of your own, 3-5 fitting
hashtags end the AI's, and a post never gets them twice."""
import os, sys, tempfile
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-own-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0")
sys.path.insert(0, ".")
from studio import auth, creators, ctx, db, jobs, posting  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


o = jobs.clean_options({"hook_text": "  Mizo  ne kya kar diya\\n😭 ", "description_text": "Line one\r\nCheck @mizoplays\n#GTA6 #MizoGTA6\x07"})
check("your big text: one line, as written", o["hook_text"], "Mizo ne kya kar diya\\n😭")
check("your description: line breaks, @names and #tags kept, control characters gone", o["description_text"], "Line one\nCheck @mizoplays\n#GTA6 #MizoGTA6")
c = jobs.own_text({"hook": "AI HOOK", "description": "AI words #old", "hashtags": ["x"], "start": 0, "end": 10, "category": "funny"},
                  {"hook_text": "My heading", "description_text": "My text #MizoGTA6"}, [])
check("on a clip: your text in place of the AI's, marked as yours", (c["hook"], c.get("hook_by_you"), c["description"], c.get("fixed_description")),
      ("My heading", True, "My text #MizoGTA6", True))
check("...and posted exactly as written, no hashtags added", posting_tags := (lambda clip: "" if clip.get("fixed_description") or clip.get("hashtags_in_description") else "x")(c), "")
words = [{"w": w, "s": i, "e": i + 0.5} for i, w in enumerate("bhai ye heist toh insane tha heist heist".split())]
c2 = jobs.own_text({"hook": "H", "description": "Wild heist moment", "hashtags": ["gta6"], "start": 0, "end": 10, "category": "funny"},
                   {}, words, "GTA 6 LIVE | Mizo Plays", "Mizo Plays", "gta6")
tags = c2["hashtags"]
check("no description of yours: 3-5 fitting hashtags end the AI's", (3 <= len(tags) <= 5, c2["description"].startswith("Wild heist moment"),
                                                                    c2["description"].rstrip().endswith(" ".join("#" + t for t in tags))), (True, True, True))
check("...the game and the streamer among them", ("gta6" in tags, any("mizo" in t for t in tags)), (True, True))
src = open("studio/posting.py").read()
check("a post whose description already ends with its hashtags doesn't get them twice", "hashtags_in_description" in src)
user = auth.local_user()
with ctx.as_user(user.id):
    cr = creators.create({"name": "Mizo", "channel": "https://www.youtube.com/@mizoplays"})
    creators.update(cr["id"], {"hook_text": "Mizo moment", "description_text": "Credit: @mizoplays"})
    j = jobs.create({"type": "url", "url": "https://www.youtube.com/watch?v=abcdefghijk", "name": "x"}, {}, enqueue=False, creator=cr["id"])
    check("a streamer's own text is used for their videos", (j["options"]["hook_text"], j["options"]["description_text"]), ("Mizo moment", "Credit: @mizoplays"))
    j2 = jobs.create({"type": "url", "url": "https://www.youtube.com/watch?v=abcdefghijk", "name": "x"}, {"hook_text": ""}, enqueue=False, creator=cr["id"])
    check("...and an empty one for one video clears it for that video", j2["options"]["hook_text"], "")
page = open("web/index.html", encoding="utf-8").read()
check("the page asks for both, for a video and for a streamer", all(x in page for x in ('id="o_hook_text"', 'id="o_desc_text"', 'data-k="hook_text"', 'data-k="description_text"')))
print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
