"""Levels, badges and the weekly leaderboard of Earn: what makes clippers want to do better.

Every clipper has a level. A new one is a Starter. To clip the premium campaigns they apply once (their page, a
link to a recording of their last 28 days of insights, their best edit); the team looks and approves them, usually
as Silver. From there the level goes up by itself as their clips do well, and a higher level is paid more per 1,000
views on premium campaigns:

    Silver  where approved clippers start
    Gold    3 clips past 50K views in a calendar month
    Elite   one clip past 5 lakh views, or 5 clips past 1 lakh (25 places)

Only views that were checked count: a clip's views as approved by the team, after its days on hold. Levels never go
down by themselves; the team can move someone down (for botted views, say). Badges and the weekly top 10 come from
the same checked views, so nothing here can be had by sending in clips nobody watched."""
import os
import re
import time
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from . import db

LEVELS = ("silver", "gold", "elite")
NAMES = {"starter": "Starter", "silver": "Silver", "gold": "Gold", "elite": "Elite"}
ICONS = {"starter": "🌱", "silver": "🥈", "gold": "🥇", "elite": "💎"}
DEFAULT_RATES = (50.0, 75.0, 100.0)             # per 1,000 views at Silver, Gold, Elite, when no campaign says otherwise
GOLD_CLIPS, GOLD_VIEWS = 3, 50_000              # in one calendar month
ELITE_ONE, ELITE_CLIPS, ELITE_EACH = 500_000, 5, 100_000
ELITE_SLOTS = int(os.environ.get("CLIPKONTRAST_ELITE_SLOTS") or 25)
REAPPLY_DAYS = 7
NICHES = {"gaming": "Gaming and streamers", "podcast": "Podcasts and talk", "irl": "IRL and vlogs", "sports": "Sports",
          "memes": "Memes and edits", "other": "Something else"}
PAGE_HOSTS = ("instagram.com", "youtube.com", "youtu.be", "x.com", "twitter.com", "tiktok.com")
IST = timezone(timedelta(hours=5, minutes=30))
BADGES = [  # key, icon, name, what it takes
    ("approved", "✅", "Approved", "Approved for premium"),
    ("first_clip", "🎯", "First clip", "A clip paid for"),
    ("viral", "🔥", "First viral", "A clip past 1 lakh"),
    ("lakh5", "🚀", "5 lakh", "A clip past 5 lakh"),
    ("million", "👑", "1M club", "A clip past 10 lakh"),
    ("top10", "🏆", "Top 10", "In a week's top 10"),
    ("hattrick", "⚡", "Hat-trick", "3 clips past 1 lakh in a month"),
    ("elite", "💎", "Elite", f"One of {ELITE_SLOTS}"),
]


class LevelError(Exception):
    pass


def _now() -> float:
    return time.time()


def month_start(t: float = None) -> float:
    d = datetime.fromtimestamp(t or _now(), IST)
    return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


def week_start(t: float = None) -> float:
    """Monday 00:00, India time: the weekly leaderboard starts again then."""
    d = datetime.fromtimestamp(t or _now(), IST)
    return (d - timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _row(c, uid: str):
    return c.execute(sa.select(db.earn_levels).where(db.earn_levels.c.user_id == uid)).first()


def level_of(row) -> str:
    """starter, or the level of an approved clipper."""
    return row.level if row is not None and row.status == "approved" and row.level in LEVELS else "starter"


def levels_map(c, uids) -> dict:
    """{user id: level} for many clippers at once (starter for those not approved)."""
    uids = list({u for u in uids if u})
    if not uids:
        return {}
    out = {u: "starter" for u in uids}
    for r in c.execute(sa.select(db.earn_levels).where(db.earn_levels.c.user_id.in_(uids))):
        out[r.user_id] = level_of(r)
    return out


def rates() -> tuple:
    """Silver, Gold and Elite rates as clippers see them: those of the premium campaign taking clips, else the defaults."""
    c_ = db.earn_campaigns.c
    with db.engine.connect() as c:
        r = c.execute(sa.select(c_.tier_rates).where(c_.premium.is_(True), c_.status == "live").order_by(c_.sort_order)).first()
    return parse_rates(r[0]) if r and r[0] else DEFAULT_RATES


def parse_rates(v) -> tuple:
    try:
        x = tuple(float(p) for p in str(v or "").split(",") if p.strip())
    except ValueError:
        return DEFAULT_RATES
    return x if len(x) == 3 else DEFAULT_RATES


def rate_for(camp, level: str) -> float:
    """What one clip of a clipper at this level earns per 1,000 views in this campaign."""
    if not getattr(camp, "premium", False):
        return camp.rate_per_1k
    r = parse_rates(camp.tier_rates) if camp.tier_rates else DEFAULT_RATES
    return r[LEVELS.index(level)] if level in LEVELS else r[0]


# ---------------------------------------------------------------- checked clips, and what they add up to
def _checked(c, uids) -> dict:
    """{user id: [(views, approved at), ...]} of the clips the team approved (their views are the checked ones)."""
    s = db.earn_submissions.c
    out = {u: [] for u in uids}
    if not uids:
        return out
    for uid, v, at, sub in c.execute(sa.select(s.user_id, s.views, s.reviewed_at, s.submitted_at)
                                     .where(s.user_id.in_(list(uids)), s.status.in_(("approved", "paid")))):
        out.setdefault(uid, []).append((int(v or 0), at or sub or 0.0))
    return out


def _earned_level(clips: list, now: float = None) -> str:
    m0 = month_start(now)
    if any(v >= ELITE_ONE for v, _ in clips) or sum(1 for v, _ in clips if v >= ELITE_EACH) >= ELITE_CLIPS:
        return "elite"
    if sum(1 for v, at in clips if v >= GOLD_VIEWS and at >= m0) >= GOLD_CLIPS:
        return "gold"
    return "silver"


_TOP10 = {"at": 0.0, "users": set(), "first": {}}


def top10_users() -> dict:
    """Who has been in a finished week's top 10, and when first: {user id: week start}. Worked out every few minutes."""
    if _now() - _TOP10["at"] < 300:
        return _TOP10["first"]
    s = db.earn_submissions.c
    this_week = week_start()
    weeks: dict = {}
    with db.engine.connect() as c:
        for uid, v, at in c.execute(sa.select(s.user_id, s.views, s.reviewed_at).where(s.status.in_(("approved", "paid")), s.reviewed_at.isnot(None))):
            w = week_start(at)
            if w >= this_week:
                continue
            weeks.setdefault(w, {}).setdefault(uid, 0)
            weeks[w][uid] += int(v or 0)
    first = {}
    for w in sorted(weeks):
        for uid, _v in sorted(weeks[w].items(), key=lambda x: -x[1])[:10]:
            first.setdefault(uid, w)
    _TOP10.update(at=_now(), first=first)
    return first


def badges(level: str, clips: list, uid: str = "", top: dict = None) -> list:
    """Every badge, earned or not, with when (for "new")."""
    now = _now()
    top = top if top is not None else top10_users()
    def first_at(cond):
        ts = [at for v, at in clips if cond(v)]
        return min(ts) if ts else None
    by_month: dict = {}
    for v, at in clips:
        if v >= ELITE_EACH:
            k = datetime.fromtimestamp(at, IST).strftime("%Y-%m")
            by_month.setdefault(k, []).append(at)
    hat = min((sorted(a)[2] for a in by_month.values() if len(a) >= 3), default=None)
    when = {"approved": 0.0 if level != "starter" else None, "first_clip": first_at(lambda v: True),
            "viral": first_at(lambda v: v >= 100_000), "lakh5": first_at(lambda v: v >= 500_000),
            "million": first_at(lambda v: v >= 1_000_000), "top10": top.get(uid), "hattrick": hat,
            "elite": 0.0 if level == "elite" else None}
    return [{"key": k, "icon": i, "name": n, "what": w, "earned": when[k] is not None,
             "new": bool(when[k]) and now - when[k] < 7 * 86400} for k, i, n, w in BADGES]


# ---------------------------------------------------------------- what a clipper sees about themselves
def info(uid: str) -> dict:
    with db.engine.connect() as c:
        row = _row(c, uid)
        clips = _checked(c, [uid])[uid]
        elite_used = c.execute(sa.select(sa.func.count()).select_from(db.earn_levels).where(
            db.earn_levels.c.status == "approved", db.earn_levels.c.level == "elite")).scalar() or 0
    lv = level_of(row)
    rt = rates()
    m0 = month_start()
    gold_n = sum(1 for v, at in clips if v >= GOLD_VIEWS and at >= m0)
    best = max((v for v, _ in clips), default=0)
    lakh_n = sum(1 for v, _ in clips if v >= ELITE_EACH)
    nxt = None
    if lv == "starter":
        nxt = {"level": "silver", "name": "Silver", "rate": rt[0], "steps": [
            {"label": "Apply with your page, a recording of your insights and your best edit", "have": 1 if row and row.status in ("pending", "approved") else 0, "need": 1},
            {"label": "The team reviews it (usually within 2 days)", "have": 1 if row and row.status == "approved" else 0, "need": 1}]}
    elif lv == "silver":
        nxt = {"level": "gold", "name": "Gold", "rate": rt[1], "resets": "on the 1st",
               "steps": [{"label": f"Clips past {GOLD_VIEWS // 1000}K views this month", "have": min(gold_n, GOLD_CLIPS), "need": GOLD_CLIPS}]}
    elif lv == "gold":
        nxt = {"level": "elite", "name": "Elite", "rate": rt[2], "either": True, "slots_left": max(0, ELITE_SLOTS - elite_used),
               "steps": [{"label": "One clip past 5 lakh views (your best so far)", "have": min(best, ELITE_ONE), "need": ELITE_ONE, "views": True},
                         {"label": "Or: clips past 1 lakh views", "have": min(lakh_n, ELITE_CLIPS), "need": ELITE_CLIPS}]}
    app = None
    if row is not None:
        app = {"status": row.status, "page_url": row.page_url, "recording_url": row.recording_url, "sample_url": row.sample_url,
               "niche": row.niche, "followers": row.followers, "avg_views": row.avg_views, "note": row.note,
               "review_note": row.review_note, "applied_at": row.applied_at, "reviewed_at": row.reviewed_at,
               "reapply_at": (row.reviewed_at or 0) + REAPPLY_DAYS * 86400 if row.status == "rejected" else None}
    return {"level": lv, "name": NAMES[lv], "icon": ICONS[lv], "rate": rt[LEVELS.index(lv)] if lv in LEVELS else None,
            "rates": {"silver": rt[0], "gold": rt[1], "elite": rt[2]}, "next": nxt, "application": app,
            "badges": badges(lv, clips, uid), "stats": {"clips": len(clips), "best": best, "views": sum(v for v, _ in clips)},
            "rules": {"gold": f"{GOLD_CLIPS} clips past {GOLD_VIEWS // 1000}K views in a month",
                      "elite": f"a clip past 5 lakh, or {ELITE_CLIPS} clips past 1 lakh", "elite_slots": ELITE_SLOTS},
            "niches": NICHES}


# ---------------------------------------------------------------- applying, and the team's answer
def _link(v, name, hosts=None) -> str:
    v = str(v or "").strip()[:300]
    if v and not re.match(r"https?://", v, re.I):
        v = "https://" + v
    m = re.fullmatch(r"https?://(?:www\.|m\.)?([\w.-]+\.[a-z]{2,})(/\S*)?", v, re.I)
    if not m:
        raise LevelError(f"{name}: paste a link, like https://…")
    if hosts and not any(m.group(1).lower() == h or m.group(1).lower().endswith("." + h) for h in hosts):
        raise LevelError(f"{name}: a link to your Instagram, YouTube, X or TikTok page.")
    return v


def _int(v, name) -> int:
    try:
        n = int(float(str(v or 0).replace(",", "").strip() or 0))
    except ValueError:
        raise LevelError(f"{name}: a number, please.")
    if n < 0 or n > 5_000_000_000:
        raise LevelError(f"{name}: that number doesn't look right.")
    return n


def apply(uid: str, data: dict) -> dict:
    vals = {"page_url": _link(data.get("page_url"), "Your page", PAGE_HOSTS),
            "recording_url": _link(data.get("recording_url"), "The recording of your insights"),
            "sample_url": _link(data.get("sample_url"), "Your best edit"),
            "niche": data.get("niche") if data.get("niche") in NICHES else "gaming",
            "followers": _int(data.get("followers"), "Followers"), "avg_views": _int(data.get("avg_views"), "Average views"),
            "note": re.sub(r"[<>]", "", str(data.get("note") or "")).strip()[:300]}
    now = _now()
    with db.engine.begin() as c:
        row = _row(c, uid)
        if row is not None and row.status == "approved":
            raise LevelError("You're already approved.")
        if row is not None and row.status == "rejected" and now < (row.reviewed_at or 0) + REAPPLY_DAYS * 86400:
            when = datetime.fromtimestamp((row.reviewed_at or 0) + REAPPLY_DAYS * 86400, IST).strftime("%d %b")
            raise LevelError(f"You can apply again from {when}. Use the time to post a few strong clips.")
        vals.update(status="pending", applied_at=now if row is None or row.status != "pending" else row.applied_at,
                    review_note="", updated_at=now)
        if row is None:
            c.execute(db.earn_levels.insert().values(user_id=uid, **vals))
        else:
            c.execute(db.earn_levels.update().where(db.earn_levels.c.user_id == uid).values(**vals))
    return info(uid)


def applications(status: str = "pending") -> dict:
    lv, u, p = db.earn_levels.c, db.users.c, db.earn_profiles.c
    q = (sa.select(db.earn_levels, u.email, p.display_name, p.instagram, p.youtube)
         .select_from(db.earn_levels.join(db.users, u.id == lv.user_id).outerjoin(db.earn_profiles, p.user_id == lv.user_id)))
    if status in ("pending", "approved", "rejected"):
        q = q.where(lv.status == status)
    with db.engine.connect() as c:
        rows = c.execute(q.order_by(lv.applied_at.desc()).limit(1000)).all()
        clips = _checked(c, [r.user_id for r in rows])
        counts = dict(c.execute(sa.select(lv.status, sa.func.count()).group_by(lv.status)).all())
        elite_used = c.execute(sa.select(sa.func.count()).select_from(db.earn_levels).where(lv.status == "approved", lv.level == "elite")).scalar() or 0
    items = []
    for r in rows:
        m, cl = r._mapping, clips.get(r.user_id, [])
        items.append({"user_id": r.user_id, "email": m["email"], "name": m["display_name"] or "", "status": r.status,
                      "level": r.level if r.status == "approved" else "", "page_url": r.page_url, "recording_url": r.recording_url,
                      "sample_url": r.sample_url, "niche": NICHES.get(r.niche, r.niche), "followers": r.followers,
                      "avg_views": r.avg_views, "note": r.note, "review_note": r.review_note, "applied_at": r.applied_at,
                      "reviewed_at": r.reviewed_at, "checked_clips": len(cl), "best": max((v for v, _ in cl), default=0),
                      "earned_level": _earned_level(cl)})
    return {"items": items, "counts": {k: counts.get(k, 0) for k in ("pending", "approved", "rejected")},
            "elite_used": elite_used, "elite_slots": ELITE_SLOTS}


def decide(uid: str, action: str, level: str = "silver", note: str = "", admin_id: str = "") -> dict:
    """approve (at a level) | level (move an approved clipper) | reject (with a reason)."""
    from . import earn
    note = re.sub(r"[<>]", "", note or "").strip()[:300]
    now = _now()
    with db.engine.begin() as c:
        row = _row(c, uid)
        if row is None:
            raise LevelError("That clipper hasn't applied.")
        if action in ("approve", "level"):
            if level not in LEVELS:
                raise LevelError("Pick Silver, Gold or Elite.")
            if action == "level" and row.status != "approved":
                raise LevelError("Approve them first.")
            c.execute(db.earn_levels.update().where(db.earn_levels.c.user_id == uid).values(
                status="approved", level=level, review_note=note, reviewed_at=now, reviewer=admin_id, updated_at=now))
        elif action == "reject":
            c.execute(db.earn_levels.update().where(db.earn_levels.c.user_id == uid).values(
                status="rejected", review_note=note or "Not yet: your page and edits need to get more views first.",
                reviewed_at=now, reviewer=admin_id, updated_at=now))
        else:
            raise LevelError("Unknown action.")
    rt = rates()
    if action == "approve":
        earn._notify(uid, f"You're approved: {NAMES[level]} {ICONS[level]}",
                     f"You can join the premium campaigns now, at ₹{rt[LEVELS.index(level)]:g} per 1,000 views. Do well and you move up.")
        promote(uid)
    elif action == "level":
        earn._notify(uid, f"Your level is now {NAMES[level]} {ICONS[level]}",
                     note or f"₹{rt[LEVELS.index(level)]:g} per 1,000 views on premium campaigns.")
    else:
        earn._notify(uid, "Your premium application", (note or "Not yet: your page and edits need to get more views first.")
                     + f" You can apply again in {REAPPLY_DAYS} days.")
    return info(uid)


def promote(uid: str):
    """After a clip is approved: up a level if the clipper's checked clips now earn it (never down). Elite has places."""
    now = _now()
    with db.engine.begin() as c:
        row = _row(c, uid)
        if row is None or row.status != "approved":
            return None
        want = _earned_level(_checked(c, [uid])[uid], now)
        if LEVELS.index(want) <= LEVELS.index(row.level if row.level in LEVELS else "silver"):
            return None
        if want == "elite":
            used = c.execute(sa.select(sa.func.count()).select_from(db.earn_levels).where(
                db.earn_levels.c.status == "approved", db.earn_levels.c.level == "elite")).scalar() or 0
            if used >= ELITE_SLOTS:
                want = "gold" if row.level == "silver" else None
            if not want or LEVELS.index(want) <= LEVELS.index(row.level):
                return None
        c.execute(db.earn_levels.update().where(db.earn_levels.c.user_id == uid).values(level=want, updated_at=now))
    from . import earn
    rt = rates()
    earn._notify(uid, f"Level up: you're {NAMES[want]} {ICONS[want]}",
                 f"Your clips did it. Premium campaigns now pay you ₹{rt[LEVELS.index(want)]:g} per 1,000 views.")
    return want


# ---------------------------------------------------------------- this week's top clippers
def weekly_board(limit: int = 10) -> dict:
    """This week's top clippers by checked views (clips approved since Monday), with their level and badges."""
    from . import earn
    s, p, u = db.earn_submissions.c, db.earn_profiles.c, db.users.c
    w0 = week_start()
    views = sa.func.sum(s.views)
    q = (sa.select(s.user_id, views, sa.func.max(s.views), sa.func.count(), p.display_name, u.email)
         .select_from(db.earn_submissions.join(db.users, u.id == s.user_id).outerjoin(db.earn_profiles, p.user_id == s.user_id))
         .where(s.status.in_(("approved", "paid")), s.reviewed_at >= w0)
         .group_by(s.user_id, p.display_name, u.email).having(views > 0).order_by(views.desc()).limit(limit))
    with db.engine.connect() as c:
        rows = c.execute(q).all()
        uids = [r[0] for r in rows]
        lv = levels_map(c, uids)
        clips = _checked(c, uids)
    top = top10_users()
    out = []
    for i, (uid, v, best, n, dn, email) in enumerate(rows):
        b = [x["icon"] for x in badges(lv.get(uid, "starter"), clips.get(uid, []), uid, top) if x["earned"] and x["key"] not in ("approved", "first_clip")]
        out.append({"rank": i + 1, "name": earn._public_name(dn or "", email), "level": lv.get(uid, "starter"),
                    "level_name": NAMES[lv.get(uid, "starter")], "views": int(v or 0), "best": int(best or 0), "clips": n,
                    "badges": b, "uid": uid})
    return {"since": w0, "ends": w0 + 7 * 86400, "rows": out}
