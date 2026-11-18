"""Confirming the email with a six-digit code. Starts its own server; with no mail service set up, the code is
printed to the server's output, which is where this test reads it from.
Usage: test_otp.py <project root>"""
import os, re, subprocess, sys, tempfile, time, urllib.request
import httpx
ROOT = sys.argv[1]
PORT = 8797
BASE = f"http://127.0.0.1:{PORT}"
ORIGIN = {"Origin": BASE}
fails = []


def check(name, got, want):
    ok = got == want if not callable(want) else want(got)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"   got {got!r}"))
    if not ok:
        fails.append(name)


data = tempfile.mkdtemp(prefix="ck-otp-")
log_path = os.path.join(data, "server.log")
env = {**os.environ, "CLIPKONTRAST_DATA": data, "CLIPKONTRAST_PORT": str(PORT), "CLIPKONTRAST_PUBLIC_URL": BASE, "DATABASE_URL": "",
       "CLIPKONTRAST_ACCOUNTS": "1", "CLIPKONTRAST_VERIFY_EMAIL": "1", "CLIPKONTRAST_SMTP_HOST": "", "CLIPKONTRAST_FETCH_MODEL": "0",
       "CLIPKONTRAST_UPDATE_CHECK": "0", "CLIPKONTRAST_AUTO_RELOAD": "0", "PYTHONUNBUFFERED": "1"}
log = open(log_path, "w")
srv = subprocess.Popen([sys.executable, "-m", "studio.server"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)


def codes_for(email):
    time.sleep(0.5)
    return re.findall(r"for " + re.escape(email) + r": \S+  \(code (\d{6})\)", open(log_path).read())


def verified(c):
    return c.get("/api/status").json()["user"]["verified"]


# PostgreSQL refuses text longer than a column allows (SQLite doesn't), so every purpose must fit the column
sys.path.insert(0, ROOT)
import re as _re
from studio import db as _db
_limit = _db.email_tokens.c.purpose.type.length
_purposes = set(_re.findall(r'purpose\s*==\s*"(\w+)"|purpose="(\w+)"|_make_link\([^,]+, \'(\w+)\'', open(os.path.join(ROOT, "studio", "auth.py")).read()))
_purposes = {p for t in _purposes for p in t if p}
check(f"every one-time code purpose fits the database column ({_limit} letters): {sorted(_purposes)}",
      all(len(p) <= _limit for p in _purposes) and len(_purposes) >= 3, True)

try:
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/healthz", timeout=2); break
        except Exception:
            time.sleep(1)

    check("a code can't be sent in without signing in",
          httpx.post(BASE + "/api/auth/verify-code", json={"code": "123456"}, headers=ORIGIN).status_code, 401)

    c = httpx.Client(base_url=BASE, timeout=30)
    check("sign up works", c.post("/api/auth/signup", json={"email": "a@example.com", "password": "test-pass-123"}, headers=ORIGIN).status_code, 200)
    first = codes_for("a@example.com")
    check("the sign-up email carries a six-digit code", len(first), 1)
    check("not confirmed yet", verified(c), False)
    r = c.post("/api/auth/verify-code", json={"code": "12"}, headers=ORIGIN)
    check("a code that isn't six digits is refused with a clear message", (r.status_code, "6-digit" in r.json()["detail"]), (400, True))
    wrong = "000000" if first[0] != "000000" else "111111"
    check("a wrong code is refused", c.post("/api/auth/verify-code", json={"code": wrong}, headers=ORIGIN).status_code, 400)
    check("still not confirmed", verified(c), False)
    check("asking for a new code works", c.post("/api/auth/resend-verification", headers=ORIGIN).json().get("sent") is not None, True)
    second = codes_for("a@example.com")
    check("a new code was sent", len(second), 2)
    if second[1] != first[0]:
        check("the older code stops working once a new one is sent",
              c.post("/api/auth/verify-code", json={"code": first[0]}, headers=ORIGIN).status_code, 400)
    spaced = second[-1][:3] + " " + second[-1][3:]
    check("the newest code works, even typed with a space", c.post("/api/auth/verify-code", json={"code": spaced}, headers=ORIGIN).status_code, 200)
    check("now confirmed", verified(c), True)
    check("a used code can't confirm anything again, and says so politely",
          c.post("/api/auth/verify-code", json={"code": second[-1]}, headers=ORIGIN).json(), {"verified": True})

    b = httpx.Client(base_url=BASE, timeout=30)
    b.post("/api/auth/signup", json={"email": "b@example.com", "password": "test-pass-123"}, headers=ORIGIN)
    code_b = codes_for("b@example.com")[-1]
    bad = "999999" if code_b != "999999" else "888888"
    for _ in range(5):
        b.post("/api/auth/verify-code", json={"code": bad}, headers=ORIGIN)
    r = b.post("/api/auth/verify-code", json={"code": code_b}, headers=ORIGIN)
    check("after five wrong tries even the right code waits", (r.status_code, "Too many" in r.json()["detail"]), (400, True))
    check("so guessing doesn't confirm the account", verified(b), False)
    d = httpx.Client(base_url=BASE, timeout=30)
    d.post("/api/auth/signup", json={"email": "d@example.com", "password": "test-pass-123"}, headers=ORIGIN)
    code_d = codes_for("d@example.com")[-1]
    if code_d != code_b:
        check("one account's code doesn't confirm another account",
              d.post("/api/auth/verify-code", json={"code": code_b}, headers=ORIGIN).status_code, 400)
    check("each account's own code works for it", d.post("/api/auth/verify-code", json={"code": code_d}, headers=ORIGIN).status_code, 200)
finally:
    srv.terminate()
    srv.wait(10)
    log.close()

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
