// Premium campaigns and levels in a browser: node tests/levels_ui.cjs <site> <shots> <cookie name> <clipper cookie> <admin cookie>
const { chromium } = require("playwright");
const [SITE, OUT, CNAME, CLIP, BOSS] = process.argv.slice(2);
let fails = 0;
const check = (n, ok, got) => { console.log((ok ? "PASS " : "FAIL ") + n + (ok ? "" : "   got " + JSON.stringify(got))); if (!ok) fails++; };
(async () => {
  const b = await chromium.launch();
  const ctx = async v => { const c = await b.newContext({ viewport: { width: 1360, height: 900 } }); await c.addCookies([{ name: CNAME, value: v, url: SITE }]); return c; };
  const errs = [];
  // ---- the clipper: a Starter
  const cc = await ctx(CLIP), p = await cc.newPage(); p.on("pageerror", e => errs.push(e.message));
  await p.goto(SITE + "/earn", { waitUntil: "networkidle" }); await p.waitForTimeout(800);
  const card = await p.$eval("#camps", e => e.innerText);
  check("the premium campaign says approved clippers only, with each level's rate", /Approved clippers only/i.test(card) && /Silver ₹50/.test(card) && /Elite ₹100/.test(card), card.slice(0, 300));
  const box = await p.$eval("#dash .lvbox", e => e.innerText);
  check("every clipper sees their level: a new one is a Starter", /Starter/.test(box) && /Next: Silver/.test(box), box);
  await p.click('[data-open="premium-edits"]'); await p.waitForSelector(".sheet");
  check("a Starter opening the premium campaign is asked to apply, not to join", !!(await p.$('.sheet [data-act="apply-open"]')) && !(await p.$('.sheet [data-act="join"]')));
  await p.waitForTimeout(700); await p.screenshot({ path: OUT + "/lv-sheet-starter.png" });
  await p.click('.sheet [data-act="apply-open"]'); await p.waitForSelector("#applyForm");
  check("...which opens the application, with the levels explained", /How levels work/.test(await p.$eval("#dash", e => e.innerText)));
  await p.fill('#applyForm [name=page_url]', "youtube.com/@asha");
  await p.fill('#applyForm [name=followers]', "12000"); await p.fill('#applyForm [name=avg_views]', "18000");
  await p.fill('#applyForm [name=recording_url]', "https://drive.google.com/file/d/abc/view");
  await p.fill('#applyForm [name=sample_url]', "https://youtube.com/shorts/aaaaaaaaaaa");
  await p.screenshot({ path: OUT + "/lv-apply.png", fullPage: false });
  await p.click('#applyForm button.primary');
  await p.waitForFunction(() => /being reviewed|We're looking/.test(document.querySelector("#dash").innerText), null, { timeout: 10000 });
  check("after applying, the clipper sees it's being reviewed", true);
  // ---- the admin approves
  const bc = await ctx(BOSS), q = await bc.newPage(); q.on("pageerror", e => errs.push(e.message));
  await q.goto(SITE + "/admin/earn/levels", { waitUntil: "networkidle" }); await q.waitForTimeout(600);
  const row = await q.$eval("#view", e => e.innerText);
  check("the admin sees the application with its page, claims, recording and best edit", /asha/i.test(row) && /18K/.test(row) && /Watch/.test(row) && /Clip ↗/.test(row), row.slice(0, 400));
  await q.screenshot({ path: OUT + "/lv-admin.png" });
  await q.click('[data-act="lapprove"][data-level="silver"]'); await q.waitForTimeout(800);
  // ---- the clipper is Silver now
  await p.reload({ waitUntil: "networkidle" }); await p.waitForTimeout(800);
  const box2 = await p.$eval("#dash .lvbox", e => e.innerText);
  check("approved: the clipper is Silver, at ₹50, and sees what Gold takes", /Silver/.test(box2) && /₹50/.test(box2) && /Next: Gold/.test(box2) && /0 \/ 3/.test(box2), box2);
  await p.click('[data-open="premium-edits"]'); await p.waitForSelector(".sheet");
  check("...and can join the premium campaign now", !!(await p.$('.sheet [data-act="join"]')));
  await p.click('.sheet [data-act="join"]'); await p.waitForTimeout(1200);
  check("...joined", !!(await p.$('.sheet [data-act="submit-for"]')));
  await p.click('.sheet [data-act="close"]');
  await p.click('#dash [data-act="tab"][data-t="level"]'); await p.waitForTimeout(300);
  check("the Level tab shows the ladder and all 8 badges", (await p.$$("#dash .bdg")).length === 8 && (await p.$$("#dash .rung")).length === 4);
  await p.evaluate(() => document.querySelector("#me").scrollIntoView()); await p.waitForTimeout(400);
  await p.screenshot({ path: OUT + "/lv-me.png" });
  await p.evaluate(() => document.querySelector("#leaderboard").scrollIntoView()); await p.waitForTimeout(500);
  check("the leaderboard has This week and All time", (await p.$$('#lb [data-act="lbtab"]')).length === 2);
  check("no errors on the pages", errs.length === 0, errs);
  await b.close();
  console.log(fails ? `  ${fails} failed` : "  ALL PASSED");
  process.exit(fails ? 1 : 0);
})();
