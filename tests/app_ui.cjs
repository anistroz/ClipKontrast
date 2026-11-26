// The app's pages in a real browser, on a server seeded by tests/editor_seed.py:
//   node tests/app_ui.cjs <base url> <screenshot folder> <folder with library files>
// Home (quick picks, More options, Ready to edit, the cards), the Editor page, the Library page (add, hear,
// delete) and Hype Edit all, which edits a clip without opening it and makes it again.
const { chromium } = require("playwright");
const BASE = process.argv[2] || "http://127.0.0.1:8823", OUT = (process.argv[3] || "/tmp") + "/", LIB = process.argv[4] || "";
let fails = 0;
const check = (n, ok, got) => { console.log((ok ? "PASS " : "FAIL ") + n + (ok ? "" : "   got " + JSON.stringify(got))); if (!ok) fails++; };
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
  const errs = []; p.on("pageerror", e => errs.push(e.message));
  await p.goto(BASE + "/app", { waitUntil: "networkidle" });
  await p.evaluate(() => fetch("/api/settings", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({tour_done: true})}));
  await p.reload({ waitUntil: "networkidle" }); await p.waitForTimeout(800);

  // Home
  check("Home opens with the link box, its Make clips button and the quick picks", !!(await p.$("#url")) && !!(await p.$(".composer-input #goBtn")) && (await p.$$("#quick [data-act=quick]")).length >= 4);
  check("...More options is closed: the full style and layout pickers are tucked away", await p.$eval("#hmore", e => e.hidden));
  await p.click('#quick [data-k="o_style"][data-v="hype"]');
  check("a quick caption pick sets the caption style Make clips uses", await p.$eval("#o_style", e => e.value) === "hype");
  await p.click('#quick [data-k="o_layout"][data-v="split"]');
  check("a quick layout pick sets the layout", await p.$eval("#o_layout", e => e.value) === "split");
  await p.click('[data-act="moreopts"]');
  check("More options opens the full pickers", !(await p.$eval("#hmore", e => e.hidden)));
  await p.click('#hmore [data-seg="o_layout"][data-v="gameplay"]');
  check("...a pick there shows in the quick picks too", await p.$eval('#quick [data-k="o_layout"][aria-pressed="true"]', e => e.dataset.v) === "gameplay");
  await p.click('#hmore [data-seg="o_style"][data-v="bounce"]');
  check("...and the caption pick too", await p.$eval('#quick [data-k="o_style"][aria-pressed="true"]', e => e.dataset.v) === "bounce");
  check("...and the job options read them", await p.evaluate(() => { const o = jobOptions(); return o.style === "bounce" && o.layout === "gameplay"; }));
  await p.click('[data-act="moreopts"]');
  check("Ready to edit shows the made clips with an Edit button", (await p.$$("#readyRow .rc .go")).length >= 1);
  check("the cards: Hype Edit, Your library and live clipping", (await p.$$("#homeCards .hcard")).length === 3);
  await p.click('[data-act="addmode"][data-m="live"]');
  check("the Live stream tab swaps in the channel box with Start live clipping", !!(await p.$("#liveurl")) && !!(await p.$(".composer-input #liveGo")));
  await p.click('[data-act="addmode"][data-m="video"]');
  await p.screenshot({ path: OUT + "app-home.png" });

  // the sidebar
  check("the sidebar has the Editor and the Library", !!(await p.$('#nav [data-v="studio"]')) && !!(await p.$('#nav [data-v="assets"]')));

  // the Library
  await p.click('#nav [data-v="assets"]'); await p.waitForTimeout(400);
  check("the Library page opens at /app/library", new URL(p.url()).pathname === "/app/library" && !!(await p.$("#libDrop")));
  if (LIB) {
    await p.setInputFiles("#libfile", ["font.ttf", "boing.wav", "meme.png", "reaction.mp4"].map(f => LIB + "/" + f));
    await p.waitForFunction(() => (S.lib || []).length >= 4, null, { timeout: 120000 });
    await p.waitForTimeout(600);
    check("files added on the Library page: a font, a sound, a picture and a video", (await p.$$("#libGrid .li")).length === 4, (await p.$$("#libGrid .li")).length);
    check("...the sidebar counts them", (await p.$eval('#nav [data-v="assets"] .count', e => e.textContent)) === "4");
    await p.click('[data-act="libf"][data-v="sound"]');
    check("the Sounds filter shows only the sound", (await p.$$("#libGrid .li")).length === 1);
    await p.click("#libGrid [data-act=libplay]"); await p.waitForTimeout(300);
    check("...which plays", await p.$eval("#libGrid [data-act=libplay]", e => e.textContent) !== "▶");
    await p.click("#libGrid [data-act=libplay]");
    await p.click('[data-act="libf"][data-v="all"]');
    await p.screenshot({ path: OUT + "app-library.png" });
    const pic = await p.evaluate(() => S.lib.find(i => i.kind === "media" && i.type === "image").id);
    await p.click(`#libGrid [data-act=libdel][data-id="${pic}"]`);
    await p.waitForSelector("#formdlg[open]");
    await p.click('#formdlg button[value="yes"]');
    await p.waitForFunction(() => document.querySelectorAll("#libGrid .li").length === 3, null, { timeout: 10000 }).catch(() => {});
    check("deleting a library item takes it out", (await p.$$("#libGrid .li")).length === 3,
      {n: (await p.$$("#libGrid .li")).length, lib: await p.evaluate(() => S.lib.length), toast: await p.$eval("#toasts", e => e.textContent)});
  }

  // the Editor page
  await p.click('#nav [data-v="studio"]'); await p.waitForTimeout(400);
  check("the Editor page opens at /app/editor with every clip", new URL(p.url()).pathname === "/app/editor" && (await p.$$("#stGrid .rc")).length >= 1);
  await p.fill("#stQ", "zzzz-nothing");
  check("...searching for nothing shows none", (await p.$$("#stGrid .rc")).length === 0);
  await p.fill("#stQ", "");
  await p.click('[data-act="stf"][data-v="edited"]');
  const editedBefore = (await p.$$("#stGrid .rc")).length;
  await p.click('[data-act="stf"][data-v="all"]');
  await p.screenshot({ path: OUT + "app-editor-page.png" });
  await p.click("#stGrid .rc-th");
  await p.waitForSelector("#clipdlg[open] .dlg-edit", { timeout: 10000 });
  check("clicking a clip opens its window (watch it, title, description), with Open in the editor", !(await p.$("#ed")) && !!(await p.$("#clipdlg[open] video")));
  await p.click("#clipdlg .dlg-edit");
  await p.waitForFunction(() => window.CKEditor && CKEditor.state() && CKEditor.state().ready, null, { timeout: 90000 });
  check("...which opens the full editor", !!(await p.$("#ed")) && !(await p.$("#clipdlg[open]")));
  await p.keyboard.press("Escape"); await p.waitForTimeout(300);
  await p.click("#stGrid .rc .go");
  await p.waitForFunction(() => window.CKEditor && CKEditor.state() && CKEditor.state().ready, null, { timeout: 90000 });
  check("Edit on a clip opens it in the editor", !!(await p.$("#ed")));
  await p.keyboard.press("Escape"); await p.waitForTimeout(300);

  // Hype Edit all
  const todo = await p.evaluate(() => notEdited().length);
  if (todo) {
    const v0 = await p.evaluate(() => notEdited().map(([j, c]) => c.version || 0));
    await p.click('#actions [data-act="hypeall"]');
    await p.click('#formdlg button[value="yes"]');
    // the clips are edited one after another, then made again
    await p.waitForFunction(n => !S.hypeRun && (S.hypeErr || readyClips().filter(([, c]) => c.edit).length >= n), todo, { timeout: 180000 }).catch(() => {});
    await p.waitForFunction(() => readyClips().every(([, c]) => c.status === "done" || c.status === "error"), null, { timeout: 300000 });
    const after = await p.evaluate(() => ({hypeErr: S.hypeErr, clips: readyClips().map(([, c]) => ({v: c.version || 0, edit: c.edit, st: c.status, err: c.error}))}));
    check("Hype Edit all puts a hype edit on the clips and makes them again", after.clips.filter(c => c.edit && c.edit.punch && c.edit.punch.length).length >= 1 && after.clips.some(c => c.v > Math.min(...v0)), after);
    await p.click('[data-act="stf"][data-v="edited"]');
    check("...and they show as edited", (await p.$$("#stGrid .rc")).length > editedBefore);
  }
  // every page opens without an error
  for (const v of ["/app", "/app/videos", "/app/campaigns", "/app/settings", "/app/usage"]) { await p.goto(BASE + v, { waitUntil: "networkidle" }); await p.waitForTimeout(400); }
  check("no errors on the page", errs.length === 0, errs);
  await b.close();
  console.log(fails ? `  ${fails} failed` : "  ALL PASSED");
  process.exit(fails ? 1 : 0);
})();
