/* "Open the app" on the website: opens the ClipKontrast app installed on this computer, not the web page.
 *
 * The Windows app answers clipkontrast:// links (studio/desktop.py registers them each time it starts, and the
 * installer does too). The browser either opens the app (the page loses focus while the browser asks or the app
 * comes up) or does nothing, when the app isn't installed. In that case this box offers the download.
 * Mac and Linux are started from their own folder, and a phone can't run it, so they get the steps and the download.
 *
 * Any element with data-openapp opens it; data-dl on that element (or window.CK_DOWNLOAD) is the download page.
 */
(function () {
  if (window.ckOpenApp) return;
  const UA = navigator.userAgent || "";
  const PHONE = /android|iphone|ipad|ipod/i.test(UA);
  const WIN = /windows/i.test(UA);
  const MAC = /macintosh|mac os x/i.test(UA) && !PHONE;
  const css = `
.ckapp-bg{position:fixed;inset:0;z-index:1000;background:rgba(20,14,10,.55);backdrop-filter:blur(6px);display:flex;align-items:center;justify-content:center;padding:18px;animation:ckfade .18s ease}
.ckapp{width:100%;max-width:440px;background:#fff;color:#211813;border-radius:22px;padding:28px 26px 24px;box-shadow:0 30px 80px rgba(0,0,0,.35);position:relative;font:15px/1.55 inherit;text-align:center}
.ckapp .x{position:absolute;top:12px;right:12px;width:34px;height:34px;border:0;border-radius:10px;background:#F7F4F1;color:#6D6159;font-size:20px;line-height:1;cursor:pointer}
.ckapp .ic{width:62px;height:62px;border-radius:18px;margin:2px auto 16px;background:#1A2100;display:grid;place-items:center;box-shadow:0 10px 30px rgba(198,244,50,.35)}
.ckapp .ic img{width:36px;height:36px}
.ckapp h3{margin:0;font-size:21px;letter-spacing:-.02em;font-weight:700;color:#1A2100}
.ckapp p{margin:8px 0 0;color:#6D6159}
.ckapp .bt{display:flex;flex-direction:column;gap:8px;margin-top:20px}
.ckapp .bt a{display:flex;align-items:center;justify-content:center;height:48px;border-radius:999px;font-weight:600;text-decoration:none;border:1px solid #E1D9D3;color:#211813;background:#fff}
.ckapp .bt a.p{background:#C6F432;border-color:#C6F432;color:#1A2100}
.ckapp .bt a.p:hover{background:#D4FA5A}
.ckapp small{display:block;margin-top:14px;color:#A0948C;font-size:13px}
.ckapp .dots{display:inline-flex;gap:5px;margin-top:14px}.ckapp .dots i{width:7px;height:7px;border-radius:50%;background:#C6F432;animation:ckdot 1s infinite}
.ckapp .dots i:nth-child(2){animation-delay:.15s}.ckapp .dots i:nth-child(3){animation-delay:.3s}
@keyframes ckdot{0%,100%{opacity:.25;transform:translateY(0)}50%{opacity:1;transform:translateY(-3px)}}
@keyframes ckfade{from{opacity:0}to{opacity:1}}`;
  let box = null, timer = 0;
  const esc = s => String(s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  function close() {
    clearTimeout(timer);
    if (box) { box.remove(); box = null; document.removeEventListener("keydown", onKey); }
  }
  function onKey(e) { if (e.key === "Escape") close(); }
  function show(html) {
    if (!document.getElementById("ckapp-css")) {
      const st = document.createElement("style"); st.id = "ckapp-css"; st.textContent = css; document.head.appendChild(st);
    }
    if (!box) {
      box = document.createElement("div"); box.className = "ckapp-bg";
      box.addEventListener("click", e => { if (e.target === box || e.target.closest(".x")) close(); });
      document.body.appendChild(box); document.addEventListener("keydown", onKey);
    }
    box.innerHTML = `<div class="ckapp" role="dialog" aria-modal="true" aria-label="ClipKontrast app"><button class="x" type="button" aria-label="Close">×</button><div class="ic"><img src="/brand/favicon.svg" alt=""></div>${html}</div>`;
  }
  function dlButtons(dl) {
    const ext = /^https?:/.test(dl) && !dl.startsWith(location.origin) ? ' target="_blank" rel="noopener"' : "";
    const label = WIN ? "Install for Windows" : MAC ? "Install for Mac" : "Install now";
    return `<div class="bt"><a class="p" href="${esc(dl)}"${ext}>${label}, free</a><a href="/download">How to install</a></div>`;
  }
  function missing(dl) {
    show(`<h3>Install ClipKontrast</h3><p>The ClipKontrast app isn't on this computer yet. It's free and takes a minute to install.</p>${dlButtons(dl)}
      <small>Already installed? Open it once from the ClipKontrast icon on your desktop. After that, this button opens it for you.</small>`);
  }
  window.ckOpenApp = function (dl) {
    dl = dl || window.CK_DOWNLOAD || "/download";
    close();
    if (PHONE) {
      show(`<h3>ClipKontrast runs on a computer</h3><p>Open clipkontrast.com on your Windows, Mac or Linux PC to install the free clip maker. On your phone you can join campaigns and send your clip links.</p><div class="bt"><a class="p" href="/earn#me">My earnings</a></div>`);
      return;
    }
    if (!WIN) {
      const how = MAC ? "Open the ClipKontrast folder you unzipped and double-click <b>Start-ClipKontrast-Mac</b>." : "Open the ClipKontrast folder and run <b>start-linux.sh</b>.";
      show(`<h3>Open ClipKontrast</h3><p>${how}</p>${dlButtons(dl)}<small>Not installed yet? The steps are on the install page.</small>`);
      return;
    }
    let left = false;
    const mark = () => { left = true; };
    window.addEventListener("blur", mark, {once: true});
    document.addEventListener("visibilitychange", mark, {once: true});
    show(`<h3>Opening ClipKontrast…</h3><p>Your browser may ask to open the app. Click <b>Open</b>.</p><div class="dots"><i></i><i></i><i></i></div>`);
    if (/firefox/i.test(UA)) {     // Firefox shows an error page for an unknown link, so it goes to a hidden frame
      const f = document.createElement("iframe"); f.style.display = "none"; f.src = "clipkontrast://open";
      document.body.appendChild(f); setTimeout(() => f.remove(), 3000);
    } else {
      location.href = "clipkontrast://open";
    }
    timer = setTimeout(() => {
      window.removeEventListener("blur", mark); document.removeEventListener("visibilitychange", mark);
      if (left) close(); else missing(dl);
    }, 2200);
  };
  document.addEventListener("click", e => {
    const a = e.target.closest("[data-openapp]");
    if (!a) return;
    e.preventDefault();
    window.ckOpenApp(a.dataset.dl);
  });
})();
