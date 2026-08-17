// Real browser test of the published tools. Run:
//   uv run --with pillow python tools/make_fixtures.py
//   npm i playwright && node tools/browser_test.js
// Real browser test of the published tools: load each page, catch console
// errors, feed real files through the UI, and assert on what the user sees.
const { chromium } = require('playwright');
const path = require('path');

const DOCS = path.join(__dirname, '..', 'docs');
const FIX = path.join(__dirname, 'fixtures');
let failures = 0;
const ok = (c, m) => { console.log(`  ${c ? 'PASS' : 'FAIL'}  ${m}`); if (!c) failures++; };

(async () => {
  // Use a preinstalled Chromium when one is present (this repo's dev sandbox),
  // otherwise let Playwright resolve its own download (CI).
  const fs = require('fs');
  // Scan rather than pin a build number, which changes when the image updates.
  const local = (() => {
    const base = '/opt/pw-browsers';
    if (!fs.existsSync(base)) return undefined;
    for (const d of fs.readdirSync(base)) {
      const p = require('path').join(base, d, 'chrome-linux', 'chrome');
      if (d.startsWith('chromium') && fs.existsSync(p)) return p;
    }
    return undefined;
  })();
  const browser = await chromium.launch(local ? { executablePath: local } : {});

  for (const scheme of ['light', 'dark']) {
    const ctx = await browser.newContext({ colorScheme: scheme, viewport: { width: 360, height: 740 } });
    const page = await ctx.newPage();
    const errs = [];
    page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
    page.on('pageerror', e => errs.push('pageerror: ' + e.message));

    console.log(`\n=== ${scheme} theme, 360px wide ===`);
    // Discovered from docs/, so a new page cannot ship without these checks.
    for (const f of fs.readdirSync(DOCS).filter(n => n.endsWith('.html')).sort()
                      .map(n => n.replace(/\.html$/, ''))) {
      await page.goto('file://' + path.join(DOCS, f + '.html'));
      await page.waitForTimeout(150);
      // horizontal overflow check at phone width
      const overflow = await page.evaluate(() =>
        document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
      ok(!overflow, `${f}.html no horizontal overflow at 360px`);
      // body must paint an explicit background (artifact/theme requirement)
      const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
      ok(bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent', `${f}.html body has explicit background (${bg})`);
    }
    ok(errs.length === 0, `no console errors across pages${errs.length ? ' -> ' + errs.slice(0, 3).join(' | ') : ''}`);
    await ctx.close();
  }

  // ---- functional: cover tool ----
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  const errs = [];
  page.on('pageerror', e => errs.push(e.message));

  const runCover = async (file) => {
    await page.goto('file://' + path.join(DOCS, 'cover.html'));
    await page.setInputFiles('#file', path.join(FIX, file));
    await page.waitForSelector('#results.show', { timeout: 8000 });
    await page.waitForTimeout(250);
    return page.evaluate(() => ({
      verdict: document.getElementById('vtitle').textContent,
      verdictSub: document.getElementById('vsub').textContent,
      checks: [...document.querySelectorAll('#checks li')].map(li => ({
        pill: li.querySelector('.pill').textContent.trim(),
        name: li.querySelector('.name').textContent.trim(),
        msg:  li.querySelector('.msg').textContent.trim(),
      })),
      platforms: [...document.querySelectorAll('.plat')].map(p => p.textContent.trim()),
    }));
  };
  const check = (r, name) => r.checks.find(c => c.name.toLowerCase() === name);

  console.log('\n=== cover tool, real files ===');
  let r = await runCover('good_3000.jpg');
  ok(check(r, 'resolution').pill === 'PASS', `3000px JPEG -> resolution PASS (${check(r,'resolution').pill})`);
  ok(check(r, 'format').pill === 'PASS', `3000px JPEG -> format PASS`);
  ok(r.verdict === 'Ready to ship', `3000px JPEG -> verdict "${r.verdict}"`);

  r = await runCover('over_4000.jpg');
  // The ceiling is its own check, independent of the floor chain, so an image
  // can be both under the recommendation and over the ceiling and hear both.
  ok(!!check(r, 'oversize'), `4000px -> a separate oversize check fires`);
  ok(check(r, 'oversize').pill === 'WARN', `4000px -> oversize WARN (the ceiling bug we fixed)`);
  ok(/3000px ceiling/.test(check(r, 'oversize').msg), `4000px -> message names the 3000 ceiling`);

  r = await runCover('cmyk_3000.jpg');
  ok(check(r, 'colour').pill === 'FAIL', `CMYK -> colour FAIL (${check(r,'colour').pill}: ${check(r,'colour').msg})`);

  r = await runCover('nonsquare.jpg');
  ok(check(r, 'square').pill === 'FAIL', `1200x1600 -> square FAIL`);
  ok(r.verdict === 'Not ready to upload', `non-square -> verdict "${r.verdict}"`);

  r = await runCover('alpha_3000.png');
  ok(check(r, 'colour').pill === 'WARN', `RGBA PNG -> colour WARN (alpha)`);
  ok(check(r, 'format').pill === 'WARN', `PNG -> format WARN (DistroKid documents JPG only)`);

  // SoundCloud split: a 3000px file over 2MB must fail SC upload only
  const scRow = r.platforms.find(t => /SoundCloud upload/.test(t));
  ok(!!scRow, `SoundCloud upload row present -> "${scRow}"`);

  // The verdict word and the reason behind it must stay separated. Every reason
  // is a lowercase fragment, so with no separator "Pass" ran straight into the
  // number and read as a threshold ("Pass 1400 floor"). Nothing asserted this
  // surface, so the regression shipped with the whole suite green.
  const runTogether = r.platforms.filter(t => /(Pass|Check|Fail)\s*[0-9]/.test(t));
  ok(runTogether.length === 0,
     `no platform row runs its verdict into a number${runTogether.length ? ' -> ' + runTogether.slice(0,2).join(' | ') : ''}`);
  const separated = r.platforms.filter(t => /(Pass|Check|Fail):\s*\S/.test(t));
  ok(separated.length === r.platforms.length,
     `every platform row separates verdict from reason (${separated.length}/${r.platforms.length})`);

  // An undecodable file must not be reported as clear. Chromium cannot decode
  // TIFF, so this arrived with no dimensions and no colour mode, every check
  // that needed them skipped itself, and the verdict said "No blockers" while
  // all seven platform tiles read Fail.
  r = await runCover('cmyk_nonsquare.tif');
  ok(/Could not check/.test(r.verdict), `undecodable file -> verdict "${r.verdict}"`);
  ok(!/No blockers/.test(r.verdictSub), `undecodable file does not claim no blockers -> "${r.verdictSub}"`);
  ok(!!check(r, 'readable'), `undecodable file gets an explicit readable check`);

  // Greyscale+alpha matched the grayscale branch first and lost the flatten
  // advice an RGBA file gets.
  r = await runCover('gray_alpha_3000.png');
  ok(/[Ff]latten/.test(check(r, 'colour').msg), `grayscale+alpha still says flatten -> "${check(r,'colour').msg}"`);

  // The verdict used to be computed from the checks alone, so it could call a
  // file ready while a platform tile below it read Fail.
  r = await runCover('good_3000.jpg');
  const anyFail = r.platforms.some(t => /Fail/.test(t));
  ok(!anyFail || /does not meet/.test(r.verdictSub),
     `verdict admits a failing platform when there is one -> "${r.verdictSub}"`);

  // ---- functional: loudness tool with a known -23 dBFS sine ----
  console.log('\n=== loudness tool, known -23.0 dBFS stereo sine ===');
  await page.goto('file://' + path.join(DOCS, 'loudness.html'));
  await page.setInputFiles('#file', path.join(FIX, 'sine_-23dBFS.wav'));
  await page.waitForSelector('#results.show', { timeout: 60000 });
  await page.waitForTimeout(400);
  const m = await page.evaluate(() => {
    const g = {};
    document.querySelectorAll('.metric').forEach(el => {
      g[el.querySelector('.k').textContent.trim()] = el.querySelector('.v').textContent.trim();
    });
    return { metrics: g, rows: [...document.querySelectorAll('#ptable tr')].map(t => t.textContent.replace(/\s+/g,' ').trim()) };
  });
  const lufs = parseFloat(m.metrics['Integrated']);
  const tp = parseFloat(m.metrics['True peak']);
  console.log('   measured in-browser:', JSON.stringify(m.metrics));
  ok(Math.abs(lufs - (-23.0)) <= 0.3, `browser LUFS ${lufs} within 0.3 of -23.0`);
  ok(tp <= -22 && tp >= -24, `browser true peak ${tp} dBTP near -23 (sine amplitude)`);
  const appleRow = m.rows.find(t => /Apple/.test(t));
  ok(/never boosted|as-is/.test(appleRow), `Apple row respects attenuate-only -> "${appleRow}"`);

  // A -23 LUFS master is 9 LU below YouTube's -14 reference. YouTube turns loud
  // content down and never raises quiet content, so it must not claim a lift.
  const ytRow = m.rows.find(t => /YouTube/.test(t));
  ok(!/turned up/.test(ytRow), `YouTube does not claim to boost a quiet master -> "${ytRow}"`);
  ok(/never boosted|as-is/.test(ytRow), `YouTube row is attenuate-only -> "${ytRow}"`);
  // Tidal's boost behaviour is disputed, so it must not assert one either.
  const tidalRow = m.rows.find(t => /Tidal/.test(t));
  ok(!/turned up/.test(tidalRow), `Tidal does not assert a boost -> "${tidalRow}"`);

  // A loud master must be judged against the stricter ceiling the page states.
  // The flag used to be a flat tp > -1, so a -1.5 dBTP club master passed while
  // both pages told the reader -2 applied above -14 LUFS. The declared sample
  // rate must also come from the file header: decodeAudioData resamples to the
  // audio device's rate, which reported 44.1k for every file on this machine
  // and would report 48k for every file on a 48k interface.
  console.log('\n=== loud master: stricter ceiling, and the file\'s own rate ===');
  await page.goto('file://' + path.join(DOCS, 'loudness.html'));
  await page.setInputFiles('#file', path.join(FIX, 'loud_44100.wav'));
  await page.waitForSelector('#results.show', { timeout: 60000 });
  await page.waitForTimeout(400);
  const loud = await page.evaluate(() => {
    const g = {};
    document.querySelectorAll('.metric').forEach(el => {
      g[el.querySelector('.k').textContent.trim()] = {
        v: el.querySelector('.v').textContent.trim(),
        u: el.querySelector('.u').textContent.trim(),
        flag: el.classList.contains('flag'),
      };
    });
    return { m: g, rows: [...document.querySelectorAll('#ptable tr')].map(t => t.textContent.replace(/\s+/g, ' ').trim()) };
  });
  ok(parseFloat(loud.m['Integrated'].v) > -14, `fixture is louder than -14 LUFS (${loud.m['Integrated'].v})`);
  ok(loud.m['True peak'].flag, `true peak flagged against the -2 ceiling (${loud.m['True peak'].v} ${loud.m['True peak'].u})`);
  ok(/over -2/.test(loud.m['True peak'].u), `the stricter ceiling is named -> "${loud.m['True peak'].u}"`);
  ok(/44\.1k/.test(loud.m['Duration'].u), `sample rate read from the file, not the device -> "${loud.m['Duration'].u}"`);

  // A disputed platform must not print a gain figure beside "may not be raised".
  await page.goto('file://' + path.join(DOCS, 'loudness.html'));
  await page.setInputFiles('#file', path.join(FIX, 'sine_-23dBFS.wav'));
  await page.waitForSelector('#results.show', { timeout: 60000 });
  await page.waitForTimeout(400);
  const quietRows = await page.evaluate(() =>
    [...document.querySelectorAll('#ptable tr')].map(t => t.textContent.replace(/\s+/g, ' ').trim()));
  const tRow = quietRows.find(t => /Tidal/.test(t));
  ok(!/[+-]?\d+\.\d+ dB/.test(tRow), `Tidal states no gain it will not commit to -> "${tRow}"`);

  // ---- audio edge cases: must not leak Infinity or hang ----
  console.log('\n=== loudness edge cases ===');
  for (const [f, want] of [['silence.wav', /nothing to measure/], ['tiny_200ms.wav', /Too short/]]) {
    await page.goto('file://' + path.join(DOCS, 'loudness.html'));
    await page.setInputFiles('#file', path.join(FIX, f));
    await page.waitForTimeout(3000);
    const o = await page.evaluate(() => ({ status: document.getElementById('status').textContent, text: document.body.innerText }));
    ok(want.test(o.status), `${f} -> clear message ("${o.status.slice(0, 46)}")`);
    ok(!/Infinity/.test(o.text), `${f} -> no Infinity leaked to the UI`);
  }

  // ---- functional: checklist persistence ----
  console.log('\n=== release checklist ===');
  await page.goto('file://' + path.join(DOCS, 'release.html'));
  await page.click('li[data-id="s0i0"]');
  let pct = await page.textContent('#pct');
  ok(/^1 \//.test(pct), `ticking an item updates progress (${pct})`);
  await page.reload();
  await page.waitForTimeout(150);
  pct = await page.textContent('#pct');
  ok(/^1 \//.test(pct), `progress survives reload (${pct})`);
  await page.click('#reset');
  pct = await page.textContent('#pct');
  ok(/^0 \//.test(pct), `reset clears progress (${pct})`);

  ok(errs.length === 0, `no uncaught page errors during functional tests${errs.length ? ' -> ' + errs.join(' | ') : ''}`);

  await browser.close();
  console.log(`\n${failures === 0 ? 'ALL CHECKS PASSED' : failures + ' CHECK(S) FAILED'}`);
  process.exit(failures ? 1 : 0);
})();
