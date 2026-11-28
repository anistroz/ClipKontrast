"""Earn's account check for a clipper with different handles on each platform (report #178): a YouTube channel that
goes by their Instagram handle, or whose name is their YouTube handle in capitals, is theirs; a stranger's is not."""
import os, sys, tempfile
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-handles-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="1",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_UPDATE_CHECK="0")
sys.path.insert(0, ".")
fails = []


def check(name, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"   got {got!r}"))
    ok or fails.append(name)


# ---- a clipper with different handles on each platform (report #178): their YouTube channel goes by their Instagram
# handle, or its name is their YouTube handle in capitals; a channel that is none of theirs is still refused
from types import SimpleNamespace as _NS
from studio import earn as _earn
_camp = _NS(required_tag="", starts_at=0)
_prof = {"youtube": "@vicexcitygaming", "instagram": "@vcx6gaming", "tiktok": "@vice.cityxgaming", "x": ""}
_info = lambda ch, cid="UCabc": {"title": "t", "channel": ch, "channel_id": cid, "posted_at": 0, "text": "", "views": 0}  # noqa: E731
_real_h = _earn._yt_handle
_earn._yt_handle = lambda cid: "@vcx6gaming"
check("a YouTube clip on a channel that goes by the clipper's Instagram handle is theirs",
      _earn._check(_camp, {"platform": "youtube", "id": "x", "handle": ""}, _prof, _info("VCX"))["owner"], True)
_earn._yt_handle = lambda cid: ""
check("...and one whose channel name is their YouTube handle in capitals",
      _earn._check(_camp, {"platform": "youtube", "id": "x", "handle": ""}, _prof, _info("VICEXCITYGAMING"))["owner"], True)
_earn._yt_handle = lambda cid: "@someoneelse"
check("...but a channel that is none of theirs is still refused",
      _earn._check(_camp, {"platform": "youtube", "id": "x", "handle": ""}, _prof, _info("Someone Else"))["owner"], False)
check("a TikTok from their own TikTok handle is theirs",
      _earn._check(_camp, {"platform": "tiktok", "id": "1", "handle": "@vice.cityxgaming"}, _prof)["owner"], True)
check("...and one from someone else's isn't",
      _earn._check(_camp, {"platform": "tiktok", "id": "1", "handle": "@stranger"}, _prof)["owner"], False)
_earn._yt_handle = _real_h

print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
