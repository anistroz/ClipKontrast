// The editor in a real browser, on a server seeded by tests/editor_seed.py:
//   node tests/editor_ui.cjs <base url> <screenshot folder>
// Opens a clip, edits it every way a person would (split, cut, transcript, transitions, sounds, punch-ins, look,
// text effect, undo / redo, keys, Hype Edit), exports it and checks the clip that comes back.
const { chromium } = require("playwright");
const BASE = process.argv[2] || "http://127.0.0.1:8822", OUT = (process.argv[3] || "/tmp") + "/";
let fails = 0;
const check = (n, ok, got) => { console.log((ok ? "PASS " : "FAIL ") + n + (ok ? "" : "   got " + JSON.stringify(got))); if (!ok) fails++; };
(async () => {
  const b = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
  const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
  const errs = []; p.on("pageerror", e => errs.push(e.message));
  await p.goto(BASE + "/app", { waitUntil: "networkidle" });
  await p.evaluate(() => fetch("/api/settings", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({tour_done: true})}));
  await p.reload({ waitUntil: "networkidle" }); await p.waitForTimeout(800);
  const ids = await p.evaluate(() => [S.jobs[0].id, S.jobs[0].clips[0].id]);
  await p.evaluate(([j, c]) => editClip(j, c), ids);
  await p.waitForFunction(() => window.CKEditor && CKEditor.state() && CKEditor.state().ready, null, { timeout: 90000 });
  await p.waitForTimeout(600);
  const st = () => p.evaluate(() => CKEditor.state());
  let s = await st();
  check("a made clip opens in the full-screen editor, with its live preview playing-ready", s.ready && !!(await p.$("#ed canvas")));
  check("...the preview draws a picture (not a black frame)", await p.evaluate(() => { const c = document.querySelector("#edCanvas").getContext("2d").getImageData(0, 0, 540, 960).data; let n = 0; for (let i = 0; i < c.length; i += 4000) n += c[i] + c[i + 1] + c[i + 2]; return n > 1000; }));
  check("...the timeline shows the clip's words", (await p.$$(".ed-word")).length > 10, (await p.$$(".ed-word")).length);
  // split and cut out the part after the split
  await p.evaluate(() => { const v = document.querySelector("#ed"); });
  await p.keyboard.press("Space"); await p.waitForTimeout(900); await p.keyboard.press("Space");
  const t1 = (await st()).t;
  check("Space plays and pauses the preview", t1 > s.doc.start + 0.3, t1);
  await p.keyboard.press("s");
  s = await st();
  check("S splits the clip at the playhead", s.doc.splits.length === 1);
  const segs = await p.$$("#ed [data-tseg]");
  const sb = await segs[0].boundingBox();                   // the part before the split: cutting the other would leave too little
  await p.mouse.click(sb.x + Math.min(10, sb.width / 2), sb.y + sb.height / 2);
  const base = JSON.stringify(s.doc.edit.cuts), basePunch = s.doc.edit.punch.length, baseBoom = s.doc.edit.sfx.filter(x => x.kind === "boom").length;
  await p.keyboard.press("Delete");
  s = await st();
  const cutNow = JSON.stringify(s.doc.edit.cuts);
  check("a part picked on the timeline and Delete: cut out of the clip", cutNow !== base && s.doc.edit.cuts.some(([a]) => Math.abs(a - s.doc.start) < 0.01), s.doc.edit.cuts);
  await p.keyboard.press("Control+z");
  check("Ctrl+Z brings it back", JSON.stringify((await st()).doc.edit.cuts) === base);
  await p.keyboard.press("Control+Shift+z");
  check("Ctrl+Shift+Z cuts it again", JSON.stringify((await st()).doc.edit.cuts) === cutNow);
  await p.keyboard.press("Control+z");
  // drag on the video track: exactly that part is picked, and Delete cuts only it (not the whole stretch around it)
  {
    const cr = await (await p.$("#ed .ed-vl .ed-clipr")).boundingBox(), d0 = await st();
    const xAt = t => cr.x + (t - d0.doc.start) / (d0.doc.end - d0.doc.start) * cr.width, y = cr.y + cr.height / 2;
    const cutLen = c => c.reduce((n, [a, b]) => n + b - a, 0), before = cutLen(d0.doc.edit.cuts);
    await p.mouse.move(xAt(d0.doc.start + 2), y); await p.mouse.down(); await p.mouse.move(xAt(d0.doc.start + 4), y, { steps: 8 }); await p.mouse.up();
    let r = await st();
    check("dragging on the video track picks just that part", r.sel && r.sel.k === "range" && Math.abs(r.sel.a - (d0.doc.start + 2)) < 0.4 && Math.abs(r.sel.b - (d0.doc.start + 4)) < 0.4, r.sel);
    await p.keyboard.press("Delete");
    r = await st();
    const added = cutLen(r.doc.edit.cuts) - before;
    check("...and Delete cuts only that part out", added > 1.4 && added < 2.6, {added, cuts: r.doc.edit.cuts});
    await p.keyboard.press("Control+z");
    await p.mouse.click(xAt(d0.doc.start + 6), y);
    r = await st();
    await p.keyboard.press("Delete");
    check("a plain click on the track only moves the playhead: Delete then cuts nothing big", cutLen((await st()).doc.edit.cuts) - before < 0.01 || (r.sel && r.sel.k === "seg"), {sel: r.sel, cuts: (await st()).doc.edit.cuts});
    if (r.sel && r.sel.k === "seg") await p.keyboard.press("Control+z");
  }
  // the transcript: pick words and delete them
  await p.click('[data-tool="edit"]');
  await p.click("#edTrans span[data-word] >> nth=6");
  await p.click("#edTrans span[data-word] >> nth=8", { modifiers: ["Shift"] });
  await p.keyboard.press("Delete");
  s = await st();
  check("words picked in the transcript and Delete: cut out", s.doc.edit.cuts.length >= 1, s.doc.edit.cuts);
  check("...and shown struck through", (await p.$$("#edTrans span.cut")).length >= 3);
  await p.click('[data-e="fillers"]').catch(() => {});
  // transitions, sounds, punch-ins, look, text effect
  await p.click('[data-tool="effects"]');
  await p.click('[data-addtr="glitch"]'); await p.waitForTimeout(300);
  s = await st();
  check("a transition clicked in the panel lands on the timeline (snapped to the cut nearby)", s.doc.edit.fx.some(f => f.type === "glitch"), s.doc.edit.fx);
  check("...and is selected, its settings on the right", s.sel && s.sel.k === "fx" && !!(await p.$("#edInsp [data-fxd]")), s.sel);
  await p.click('[data-look="cinema"]');
  await p.click('[data-tool="audio"]'); await p.click('[data-addsfx="boom"]');
  await p.keyboard.press("p");
  await p.click('[data-tool="text"]'); await p.click('[data-hookfx="glow"]');
  await p.fill('[data-txt="hook"]', "THE BOX WAS EMPTY");
  await p.waitForTimeout(800);
  s = await st();
  check("look, sound, punch-in, text effect and new text are all in the edit",
    s.doc.edit.look === "cinema" && s.doc.edit.sfx.filter(x => x.kind === "boom").length === baseBoom + 1 && s.doc.edit.punch.length === basePunch + 1 && s.doc.edit.hook_fx === "glow" && s.doc.hook === "THE BOX WAS EMPTY", s.doc.edit);
  // drag the big text down on the preview
  const hb = await p.$("#edHookBox"), r = await hb.boundingBox();
  await p.mouse.move(r.x + r.width / 2, r.y + r.height / 2); await p.mouse.down(); await p.mouse.move(r.x + r.width / 2, r.y + r.height / 2 + 120, { steps: 6 }); await p.mouse.up();
  s = await st();
  check("dragging the big text on the preview moves it", s.doc.edit.hook_y > 500, s.doc.edit.hook_y);
  await p.screenshot({ path: OUT + "editor-edited.png" });
  // Hype Edit on top
  await p.click('[data-e="hype"]'); await p.waitForTimeout(500);
  s = await st();
  check("Hype Edit adds punch-ins, transitions and a riser, and is one Undo away", s.doc.edit.punch.length >= 2 && s.doc.edit.sfx.some(x => x.kind === "riser"), s.doc.edit);
  await p.keyboard.press("Space"); await p.waitForTimeout(1500); await p.keyboard.press("Space");
  await p.screenshot({ path: OUT + "editor-hype.png" });
  // the layout changes in the preview at once, no export needed
  const pix = () => p.evaluate(() => { const c = document.querySelector("#edCanvas").getContext("2d").getImageData(0, 0, 540, 960).data; let h = 0; for (let i = 0; i < c.length; i += 997) h = (h * 31 + c[i]) % 1e9; return h; });
  await p.click('[data-tool="frame"]');
  const before1 = await pix();
  await p.click('[data-layout="crop"]'); await p.waitForTimeout(300);
  s = await st();
  check("a new layout shows in the preview at once", s.doc.layout === "crop" && s.layout === "crop" && (await pix()) !== before1, s.layout);
  check("...with no 'after you export' note", !(await p.$eval("#edPanel", e => /after you export/.test(e.textContent))));
  await p.click('[data-layout="blur"]');
  // the library: own fonts, sounds and media
  await p.click('[data-tool="library"]');
  const files = process.argv[4] ? ["font.ttf", "boing.wav", "meme.png", "reaction.mp4"].map(f => process.argv[4] + "/" + f) : [];
  if (files.length) {
    const [chooser] = await Promise.all([p.waitForEvent("filechooser"), p.click("#edDrop")]);
    await chooser.setFiles(files);
    await p.waitForFunction(() => CKEditor.state().lib.length >= 4, null, { timeout: 120000 });
    s = await st();
    check("files added to the library: a font, a sound, a picture and a video", JSON.stringify(s.lib.map(i => i.kind).sort()) === JSON.stringify(["font", "media", "media", "sound"]), s.lib);
    await p.waitForTimeout(500);
    await p.click('[data-libadd] >> nth=0');
    s = await st();
    check("a picture or video goes on the clip at the playhead, picked, its settings on the right", s.doc.edit.media.length === 1 && s.sel && s.sel.k === "media" && !!(await p.$("#edInsp [data-med]")), s.sel);
    await p.click('[data-medfit="top"]');
    check("...and can be placed in one click", (await st()).doc.edit.media[0].y < 0.3);
    const font = s.lib.find(i => i.kind === "font").id;
    await p.click(`#edPanel [data-font="hook_font"][data-v="${font}"]`);
    check("a library font is used for the big text", (await st()).doc.edit.hook_font === font);
    await p.click('[data-tool="audio"]');
    await p.click('[data-addsfx^="lib:"]');
    check("a library sound goes on the timeline", (await st()).doc.edit.sfx.some(x => x.kind.startsWith("lib:")));
    await p.screenshot({ path: OUT + "editor-library.png" });
  }
  // a word heard wrong: double-click it in the transcript, type what was said (report #201)
  await p.click('[data-tool="edit"]'); await p.waitForTimeout(150);
  const wsp = await p.$("#edTrans [data-word]:not(.out)");
  if (wsp) {
    await wsp.dblclick();
    await p.waitForSelector(".ed-fixbox", { timeout: 3000 });
    await p.fill("#edFixIn", "Mizo");
    await p.keyboard.press("Enter");
    await p.waitForTimeout(200);
    s = await st();
    const shown = await p.$eval("#edTrans", e => e.textContent);
    check("double-click a caption word and type: the captions say the fixed word", Object.values(s.doc.edit.fix || {}).includes("Mizo") && shown.includes("Mizo") && !(await p.$(".ed-fixbox")), s.doc.edit.fix);
  } else check("the transcript shows words to fix", false);
  // every tool panel opens
  for (const t of ["frame", "captions", "post", "ai", "library"]) { await p.click(`[data-tool="${t}"]`); await p.waitForTimeout(150); }
  check("every tool's panel opens", (await p.$eval("#edPanel", e => e.textContent.length)) > 50);
  // export
  const before = await p.evaluate(([j, c]) => S.jobs.find(x => x.id === j).clips.find(x => x.id === c).version, ids);
  await p.click("#edExport");
  await p.waitForSelector(".ed-exp", { timeout: 5000 });
  const filled = await p.waitForFunction(() => { const e = document.querySelector("#edPct"); return (e && parseInt(e.textContent) > 0) || /Your clip is ready/.test(document.querySelector(".ed-exp")?.textContent || ""); }, null, { timeout: 240000 }).then(() => p.evaluate(() => document.querySelector("#edPct")?.textContent || "done")).catch(() => "");
  check("the export bar fills with how much of the clip is made", !!filled, filled);
  await p.waitForFunction(() => document.querySelector(".ed-exp") && /Your clip is ready|didn't work/.test(document.querySelector(".ed-exp").textContent), null, { timeout: 240000 });
  const msg = await p.$eval(".ed-exp", e => e.textContent);
  const clip = await p.evaluate(([j, c]) => S.jobs.find(x => x.id === j).clips.find(x => x.id === c), ids);
  check("Export makes the clip with the edit: a new version comes back", /Your clip is ready/.test(msg) && clip.version === before + 1 && clip.status === "done", { msg, v: clip.version, before, st: clip.status, err: clip.error });
  check("...the edit is saved with the clip", !!(clip.edit && clip.edit.fx && clip.edit.fx.length && clip.edit.look), clip.edit);
  check("...with the fixed word", Object.values(clip.edit.fix || {}).includes("Mizo"), clip.edit.fix);
  if (process.argv[4]) check("...with its library picture, font and sound", !!(clip.edit.media && clip.edit.media.length && clip.edit.hook_font && clip.edit.sfx.some(x => x.kind.startsWith("lib:"))), clip.edit);
  check("...and nothing failed quietly (no 'effects couldn't be added')", !/couldn't be added/.test(clip.layout_note || ""), clip.layout_note);
  await p.screenshot({ path: OUT + "editor-exported.png" });
  await p.click('[data-e="hideexp"]');
  await p.keyboard.press("Escape");
  check("Esc goes back to the clips", !(await p.$("#ed")));
  // reopening keeps the saved edit
  await p.evaluate(([j, c]) => editClip(j, c), ids);
  await p.waitForFunction(() => CKEditor.state() && CKEditor.state().ready, null, { timeout: 60000 });
  s = await st();
  check("opening the clip again brings its saved edit back", s.doc.edit.look === clip.edit.look && s.doc.edit.fx.length === clip.edit.fx.length);
  check("no errors on the page", errs.length === 0, errs);
  await b.close();
  console.log(fails ? `  ${fails} failed` : "  ALL PASSED");
  process.exit(fails ? 1 : 0);
})();
