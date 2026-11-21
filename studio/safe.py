"""Small helpers for what is safe to show a user."""
import re

_PATH = re.compile(r"(?:[A-Za-z]:)?[\\/][^\s'\"]*[\\/][^\s'\"]+")


def friendly(e, limit=600) -> str:
    """An error message for the user: trimmed, with any server file paths removed. A missing ffmpeg, which Windows
    reports only as "the system cannot find the file specified", is said in plain words with what to do."""
    from . import tools
    text = str(e)
    if isinstance(e, MemoryError) or re.search(r"allocate memory|bad_alloc|out of memory|MemoryError|Unable to allocate", text, re.I):
        return ("Your computer ran out of memory while working on this video. Close other programs (browser tabs, "
                "games), then try again. ClipKontrast needs about 4 GB of free memory; a long stream needs more.")
    if re.search(r"WinError 4551|Application Control policy", text, re.I):
        return ("Windows blocked one of ClipKontrast's files (Smart App Control, which stops apps that aren't signed "
                "yet). Open Windows Security, App & browser control, Smart App Control settings, and turn it off; or add "
                "ClipKontrast's folder to the exclusions of your antivirus. Then restart ClipKontrast and try again.")
    if re.search(r"WinError (5|32)\b|Access is denied|being used by another process", text, re.I):
        return ("Another program was holding one of ClipKontrast's files (usually an antivirus scanning it). Try again; "
                "if it keeps happening, add ClipKontrast's folders to your antivirus's exclusions: the app's own "
                "folder and the folder your videos and clips are kept in (Settings, Storage).")
    # Only YouTube's own answer counts, not a note one of the other ways of asking left behind it ("(tried 5 ways) (...)").
    main = text.split(" (tried ", 1)[0]
    if re.search(r"This live event will begin|Premieres in|is_upcoming", main, re.I):
        return "This stream or premiere hasn't started yet. Clip it once it's live (Clip a live stream), or after it's over."
    if re.search(r"live event has ended|live stream recording is not available|post.live", main, re.I):
        return POST_LIVE
    return tools.explain(e) or _PATH.sub("[file]", text[-limit:])


POST_LIVE = ("YouTube hasn't made this stream's replay available yet, so it can't be downloaded. After a long stream YouTube "
             "can take many hours to finish the replay, and for a stream of 12 hours or more it may keep only part of it, "
             "or none. What works now: upload the video file instead (the raw stream or clips from Drive), or clip it "
             "live next time with Clip a live stream.")

