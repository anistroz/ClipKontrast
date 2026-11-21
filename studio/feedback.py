"""Bug reports, feature ideas and other messages from users, read by admins in the admin dashboard."""
import io
import re
import time

import sqlalchemy as sa

from . import config, db, notices

KINDS = {"bug": "Bug report", "idea": "Feature idea", "other": "Message"}
STATUSES = ("new", "seen", "done")


class Refused(ValueError):
    pass


def submit(uid: str, kind: str, message: str, page: str = "", context: str = "") -> dict:
    kind = kind if kind in KINDS else "other"
    message = (message or "").strip()
    if len(message) < 3:
        raise Refused("Write a few words so we know what you mean.")
    if len(message) > 4000:
        raise Refused("That's a bit long. Keep it under 4,000 characters.")
    now = time.time()
    with db.engine.begin() as c:
        fid = c.execute(db.feedback.insert().values(user_id=uid, t=now, kind=kind, message=message,
                                                    page=(page or "")[:200], context=(context or "")[:1000],
                                                    status="new", updated_at=now)).inserted_primary_key[0]
        who = c.execute(sa.select(db.users.c.email).where(db.users.c.id == uid)).scalar() or "someone"
        admins = [r[0] for r in c.execute(sa.select(db.users.c.id).where(db.users.c.is_admin == sa.true(),
                                                                         db.users.c.disabled == sa.false()))]
        for a in admins:
            notices.add(a, "feedback", f"New {KINDS[kind].lower()} from {who}", message[:140], "/admin/feedback", conn=c)
    return {"id": fid}


def submit_report(message: str, steps: str = "", contact: str = "", app: str = "", diag: str = "", context: str = "",
                  source: str = "app", screenshot: bytes = b"", uid: str = None) -> dict:
    """A bug report from the clip maker (any computer, no account needed) or the website. The screenshot, if any, is
    opened and saved again as plain pixels, so nothing but a picture is ever kept. Admins get a notice and an email."""
    message = (message or "").strip()
    if len(message) < 3:
        raise Refused("Write a few words about what went wrong.")
    if len(message) > 4000 or len(steps or "") > 4000:
        raise Refused("That's a bit long. Keep it under 4,000 characters.")
    clean = lambda v, n: re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(v or ""))[:n].strip()   # noqa: E731
    full = message + ("\n\nWhat they were doing:\n" + steps.strip() if (steps or "").strip() else "")
    pic = None
    if screenshot:
        pic = _picture(screenshot)
    now = time.time()
    with db.engine.begin() as c:
        fid = c.execute(db.feedback.insert().values(user_id=uid, t=now, kind="bug", message=full[:8500], page=source[:20],
                                                    context=clean(context, 1000), status="new", updated_at=now,
                                                    source=clean(source, 20), contact=clean(contact, 200),
                                                    app=clean(app, 200), diag=clean(diag, 20000),
                                                    shot=1 if pic else 0)).inserted_primary_key[0]
        admins = [(r[0], r[1]) for r in c.execute(sa.select(db.users.c.id, db.users.c.email).where(
            db.users.c.is_admin == sa.true(), db.users.c.disabled == sa.false()))]
        for a, _email in admins:
            notices.add(a, "feedback", f"New bug report #{fid}", message[:140], "/admin/earn/bugs", conn=c)
    if pic:
        SHOTS.mkdir(parents=True, exist_ok=True)
        pic.save(SHOTS / f"{fid}.jpg", "JPEG", quality=82, optimize=True)
    _email_admins(fid, message, source, contact, [e for _a, e in admins])
    return {"id": fid}


SHOTS = config.DATA_DIR / "bug-shots"


def _picture(data: bytes):
    from PIL import Image, ImageOps
    if len(data) > 6 * 1024 * 1024:
        raise Refused("That screenshot is too big. The limit is 6 MB.")
    try:
        im = Image.open(io.BytesIO(data))
        if im.format not in ("PNG", "JPEG", "WEBP") or im.width * im.height > 40_000_000:
            raise Refused("The screenshot must be a PNG or JPG picture.")
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((2000, 2000))
        return im
    except Refused:
        raise
    except Exception:  # noqa: BLE001 - anything Pillow can't read is not a picture
        raise Refused("The screenshot must be a PNG or JPG picture.")


def _email_admins(fid: int, message: str, source: str, contact: str, emails: list):
    try:
        from . import mailer
        for to in emails[:5]:
            mailer.send(to, f"Bug report #{fid} ({source})", "A new bug report",
                        (message[:600] + ("\n\nContact: " + contact if contact else "")),
                        "Open bug reports", config.PUBLIC_URL + "/admin/earn/bugs", "")
    except Exception:  # noqa: BLE001 - the report is saved whatever the mail does
        pass


def shot_path(fid: int):
    p = SHOTS / f"{int(fid)}.jpg"
    return p if p.is_file() else None


def listing(status: str = "") -> dict:
    f, u = db.feedback.c, db.users.c
    q = (sa.select(db.feedback, u.email, u.name).select_from(db.feedback.outerjoin(db.users, u.id == f.user_id))
         .order_by(f.t.desc()).limit(300))
    if status in STATUSES:
        q = q.where(f.status == status)
    with db.engine.connect() as c:
        rows = c.execute(q).all()
        counts = dict(c.execute(sa.select(f.status, sa.func.count()).group_by(f.status)).all())
    return {"items": [{"id": r.id, "t": r._mapping["t"], "kind": r.kind, "message": r.message, "page": r.page,
                       "context": r.context, "status": r.status, "email": r.email or "", "name": r.name or "",
                       "source": r.source, "contact": r.contact, "app": r.app, "diag": r.diag, "shot": bool(r.shot)}
                      for r in rows],
            "counts": {s: int(counts.get(s, 0)) for s in STATUSES}}


CSV_COLUMNS = ("id", "date", "status", "source", "kind", "name", "email", "contact", "app", "page", "context", "message",
               "technical_details", "screenshot")


def _cell(v) -> str:
    """One CSV cell: text a spreadsheet would run as a formula (=, +, -, @ at the start) is kept as text, and nothing
    is longer than a spreadsheet cell can hold."""
    s = str(v if v is not None else "")
    if s[:1] in ("=", "+", "-", "@", "\t", "\r"):
        s = "'" + s
    return s[:32000]


def csv_text(status: str = "") -> str:
    """Every report (or every one with this status), newest first, as CSV: to hand over in one go."""
    import csv
    import io
    f, u = db.feedback.c, db.users.c
    q = (sa.select(db.feedback, u.email, u.name).select_from(db.feedback.outerjoin(db.users, u.id == f.user_id))
         .order_by(f.t.desc()))
    if status in STATUSES:
        q = q.where(f.status == status)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(CSV_COLUMNS)
    with db.engine.connect() as c:
        for r in c.execute(q):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(r._mapping["t"]))
            w.writerow([_cell(x) for x in (r.id, when, r.status, r.source, r.kind, r.name or "", r.email or "", r.contact,
                                            r.app, r.page, r.context, r.message, r.diag, "yes" if r.shot else "no")])
    return "\ufeff" + out.getvalue()          # the mark Excel needs to read the letters of every language right


def set_status(fid: int, status: str):
    if status not in STATUSES:
        raise Refused("Unknown status.")
    with db.engine.begin() as c:
        done = c.execute(db.feedback.update().where(db.feedback.c.id == fid).values(status=status, updated_at=time.time()))
        if done.rowcount != 1:
            raise Refused("That message no longer exists.")
