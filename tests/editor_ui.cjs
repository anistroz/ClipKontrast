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
  await p.evaluate(([j, c]) => openClip(j, c), ids);
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
  // every tool panel opens
  for (const t of ["frame", "captions", "post", "ai"]) { await p.click(`[data-tool="${t}"]`); await p.waitForTimeout(150); }
  check("every tool's panel opens", (await p.$eval("#edPanel", e => e.textContent.length)) > 50);
  // export
  const before = await p.evaluate(([j, c]) => S.jobs.find(x => x.id === j).clips.find(x => x.id === c).version, ids);
  await p.click("#edExport");
  await p.waitForSelector(".ed-exp", { timeout: 5000 });
  await p.waitForFunction(() => document.querySelector(".ed-exp") && /ready|didn't work/.test(document.querySelector(".ed-exp").textContent), null, { timeout: 240000 });
  const msg = await p.$eval(".ed-exp", e => e.textContent);
  const clip = await p.evaluate(([j, c]) => S.jobs.find(x => x.id === j).clips.find(x => x.id === c), ids);
  check("Export makes the clip with the edit: a new version comes back", /ready/.test(msg) && clip.version === before + 1 && clip.status === "done", { msg, v: clip.version, before, st: clip.status, err: clip.error });
  check("...the edit is saved with the clip", !!(clip.edit && clip.edit.fx && clip.edit.fx.length && clip.edit.look), clip.edit);
  check("...and nothing failed quietly (no 'effects couldn't be added')", !/couldn't be added/.test(clip.layout_note || ""), clip.layout_note);
  await p.screenshot({ path: OUT + "editor-exported.png" });
  await p.click('[data-e="hideexp"]');
  await p.keyboard.press("Escape");
  check("Esc goes back to the clips", !(await p.$("#ed")));
  // reopening keeps the saved edit
  await p.evaluate(([j, c]) => openClip(j, c), ids);
  await p.waitForFunction(() => CKEditor.state() && CKEditor.state().ready, null, { timeout: 60000 });
  s = await st();
  check("opening the clip again brings its saved edit back", s.doc.edit.look === clip.edit.look && s.doc.edit.fx.length === clip.edit.fx.length);
  check("no errors on the page", errs.length === 0, errs);
  await b.close();
  console.log(fails ? `  ${fails} failed` : "  ALL PASSED");
  process.exit(fails ? 1 : 0);
})();
