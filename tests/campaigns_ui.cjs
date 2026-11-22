// The Paid campaigns screens in a browser, for test_campaigns_app.py: node campaigns_ui.cjs <app url> <screenshots folder>
// Prints one JSON line per check: {"name", "got", "want"}.
const { chromium } = require("playwright");
const path = require("path");
const [APP, SHOTS, THUMB, SITE, CK_NAME, CK_VALUE] = process.argv.slice(2);
const out = (name, got, want) => console.log(JSON.stringify({ name, got, want }));
// a stream picture: a small JPEG, so the test needs no internet
const JPG = require("fs").readFileSync(THUMB);
(async () => {
  const b = await chromium.launch();
  try {
    const pg = await b.newPage({ viewport: { width: 1366, height: 900 } });
    const errs = [];
    pg.on("pageerror", e => errs.push(String(e)));
    await pg.route("**/api/link-thumb?**", r => r.fulfill({ status: 200, contentType: "image/jpeg", body: JPG }));
    // what a link is, as the app would find out from the video site
    await pg.route("**/api/preview?**", r => { const u = new URL(r.request().url()).searchParams.get("url");
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ title: "Video " + u.slice(-11), uploader: "Mizo Plays", duration: 36000,
        is_live: false, thumb: "", post_live: false, handle: "mizoplays", platform: u.includes("kick") ? "kick" : "youtube" }) }); });
    await pg.goto(APP + "/app", { waitUntil: "networkidle" });
    await pg.waitForSelector("#camps-home .pc-hero", { timeout: 20000 });
    const home = await pg.innerText("#camps-home");
    out("Home: Clip & get paid, the campaign, its pool in rupees", ["Clip & get paid", "GTA 6 Launch × Mizo Plays", "₹1,10,000", "per 1,000 views"].every(x => home.includes(x)), true);
    out("...the streams to clip, with their pictures (4 on Home)", [await pg.locator("#camps-home .pcs").count(), await pg.locator("#camps-home .pcs img.lt").count()], [4, 4]);
    out("...and our previous campaigns, money first", ["Our previous campaigns", "₹75,000", "₹1,50,000 across 3 completed campaigns"].every(x => home.includes(x)), true);
    out("Home: a pill at the top says a paid campaign is live", (await pg.innerText("#campPill")).toLowerCase().includes("paid campaign live"), true);
    await pg.screenshot({ path: path.join(SHOTS, "home.png") });
    await pg.click('[data-act="campscroll"]'); await pg.waitForTimeout(700);
    await pg.screenshot({ path: path.join(SHOTS, "home-scrolled.png") });
    await pg.locator("#camps-home .pc").screenshot({ path: path.join(SHOTS, "home-campaign.png") });
    out("the sidebar says a paid campaign is live", await pg.locator('.nav-item[data-v="campaigns"] .livec').count(), 1);
    await pg.click('.nav-item[data-v="campaigns"]');
    await pg.waitForSelector("#camps-page .pc-camp", { timeout: 10000 });
    const page = await pg.innerText("#camps-page");
    out("Paid campaigns: the whole campaign, how to get paid, every stream, the rules",
      ["Join on clipkontrast.com", "Send the link, get paid", "#MizoGTA6", "Kick stream", "Teaser video", "Raw folder", "Only clips from these streams"].every(x => page.includes(x)), true);
    out("...the coming-soon campaign without its streams", page.includes("Secret next campaign") && !page.includes("not revealed"), true);
    out("...the address is /app/campaigns", pg.url().endsWith("/app/campaigns"), true);
    await pg.screenshot({ path: path.join(SHOTS, "campaigns.png") });
    await pg.setViewportSize({ width: 1366, height: 3200 });
    await pg.screenshot({ path: path.join(SHOTS, "campaigns-full.png") });
    await pg.setViewportSize({ width: 1366, height: 900 });
    await pg.click('#camps-page .pc-camp [data-act="campmoments"][data-s="2"]');
    out("Moments: the marked moments of that stream", await pg.locator("#camps-page .pcm .cm-m").count(), 2);
    await pg.locator("#camps-page .pcm").screenshot({ path: path.join(SHOTS, "moments.png") });
    await pg.click('#camps-page .pcm [data-act="campmoment"][data-i="1"]');
    await pg.waitForSelector("#addform .prerange", { timeout: 10000 });
    await pg.waitForFunction(() => document.querySelector("#attIn")?.innerText.includes("Video CCCCCCCCCCC"), null, { timeout: 10000 });
    out("Clip this: the composer opens with that stream and just that moment", (await pg.innerText(".prerange")).includes("2:44:22"), true);
    await pg.locator("#addform").screenshot({ path: path.join(SHOTS, "composer-moment.png") });
    await pg.click('.nav-item[data-v="campaigns"]'); await pg.waitForSelector("#camps-page .pc-camp");
    await pg.locator('#camps-page .pc-camp .pcs-a [data-act="campclip"][data-s="3"]').first().click();
    await pg.waitForFunction(() => document.querySelector("#attIn")?.innerText.includes("Video s/1234-abcd"), null, { timeout: 10000 });
    out("Clip it on the Kick stream: the composer opens with it, the whole stream", await pg.locator("#addform .prerange").count(), 0);
    const m = await b.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
    m.on("pageerror", e => errs.push(String(e)));
    await m.route("**/api/link-thumb?**", r => r.fulfill({ status: 200, contentType: "image/jpeg", body: JPG }));
    await m.goto(APP + "/app/campaigns", { waitUntil: "networkidle" }); await m.waitForSelector("#camps-page .pc-camp");
    out("on a phone-size window nothing spills sideways", await m.evaluate(() => { const e = document.querySelector("#camps-page"); return e.scrollWidth <= e.clientWidth + 1; }), true);
    await m.screenshot({ path: path.join(SHOTS, "phone.png") });
    if (SITE && CK_NAME) {                               // the admin's campaign editor on the website
      const ctx = await b.newContext({ viewport: { width: 1366, height: 1000 } });
      await ctx.addCookies([{ name: CK_NAME, value: CK_VALUE, url: SITE }]);
      const a = await ctx.newPage();
      a.on("pageerror", e => errs.push("admin: " + String(e)));
      await a.route("**/api/link-thumb?**", r => r.fulfill({ status: 200, contentType: "image/jpeg", body: JPG }));
      await a.goto(SITE + "/admin/earn", { waitUntil: "networkidle" });
      await a.locator("tr", { hasText: "GTA 6 Launch" }).locator('[data-act="edit"]').click();
      await a.waitForSelector("#streams .srow");
      out("admin: each stream box shows the link's picture, as the app shows it",
        [await a.locator("#streams .srow").count(), await a.locator("#streams .s-thumb img").count()], [6, 5]);
      out("admin: the editor says live campaigns show in the app", (await a.innerText(".inapp")).includes("Paid campaigns"), true);
      await a.locator("#streams").scrollIntoViewIfNeeded();
      await a.locator(".inapp").screenshot({ path: path.join(SHOTS, "admin-note.png") });
      await a.locator("#streams .srow").first().screenshot({ path: path.join(SHOTS, "admin-row.png") });
      await a.locator("#streams .srow .s-url").nth(1).fill("https://kick.com/mizoplays/videos/new-one");
      await a.waitForFunction(() => document.querySelectorAll("#streams .s-thumb img")[1]?.src.includes("new-one"), null, { timeout: 5000 });
      out("admin: a new link shows its picture once typed", true, true);
      // the Earn page: before much is paid out, the best rate is shown instead of "₹60 paid out"
      await a.goto(SITE + "/earn", { waitUntil: "networkidle" });
      await a.waitForFunction(() => document.querySelector("#tPaidL")?.textContent === "per 1,000 views", null, { timeout: 8000 }).catch(() => {});
      out("Earn page: little paid out yet shows the rate per 1,000 views instead", [await a.innerText("#tPaidL"), (await a.innerText("#tPaid")).includes("25")], ["per 1,000 views", true]);
      // the Clippers tab: every account counted, and the filters
      await a.goto(SITE + "/admin/earn/clippers", { waitUntil: "networkidle" });
      await a.waitForSelector(".cfilters");
      const total = Number((await a.locator(".kpi").first().locator("b").innerText()).replace(/\D/g, ""));
      out("admin Clippers: every account is counted", total >= 31, true);
      const shown = async () => Number((await a.locator("text=/ of /").first().locator("b").innerText()).replace(/\D/g, ""));
      await a.click('[data-act="cpreset"][data-k="noclips"]');
      out("admin Clippers: 'Joined, no clip yet' = the 18 in the campaign", await shown(), 18);
      await a.click('[data-act="cpreset"][data-k="noprofile"]');
      out("admin Clippers: 'Payout profile missing'", await shown(), total - 10);
      await a.click('[data-act="cclear"]');
      await a.selectOption('select[data-cf="camp"]', "GTA 6 Launch × Mizo Plays");
      await a.selectOption('select[data-cf="has"]', "instagram");
      out("admin Clippers: filters combine (in the campaign AND has Instagram)", await shown(), 5);
      await a.selectOption('select[data-cf="sort"]', "name");
      await a.fill("#cq", "clipper3");
      out("admin Clippers: and with the search box", await shown(), 1);
      await a.fill("#cq", "");
      const [dl] = await Promise.all([a.waitForEvent("download"), a.click('[data-act="ccsv"]')]);
      const csv = require("fs").readFileSync(await dl.path(), "utf8");
      out("admin Clippers: Download CSV gives just the clippers shown", csv.trim().split(/\r?\n/).length - 1, 5);
      await a.locator(".card").first().screenshot({ path: path.join(SHOTS, "admin-clippers.png") });
      // Feedback: a report sent from the app (no account on the website) isn't called a deleted account
      await a.goto(SITE + "/admin/feedback", { waitUntil: "networkidle" });
      await a.waitForSelector(".fbitem");
      const fb = await a.locator(".fbitem").first().innerText();
      out("admin Feedback: a report from the app says so, with its version, not 'Deleted account'",
        [fb.includes("From the app"), fb.includes("2026.11.22.4"), fb.includes("Deleted account")], [true, true, false]);
      await ctx.close();
    }
    out("no script errors on the page", errs, []);
  } finally { await b.close(); }
})().catch(e => { console.error(String(e)); process.exit(1); });
