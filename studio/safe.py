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
    if re.search(r"live event has ended|This live event will begin|Premieres in|is_upcoming", text, re.I):
        return ("This live stream has just ended, and YouTube is still preparing its replay. Try again in an hour or two "
                "(a long stream can take longer). To clip a stream while it's live, use Clip a live stream instead.")
    return tools.explain(e) or _PATH.sub("[file]", text[-limit:])

