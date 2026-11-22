"""Seeds a website data folder with campaigns, for test_campaigns_app.py (run with CLIPKONTRAST_DATA set)."""
import io, sys, time
sys.path.insert(0, ".")
from PIL import Image  # noqa: E402
from studio import db, earn  # noqa: E402
db.init()
now = time.time()
SOURCES = "\n".join(["Day 1 | https://www.youtube.com/live/AAAAAAAAAAA?si=x", "Day 2 | https://youtu.be/BBBBBBBBBBB",
                     "Day 3 | https://www.youtube.com/watch?v=CCCCCCCCCCC&t=99s", "Kick stream | https://kick.com/mizoplays/videos/1234-abcd",
                     "Teaser video | https://www.youtube.com/watch?v=DDDDDDDDDDD", "Raw folder | https://drive.google.com/drive/folders/abcdefghijklmn"])
MOMENTS = "Day 3 | https://www.youtube.com/watch?v=CCCCCCCCCCC\n2:37:12 heavy driving race to the club\n2:44:30-2:45:53 finally found jason\n\nDay 1\n13:29 the first mission"
live = earn.save_campaign({"title": "GTA 6 Launch × Mizo Plays", "creator_name": "Mizo Plays", "status": "live", "rate_per_1k": 25,
                           "budget": 110000, "platforms": ["youtube", "instagram"], "required_tag": "#MizoGTA6", "category": "Gaming",
                           "tagline": "Clip the GTA 6 marathon and get paid for every view", "brief": "Mizo is playing GTA 6 all week.\nClip the funniest and wildest moments.",
                           "rules": "Only clips from these streams\nCaption must have #MizoGTA6", "ends_at": now + 5 * 86400 + 3 * 3600,
                           "min_views": 1000, "max_per_clip": 5000, "sources": SOURCES, "moments": MOMENTS, "accent": "#C6F432",
                           "raw_clips": "https://drive.google.com/drive/folders/secretfolder123"})
from PIL import ImageDraw  # noqa: E402
img = Image.new("RGB", (1200, 675))
d = ImageDraw.Draw(img)
for y in range(675):                                   # a cover like an admin would upload: a gradient and a big title
    d.line([(0, y), (1200, y)], fill=(int(30 + y / 675 * 150), int(20 + y / 675 * 40), int(90 + y / 675 * 60)))
d.rectangle((90, 250, 1110, 430), fill=(198, 244, 50))
d.text((130, 300), "GTA 6  x  MIZO", fill=(26, 33, 0), font_size=96)
buf = io.BytesIO(); img.save(buf, "JPEG")
earn.save_cover(live["id"], buf.getvalue())
earn.save_campaign({"title": "Secret next campaign", "creator_name": "Someone", "status": "soon", "rate_per_1k": 20, "budget": 50000,
                    "platforms": ["youtube"], "sources": "Day 1 | https://www.youtube.com/watch?v=EEEEEEEEEEE", "brief": "not revealed"})
earn.save_campaign({"title": "Draft never shown", "status": "draft", "rate_per_1k": 20, "budget": 1, "platforms": ["youtube"]})
for t, b, v in (("Diwali Stream Clips", 75000, 9_800_000), ("BGMI Finals × Mizo", 50000, 6_200_000), ("Valorant Week", 25000, 2_100_000)):
    e = earn.save_campaign({"title": t, "creator_name": "Mizo Plays", "status": "ended", "rate_per_1k": 20, "budget": b,
                            "platforms": ["youtube"], "results": {"views": v, "clips": 400, "clippers": 120}})
print("seeded", live["slug"])

# clippers, for the Clippers tab's filters: 10 ready to be paid in the campaign, 8 in it with no payout profile, 12 outside it
from studio import db as _db, feedback  # noqa: E402
with _db.engine.begin() as c:
    for i in range(30):
        uid = f"u_clip{i:03d}"
        c.execute(_db.users.insert().values(id=uid, email=f"clipper{i}@example.com", name=f"Clipper {i}", is_admin=False,
                                            created_at=now - i * 86400, last_seen=now - i * 3600))
        if i < 10:
            c.execute(_db.earn_profiles.insert().values(user_id=uid, display_name=f"Clipper {i}", whatsapp=f"+9198765432{i:02d}",
                                                        upi=f"clipper{i}@upi", youtube=f"@clip{i}", instagram=f"clip{i}" if i % 2 else "",
                                                        updated_at=now))
        if i < 18:
            c.execute(_db.earn_members.insert().values(campaign_id=live["id"], user_id=uid, joined_at=now))
feedback.submit_report("The clips that are being downloaded are not going to the folder", app="ClipKontrast 2026.11.22.4 (installed app) · Windows 11",
                       source="app", uid=None)
print("seeded clippers")
