#!/usr/bin/env node
// Accessibility regression checks for the docs/ pages.
// Computes real rendered contrast, checks heading order, landmarks, tap
// targets and that no interactive element is clipped out of reach.
// Usage: node tools/a11y_test.js
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = path.join(__dirname, "..", "docs");
// Discovered, not listed. A hardcoded list let splits.html ship untested,
// which is exactly the failure a new page should not be able to have.
const PAGES = fs.readdirSync(ROOT).filter(f => f.endsWith(".html")).sort();

function chromePath() {
  const base = "/opt/pw-browsers";
  if (!fs.existsSync(base)) return undefined;
  for (const d of fs.readdirSync(base)) {
    const p = path.join(base, d, "chrome-linux", "chrome");
    if (d.startsWith("chromium") && fs.existsSync(p)) return p;
  }
  return undefined;
}

let pass = 0, fail = 0;
function check(name, ok, extra) {
  if (ok) { pass++; console.log("  PASS  " + name); }
  else { fail++; console.log("  FAIL  " + name + (extra ? "  -> " + extra : "")); }
}

// Contrast, heading order and tap targets, evaluated in the page.
const PROBE = () => {
  function parse(c) {
    const m = c.match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/);
    return m ? { r: +m[1], g: +m[2], b: +m[3], a: m[4] === undefined ? 1 : +m[4] } : null;
  }
  function lum(c) {
    const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  }
  function over(fg, bg) {
    if (fg.a >= 1) return fg;
    return { r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 };
  }
  function bgOf(el) {
    let n = el;
    while (n && n !== document.documentElement) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0) return c;
      n = n.parentElement;
    }
    const c = parse(getComputedStyle(document.body).backgroundColor);
    return c && c.a > 0 ? c : { r: 255, g: 255, b: 255, a: 1 };
  }
  function ratio(a, b) {
    const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
  }

  const contrast = [];
  document.querySelectorAll("body *").forEach(el => {
    if (!el.offsetParent && getComputedStyle(el).position !== "fixed") return;
    const text = Array.from(el.childNodes)
      .filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join("");
    if (!text) return;
    const st = getComputedStyle(el);
    if (st.visibility === "hidden" || +st.opacity === 0) return;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    const fg = parse(st.color);
    if (!fg) return;
    const bg = bgOf(el);
    const size = parseFloat(st.fontSize);
    const bold = +st.fontWeight >= 700;
    const large = size >= 24 || (bold && size >= 18.66);
    const need = large ? 3 : 4.5;
    const got = ratio(over(fg, bg), bg);
    if (got < need) {
      contrast.push({ tag: el.tagName.toLowerCase(), cls: el.className && String(el.className).slice(0, 30),
        text: text.slice(0, 40), got: +got.toFixed(2), need, color: st.color, size });
    }
  });

  // Heading order: no level skipped going down.
  const heads = Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,h6"))
    .map(h => ({ level: +h.tagName[1], text: h.textContent.trim().slice(0, 40) }));
  const skips = [];
  let prev = 0;
  for (const h of heads) {
    if (prev && h.level > prev + 1) skips.push(h.text + " (h" + h.level + " after h" + prev + ")");
    prev = h.level;
  }

  // Tap targets on interactive controls.
  const small = [];
  document.querySelectorAll("button, input[type=button], input[type=submit], [role=checkbox]").forEach(el => {
    if (!el.offsetParent) return;
    const r = el.getBoundingClientRect();
    if (r.height < 24 || r.width < 24) small.push(el.tagName.toLowerCase() + " " + r.width.toFixed(0) + "x" + r.height.toFixed(0));
  });

  // Anything interactive that sits outside its scroll container with no way to reach it.
  const clipped = [];
  document.querySelectorAll("a, button, [role=checkbox], input").forEach(el => {
    if (!el.offsetParent) return;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return;
    let n = el.parentElement, reachable = true;
    while (n && n !== document.body) {
      const st = getComputedStyle(n);
      const clips = /hidden|clip/.test(st.overflowX) || /hidden|clip/.test(st.overflowY);
      if (clips) {
        const pr = n.getBoundingClientRect();
        if (r.right > pr.right + 1 || r.left < pr.left - 1) reachable = false;
      }
      n = n.parentElement;
    }
    if (!reachable) clipped.push((el.getAttribute("aria-label") || el.textContent.trim()).slice(0, 40));
  });

  return {
    contrast, skips, small, clipped,
    landmarks: {
      main: document.querySelectorAll("main, [role=main]").length,
      skipLink: !!document.querySelector('a[href^="#"]'),
      h1: document.querySelectorAll("h1").length,
    },
    // Every control that can be focused should have an accessible name.
    unnamed: Array.from(document.querySelectorAll("a[href], button, input, [role=checkbox], [tabindex='0']"))
      .filter(el => el.offsetParent)
      .filter(el => !(el.getAttribute("aria-label") || el.getAttribute("aria-labelledby") ||
        el.textContent.trim() || el.getAttribute("title") ||
        (el.labels && el.labels.length)))
      .map(el => el.tagName.toLowerCase() + "." + String(el.className).slice(0, 20)),
  };
};

(async () => {
  const browser = await chromium.launch({ executablePath: chromePath() });
  for (const scheme of ["light", "dark"]) {
    console.log("\n=== " + scheme + " scheme ===");
    const ctx = await browser.newContext({ colorScheme: scheme, viewport: { width: 360, height: 780 } });
    const page = await ctx.newPage();
    for (const f of PAGES) {
      await page.goto("file://" + path.join(ROOT, f));
      await page.waitForTimeout(150);
      const r = await page.evaluate(PROBE);
      check(f + " all text meets WCAG AA contrast", r.contrast.length === 0,
        JSON.stringify(r.contrast.slice(0, 4)));
      check(f + " no heading level skipped", r.skips.length === 0, r.skips.join("; "));
      check(f + " interactive tap targets >= 24px", r.small.length === 0, r.small.join("; "));
      check(f + " no control clipped out of reach", r.clipped.length === 0, r.clipped.join("; "));
      check(f + " exactly one h1 and a main landmark",
        r.landmarks.h1 === 1 && r.landmarks.main === 1,
        "h1=" + r.landmarks.h1 + " main=" + r.landmarks.main);
      check(f + " every focusable control has a name", r.unnamed.length === 0, r.unnamed.join("; "));
    }
    await ctx.close();
  }

  console.log("\n=== file input accessibility ===");
  const ctx = await browser.newContext({ viewport: { width: 1200, height: 900 } });
  const page = await ctx.newPage();
  // The cover tool's file input must be the labelled, focusable control.
  await page.goto("file://" + path.join(ROOT, "cover.html"));
  const inputs = await page.evaluate(() => {
    const i = document.querySelector('input[type=file]');
    return {
      named: !!(i && (i.getAttribute("aria-label") || (i.labels && i.labels.length))),
      dupTabStops: document.querySelectorAll('label[tabindex="0"]').length,
      live: document.querySelectorAll('[role=status],[aria-live]').length,
    };
  });
  check("cover file input has an accessible name", inputs.named);
  check("cover drop label is not a duplicate tab stop", inputs.dupTabStops === 0);
  check("cover has a live region for results", inputs.live > 0);

  await ctx.close();

  // Contrast, on the colours a visitor is actually here to read.
  //
  // Every check above ran on an untouched page. The pass, warn and fail
  // pills, the coloured verdict lines and the tinted table cells do not
  // exist until a file has been measured, so the site's whole semantic
  // palette had never had its contrast computed, in either scheme, while the
  // suite reported "all text meets WCAG AA contrast" for every page.
  //
  // That is this repository's oldest defect wearing accessibility clothes: a
  // verdict reported over a measurement that did not happen. So these drive
  // the tools with real fixtures first, and assert that the results actually
  // rendered before believing an empty list of failures.
  console.log("\n=== contrast after a real measurement ===");
  const FIX = path.join(__dirname, "fixtures");
  const settled = async (pg) => {
    // Wait for a result to exist rather than for a fixed number of seconds.
    // A hardcoded sleep makes a slow runner look like a page that rendered
    // nothing, which would fail the evidence check for a reason that has
    // nothing to do with the page.
    await pg.waitForFunction(
      () => document.querySelectorAll(".pill, [class*=pill]").length > 0,
      null, { timeout: 60000 },
    ).catch(() => {});
    await pg.waitForTimeout(400);
  };
  const measured = async (scheme, label, drive) => {
    const c = await browser.newContext({ colorScheme: scheme, viewport: { width: 1200, height: 900 } });
    const pg = await c.newPage();
    await drive(pg);
    await settled(pg);
    const shown = await pg.evaluate(() =>
      document.querySelectorAll(".pill, [class*=pill]").length);
    // Positive evidence the run produced something. Without this an empty
    // failure list is indistinguishable from a page that never rendered.
    check(label + " (" + scheme + ") rendered a verdict to measure", shown > 0,
      "no pills on the page, so the fixture never produced a result and the "
      + "contrast check below examined nothing");
    const bad = await pg.evaluate(PROBE);
    check(label + " (" + scheme + ") result colours meet WCAG AA",
      bad.contrast.length === 0, JSON.stringify(bad.contrast.slice(0, 4)));
    await c.close();
  };

  const drives = [
    ["cover", async pg => {
      await pg.goto("file://" + path.join(ROOT, "cover.html"));
      await pg.setInputFiles("input[type=file]", path.join(FIX, "nonsquare.jpg"));
    }],
  ];
  for (const scheme of ["light", "dark"]) {
    for (const [label, drive] of drives) await measured(scheme, label, drive);
  }

  await browser.close();
  console.log("\n" + (fail ? fail + " FAILED, " + pass + " passed" : "ALL " + pass + " CHECKS PASSED"));
  process.exit(fail ? 1 : 0);
})();
