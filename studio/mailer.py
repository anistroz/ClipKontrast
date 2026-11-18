"""Sending account emails (verify your address, reset your password) over SMTP.

Works with any provider that offers SMTP: Resend, Postmark, Brevo, Amazon SES, Google Workspace and so on. Set
CLIPKONTRAST_SMTP_HOST, CLIPKONTRAST_SMTP_PORT (587), CLIPKONTRAST_SMTP_USER, CLIPKONTRAST_SMTP_PASSWORD_FILE (a file holding the
password or API key) and CLIPKONTRAST_MAIL_FROM ("ClipKontrast <hello@yourdomain.com>"). Without them nothing is sent and the
link is written to the server log instead, which is enough for running ClipKontrast on your own machine.

Some hosts (DigitalOcean, for one) block the mail ports on new servers. With CLIPKONTRAST_BREVO_API_KEY set, mail goes
through Brevo's web API over HTTPS instead, which no host blocks; it takes priority over SMTP."""
import html
import logging
import smtplib
import ssl
import threading
from email.message import EmailMessage
from email.utils import formataddr, getaddresses, make_msgid, parseaddr

from . import config

log = logging.getLogger("clipkontrast.mail")


def ready() -> bool:
    return bool((config.SMTP_HOST or config.brevo_api_key()) and config.MAIL_FROM)


def _send_brevo_api(to: str, subject: str, text: str, html_body: str):
    """One email through Brevo's web API (HTTPS, port 443)."""
    import httpx
    name, addr = parseaddr(config.MAIL_FROM)
    r = httpx.post("https://api.brevo.com/v3/smtp/email", timeout=20,
                   headers={"api-key": config.brevo_api_key(), "accept": "application/json"},
                   json={"sender": {"name": name or "ClipKontrast", "email": addr}, "to": [{"email": to}],
                         "subject": subject, "textContent": text, "htmlContent": html_body})
    if r.status_code >= 300:
        raise RuntimeError(f"Brevo API answered {r.status_code}: {r.text[:200]}")


LOGO = config.ROOT / "web" / "brand" / "logo-email.png"   # PNG: email apps don't show SVG
LOGO_CID = "clipkontrast-logo"


def _html(title: str, intro: str, button: str, link: str, outro: str, logo_src: str = "cid:" + LOGO_CID, code: str = "") -> str:
    """The branded email: logo, a white card with the message and one big button, and a quiet footer.
    Tables and inline styles only, because that is what every email app renders the same way."""
    e = html.escape
    site = config.PUBLIC_URL
    font = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only"><title>{e(title)}</title></head>
<body style="margin:0;padding:0;background:#F3F5EE;-webkit-text-size-adjust:100%">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:#F3F5EE">{e(intro)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F3F5EE"><tr><td align="center" style="padding:36px 14px">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px">
    <tr><td style="padding:0 6px 22px"><a href="{e(site)}" style="text-decoration:none">
      <img src="{e(logo_src)}" width="138" height="38" alt="ClipKontrast" style="display:block;border:0;width:138px;height:38px"></a></td></tr>
    <tr><td style="background:#ffffff;border-radius:18px;border:1px solid #E3E8D6;padding:36px 34px">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr><td style="font-family:{font};font-size:24px;line-height:1.25;font-weight:700;color:#1A2100;padding-bottom:12px">{e(title)}</td></tr>
        <tr><td style="font-family:{font};font-size:16px;line-height:1.65;color:#4A4F40;padding-bottom:28px">{e(intro)}</td></tr>
        {f'<tr><td style="padding-bottom:28px"><div style="display:inline-block;background:#F5FDE0;border:1px solid #E3F7A8;border-radius:14px;padding:14px 22px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:34px;font-weight:700;letter-spacing:10px;color:#1A2100">{e(code)}</div></td></tr>' if code else ""}
        <tr><td style="padding-bottom:28px">
          <table role="presentation" cellpadding="0" cellspacing="0"><tr><td style="border-radius:12px;background:#C6F432">
            <a href="{e(link)}" style="display:inline-block;padding:14px 28px;font-family:{font};font-size:16px;font-weight:700;color:#1A2100;text-decoration:none;border-radius:12px">{e(button)}</a>
          </td></tr></table></td></tr>
        <tr><td style="font-family:{font};font-size:14px;line-height:1.6;color:#666C5A;padding-bottom:22px">{e(outro)}</td></tr>
        <tr><td style="border-top:1px solid #E9EDE1;padding-top:18px;font-family:{font};font-size:12px;line-height:1.6;color:#8A907C">
          Button not working? Copy this link into your browser:<br><a href="{e(link)}" style="color:#4E6B00;word-break:break-all">{e(link)}</a></td></tr>
      </table></td></tr>
    <tr><td align="center" style="padding:24px 10px 0;font-family:{font};font-size:12px;line-height:1.7;color:#8A907C">
      You're getting this because of your ClipKontrast account. We only email you about your account.<br>
      <a href="{e(site)}" style="color:#666C5A;text-decoration:underline">ClipKontrast</a> &nbsp;·&nbsp;
      <a href="{e(site)}/privacy" style="color:#666C5A;text-decoration:underline">Privacy</a> &nbsp;·&nbsp;
      <a href="{e(site)}/terms" style="color:#666C5A;text-decoration:underline">Terms</a></td></tr>
  </table></td></tr></table></body></html>"""


def preview(title="Confirm your email", intro="Thanks for joining ClipKontrast. Confirm this is your email address to start clipping.",
            button="Confirm my email", link=None, outro="The link works for 3 days. If you didn't sign up, you can ignore this email.") -> str:
    """The same email for viewing in a browser: the logo is inlined so it shows without an email app."""
    import base64
    data = "data:image/png;base64," + base64.b64encode(LOGO.read_bytes()).decode() if LOGO.is_file() else ""
    return _html(title, intro, button, link or config.PUBLIC_URL + "/auth/verify?t=example", outro, logo_src=data)


def send(to: str, subject: str, title: str, intro: str, button: str, link: str, outro: str, code: str = "") -> bool:
    """Send in the background. Returns False when no mail service is set up (the link goes to the log)."""
    if [a for _n, a in getaddresses([to])] != [to]:   # one address only: never mail someone the address list sneaks in
        log.warning("Not sending %r: %r is not a single email address", subject, to)
        return False
    if not ready():
        if config.HTTPS:      # a real site: a sign-in link must never sit in a log file
            log.warning("Email not set up, so nothing was sent: %s", subject)
        else:                 # on your own computer the link is printed so you can use it
            print(f"[ClipKontrast mail] {subject} for {to}: {link}" + (f"  (code {code})" if code else ""), flush=True)
        return False
    text = f"{title}\n\n{intro}\n\n" + (f"Your code: {code}\n\n" if code else "") + f"{button}: {link}\n\n{outro}\n"
    if config.brevo_api_key():
        # the logo is loaded from the website here, because the web API can't carry it inside the email
        body = _html(title, intro, button, link, outro, logo_src=config.PUBLIC_URL + "/brand/logo-email.png", code=code)

        def work_api():
            try:
                _send_brevo_api(to, subject, text, body)
            except Exception as e:  # noqa: BLE001
                log.error("Could not send %r to %s: %s", subject, to, e)
                print(f"[ClipKontrast mail] could not send {subject!r} to {to}: {e}", flush=True)

        threading.Thread(target=work_api, daemon=True).start()
        return True
    msg = EmailMessage()
    name, addr = parseaddr(config.MAIL_FROM)
    msg["From"] = formataddr((name or "ClipKontrast", addr))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=addr.split("@")[-1] if "@" in addr else None)
    msg.set_content(text)
    msg.add_alternative(_html(title, intro, button, link, outro, code=code), subtype="html")
    if LOGO.is_file():   # the logo travels inside the email, so it shows without loading anything from the web
        msg.get_payload()[1].add_related(LOGO.read_bytes(), maintype="image", subtype="png", cid=f"<{LOGO_CID}>",
                                         filename="clipkontrast.png", disposition="inline")

    def work():
        try:
            if config.SMTP_PORT == 465:
                with smtplib.SMTP_SSL(config.SMTP_HOST, 465, context=ssl.create_default_context(), timeout=20) as s:
                    if config.SMTP_USER:
                        s.login(config.SMTP_USER, config.smtp_password())
                    s.send_message(msg)
            else:
                with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
                    s.starttls(context=ssl.create_default_context())
                    if config.SMTP_USER:
                        s.login(config.SMTP_USER, config.smtp_password())
                    s.send_message(msg)
        except Exception as e:  # noqa: BLE001
            log.error("Could not send %r to %s: %s", subject, to, e)
            print(f"[ClipKontrast mail] could not send {subject!r} to {to}: {e}", flush=True)

    threading.Thread(target=work, daemon=True).start()
    return True
