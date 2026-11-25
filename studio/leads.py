"""Launch a campaign: creators, streamers, brands and agencies ask to run a paid clipping campaign.

A request is saved, the admins are told (the bell and an email), and they take it from there: they talk to the
person, take the budget, and make the campaign from the request in the Earn admin. Nothing is published by a request
on its own. The pricing shown on the page (the minimum budget and ClipKontrast's management fee) is set here."""
import re
import time

import sqlalchemy as sa

from . import config, db

STATUSES = ("new", "contacted", "won", "lost")
ROLES = {"creator": "Creator / streamer", "brand": "Brand", "agency": "Agency"}
PLATFORMS = {"youtube": "YouTube Shorts", "instagram": "Instagram Reels", "x": "X", "tiktok": "TikTok"}
CATEGORIES = ("Gaming", "IRL / Vlogs", "Podcast", "Sports", "Music", "Brand / Product", "Other")
_EMAIL = re.compile(r"^[^@\s<>\"']{1,64}@[^@\s<>\"']+\.[A-Za-z]{2,}$")


class Refused(Exception):
    pass


def pricing() -> dict:
    """What the page shows: the minimum budget and the management fee (verification, fraud checks, payouts,
    reporting). "included": the fee is part of the budget; "on_top": it is added to it."""
    def num(name, default):
        try:
            return float(config.env(name) or default)
        except ValueError:
            return float(default)
    mode = (config.env("CLIPKONTRAST_CAMPAIGN_FEE_MODE") or "included").strip().lower()
    return {"min_budget": num("CLIPKONTRAST_CAMPAIGN_MIN_BUDGET", 100000), "fee_pct": num("CLIPKONTRAST_CAMPAIGN_FEE_PCT", 30),
            "fee_mode": mode if mode in ("included", "on_top") else "included", "currency": "INR"}


def inr(n) -> str:
    """₹1,00,000: rupees the Indian way."""
    n = int(round(float(n or 0)))
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        s = head + "," + tail
    return ("-" if n < 0 else "") + "₹" + s


def split(budget: float) -> dict:
    """A budget as the clippers' pool and the fee, the way the page and the admin both show it."""
    p = pricing()
    pct = max(0.0, min(90.0, p["fee_pct"])) / 100
    if p["fee_mode"] == "on_top":
        return {"pool": round(budget, 2), "fee": round(budget * pct, 2), "total": round(budget * (1 + pct), 2)}
    return {"pool": round(budget * (1 - pct), 2), "fee": round(budget * pct, 2), "total": round(budget, 2)}


def _clean(v, n) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(v or "")).strip()[:n]


def submit(data: dict) -> dict:
    """Save a request (checked), tell the admins. Returns {"id"}."""
    if _clean(data.get("website"), 200):                 # the hidden field only robots fill in
        raise Refused("Something went wrong. Please try again.")
    name, email = _clean(data.get("name"), 80), _clean(data.get("email"), 160).lower()
    if len(name) < 2:
        raise Refused("Please tell us your name.")
    if not _EMAIL.match(email):
        raise Refused("Please give an email address we can reply to.")
    role = data.get("role") if data.get("role") in ROLES else "creator"
    org = _clean(data.get("org"), 120)
    links = "\n".join(l for l in (_clean(x, 300) for x in re.split(r"[\n,]+", str(data.get("links") or ""))) if re.match(r"https?://\S+$", l))[:1000]
    if not org and not links:
        raise Refused("Please add your channel or brand name, or a link to it.")
    try:
        budget = float(str(data.get("budget") or "0").replace(",", ""))
    except ValueError:
        budget = 0.0
    p = pricing()
    if not (p["min_budget"] <= budget <= 1e9):
        raise Refused(f"Campaigns start at {inr(p['min_budget'])}. Please set a budget of at least that.")
    try:
        rate = float(data.get("rate")) if str(data.get("rate") or "").strip() else None
    except ValueError:
        rate = None
    if rate is not None and not (1 <= rate <= 10000):
        rate = None
    plats = ",".join(x for x in (data.get("platforms") or []) if x in PLATFORMS) if isinstance(data.get("platforms"), list) else ""
    category = data.get("category") if data.get("category") in CATEGORIES else ""
    now = time.time()
    row = dict(t=now, status="new", role=role, name=name, email=email, whatsapp=_clean(data.get("whatsapp"), 30), org=org,
               links=links, budget=round(budget, 2), rate=rate, platforms=plats, start=_clean(data.get("start"), 40),
               duration=_clean(data.get("duration"), 40), category=category, brief=_clean(data.get("brief"), 4000),
               notes="", updated_at=now)
    with db.engine.begin() as c:
        rid = c.execute(db.earn_requests.insert().values(**row)).inserted_primary_key[0]
        admins = [(r[0], r[1]) for r in c.execute(sa.select(db.users.c.id, db.users.c.email).where(
            db.users.c.is_admin == sa.true(), db.users.c.disabled == sa.false()))]
    _tell(rid, row, admins)
    return {"id": rid}


def _tell(rid, row, admins):
    from . import notices
    who = row["org"] or row["name"]
    line = f"{who}: {inr(row['budget'])} budget ({ROLES[row['role']]})"
    for a, _e in admins:
        try:
            notices.add(a, "campaign_request", f"New campaign request #{rid}", line, "/admin/earn/requests")
        except Exception:  # noqa: BLE001 - the request is saved whatever the bell does
            pass
    try:
        from . import mailer
        body = (f"{line}\n\nName: {row['name']}\nEmail: {row['email']}\nWhatsApp: {row['whatsapp'] or '-'}\n"
                f"Links: {row['links'] or '-'}\n\n{row['brief'][:800]}")
        for _a, to in admins[:5]:
            mailer.send(to, f"Campaign request #{rid}: {who}", "A new campaign request", body,
                        "Open campaign requests", config.PUBLIC_URL + "/admin/earn/requests", "")
    except Exception:  # noqa: BLE001
        pass


def _row(r) -> dict:
    m = r._mapping                       # (r.t is SQLAlchemy's own "row as a tuple", not the column)
    d = {k: m[k] for k in ("id", "t", "status", "role", "name", "email", "whatsapp", "org", "links", "budget", "rate",
                                     "platforms", "start", "duration", "category", "brief", "notes", "campaign_id", "updated_at")}
    d["links"] = [l for l in (d["links"] or "").splitlines() if l]
    d["platforms"] = [p for p in (d["platforms"] or "").split(",") if p]
    d["split"] = split(d["budget"])
    return d


def listing(status: str = "") -> dict:
    q = sa.select(db.earn_requests).order_by(db.earn_requests.c.t.desc()).limit(500)
    if status in STATUSES:
        q = q.where(db.earn_requests.c.status == status)
    with db.engine.connect() as c:
        rows = c.execute(q).all()
        counts = dict(c.execute(sa.select(db.earn_requests.c.status, sa.func.count()).group_by(db.earn_requests.c.status)).all())
    return {"items": [_row(r) for r in rows], "counts": {s: int(counts.get(s, 0)) for s in STATUSES}, "pricing": pricing()}


def update(rid: int, data: dict) -> dict:
    vals = {"updated_at": time.time()}
    if "status" in data:
        if data["status"] not in STATUSES:
            raise Refused("Unknown status.")
        vals["status"] = data["status"]
    if "notes" in data:
        vals["notes"] = _clean(data["notes"], 4000)
    if "campaign_id" in data:
        vals["campaign_id"] = _clean(data["campaign_id"], 24) or None
    with db.engine.begin() as c:
        n = c.execute(db.earn_requests.update().where(db.earn_requests.c.id == int(rid)).values(**vals)).rowcount
        if not n:
            raise Refused("That request doesn't exist.")
        return _row(c.execute(sa.select(db.earn_requests).where(db.earn_requests.c.id == int(rid))).first())
