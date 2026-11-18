"""Mail through Brevo's web API (for hosts that block the mail ports). Nothing leaves this machine: the request is caught."""
import os, sys, tempfile, time
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="ck-mailapi-"), DATABASE_URL="", CLIPKONTRAST_SMTP_HOST="",
                  CLIPKONTRAST_BREVO_API_KEY="xkeysib-test-key-123", CLIPKONTRAST_MAIL_FROM="ClipKontrast <hello@example.com>",
                  CLIPKONTRAST_PUBLIC_URL="https://clips.example.com")
sys.path.insert(0, ".")
import httpx
from studio import mailer
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


sent = []


class R:
    def __init__(self, code): self.status_code, self.text = code, "nope"


answer = [201]
httpx.post = lambda url, **kw: (sent.append((url, kw)), R(answer[0]))[1]

check("mail counts as set up with only the API key", mailer.ready(), True)
check("sending starts", mailer.send("a@example.com", "123456 is your ClipKontrast code", "Confirm your email", "Enter this code.",
                                    "Or confirm with one click", "https://clips.example.com/auth/verify?t=x", "Ignore if not you.", code="123456"), True)
for _ in range(50):
    if sent: break
    time.sleep(0.05)
check("one request went to Brevo's web API", [u for u, _ in sent], ["https://api.brevo.com/v3/smtp/email"])
kw = sent[0][1] if sent else {}
j = kw.get("json", {})
check("it carries the key in the api-key header", kw.get("headers", {}).get("api-key"), "xkeysib-test-key-123")
check("sender and recipient are right", (j.get("sender"), j.get("to")), ({"name": "ClipKontrast", "email": "hello@example.com"}, [{"email": "a@example.com"}]))
check("the code is in the subject, the text and the page", ("123456" in j.get("subject", ""), "123456" in j.get("textContent", ""), "123456" in j.get("htmlContent", "")), (True, True, True))
check("the logo is loaded from the website", "https://clips.example.com/brand/logo-email.png" in j.get("htmlContent", ""), True)
check("the one-click link is there too", "https://clips.example.com/auth/verify?t=x" in j.get("htmlContent", ""), True)
check("a bad address is never sent to", mailer.send("a@example.com, b@example.com", "s", "t", "i", "b", "l", "o"), False)
print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
