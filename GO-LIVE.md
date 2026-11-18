# ClipKontrast website live karna (cloud server)

Guide by [@anistroz.ai](https://www.instagram.com/anistroz.ai/) · [@anistrozelite](https://www.youtube.com/@anistrozelite)

**Kya banega:**
- **clipkontrast.com:** signup/signin (email pe 6-digit OTP, ya Google), campaigns, clip submit, views, admin approval, payouts.
- **Clip maker:** website ke "Download free" button se log ZIP lenge aur apne PC pe chalayenge (Windows `.bat`, Mac `.command`, Linux `.sh`).
  Server pe clips nahi bante, isliye chhota aur sasta server kaafi hai.

Total time: lagbhag 1 ghanta. Har command copy karke chalao.

---

## 1. Server lo (DigitalOcean, ~$6/mahina)

1. https://www.digitalocean.com pe account banao (card ya PayPal chahiye).
2. **Create → Droplets**:
   - Region: **Bangalore (BLR1)**
   - Image: **Ubuntu 24.04 LTS**
   - Size: **Basic → Regular → $6/mo (1 GB RAM, 1 CPU)**
   - Authentication: **Password** (ek lamba, mazboot password) ya SSH key
3. **Create Droplet** dabao. Droplet ka **IP address** copy kar lo (jaise `143.110.x.x`).

## 2. Domain ko server se jodo (Cloudflare)

1. https://dash.cloudflare.com pe `clipkontrast.com` add karo (Free plan).
2. Cloudflare jo 2 nameservers deta hai, unhe wahan daalo jahan domain kharida tha (GoDaddy, Hostinger waghera).
   Activate hone mein 5 minute se kuch ghante lag sakte hain.
3. Cloudflare → **DNS → Records → Add record**:
   - Type `A`, Name `@`, IPv4 = droplet ka IP, Proxy status: **DNS only (grey cloud)**
   - Type `CNAME`, Name `www`, Target `clipkontrast.com`, **DNS only**

   Shuru mein grey cloud hi rakhna, taaki server khud HTTPS certificate le sake.

## 3. Email (Brevo, free: roz 300 emails)

1. https://www.brevo.com pe account banao.
2. **Senders, Domains → Domains → Add a domain** → `clipkontrast.com`. Brevo jo DNS records dikhaye (TXT/CNAME),
   wo Cloudflare DNS mein daalo aur **Verify** dabao. Iske bina OTP emails spam mein jaa sakti hain.
3. **SMTP & API → SMTP** tab: **login** aur ek nayi **SMTP key** copy kar lo.

## 4. Server pe ClipKontrast lagao

Apne PC pe terminal (Windows: PowerShell) kholo aur server mein login karo:

```bash
ssh root@DROPLET_KA_IP
```

Server pe ye commands ek-ek karke chalao:

```bash
apt-get update && apt-get install -y docker.io docker-compose-v2 git
```

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

```bash
git clone https://github.com/anistroz/clipkontrast /opt/clipkontrast && cd /opt/clipkontrast
```

```bash
mkdir -p secrets && nano .env
```

`nano` mein ye paste karo, apni values bharo, phir `Ctrl+O`, `Enter`, `Ctrl+X` se save karo:

```ini
CLIPKONTRAST_DOMAIN=clipkontrast.com
COMPOSE_PROFILES=own-https
POSTGRES_PASSWORD=yahan-ek-lamba-random-password-daalo

CLIPKONTRAST_ACCOUNTS=1
CLIPKONTRAST_EARN_ONLY=1
CLIPKONTRAST_FETCH_MODEL=0
CLIPKONTRAST_VERIFY_EMAIL=1
CLIPKONTRAST_DOWNLOAD_URL=https://github.com/anistroz/clipkontrast/archive/refs/heads/main.zip

CLIPKONTRAST_SMTP_HOST=smtp-relay.brevo.com
CLIPKONTRAST_SMTP_PORT=587
CLIPKONTRAST_SMTP_USER=brevo-ka-smtp-login
CLIPKONTRAST_SMTP_PASSWORD=brevo-ki-smtp-key
CLIPKONTRAST_MAIL_FROM=ClipKontrast <hello@clipkontrast.com>

CLIPKONTRAST_CONTACT_EMAIL=hello@clipkontrast.com
CLIPKONTRAST_LEGAL_NAME=Tumhara poora naam ya business ka naam
CLIPKONTRAST_LEGAL_COUNTRY=India
```

Random password banane ke liye ye chalao aur jo aaye wo `POSTGRES_PASSWORD` mein daalo:

```bash
openssl rand -hex 24
```

Ab website start karo (pehli baar 3-5 minute lagenge):

```bash
docker compose up -d --build
```

Check karo sab chal raha hai:

```bash
docker compose ps
```

Phir browser mein **https://clipkontrast.com** kholo.

## 5. Khud ko admin banao

1. https://clipkontrast.com/signup pe apne email se signup karo, aur email mein aaya 6-digit code daalo.
2. Server pe chalao:

```bash
docker compose exec app python -m studio.admin grant tumhara@email.com
```

## 6. Pehla campaign

1. https://clipkontrast.com/admin/earn → **Settings** → YouTube Data API key daalo (steps wahi page pe likhe hain).
2. **Campaigns → New campaign**: title, creator, rules, platforms, required tag, budget, rate per 1,000 views,
   minimum views, most per clip, hold days, start/end. Cover upload karo → **Go live**.
3. Reel aur story mein `https://clipkontrast.com/earn` share karo.

Budget utna hi daalo jitna sach mein clippers ko de sakte ho. Approve hote hi wo amount "owed" (dena baaki) ban jaata hai.

## 7. Live karne se pehle khud test karo

Ek doosre email se clipper banke poora flow chalao:
signup → OTP → payout profile (UPI, WhatsApp, handle) → campaign join → clip link submit.
Phir admin account se: review → approve → **Payouts → Mark paid**.

---

## Roz ka kaam

- **Review:** clips hold period ke baad *Ready* ho jaate hain. Instagram/X ke views screenshot se daalo, phir approve karo.
- **Payout:** UPI app se paise bhejo, phir **Mark paid** dabao aur UTR paste karo.

## Update kaise karein (jab naya code push ho)

```bash
cd /opt/clipkontrast && git pull && docker compose up -d --build
```

## Backup (hafte mein ek baar)

```bash
cd /opt/clipkontrast && docker compose exec -T db pg_dump -U clipkontrast clipkontrast > backup-$(date +%F).sql
```

Ye file apne PC pe bhi copy karke rakho. Isme users, campaigns aur payout ka saara record hai.

## Kuch gadbad ho toh

| Problem | Kya karein |
|---|---|
| Site nahi khul rahi | `docker compose ps` se check karo sab "running" hai; `docker compose logs app --tail 50` dekho |
| HTTPS/certificate error | Cloudflare mein record **DNS only (grey)** hai, ye check karo; `docker compose logs caddy --tail 50` |
| OTP email nahi aa rahi | Brevo mein domain verified hai, ye check karo; `.env` ka SMTP login/key check karo; spam folder dekho |
| `.env` badla | `docker compose up -d` dobara chalao |
