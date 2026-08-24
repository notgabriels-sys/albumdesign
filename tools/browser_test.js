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
      // Read out of the element that holds it. Regexing the tile's whole text
      // for /\bPass\b/ silently matches nothing, because the name runs
      // straight into the verdict ("BandcampPass: 1400 floor") and "p" to "P"
      // is not a word boundary. That assertion passed on every file, including
      // ones where seven tiles said Pass.
      platformVerdicts: [...document.querySelectorAll('.plat b')].map(b => b.textContent.trim()),
      specs: [...document.querySelectorAll('#specs div')]
        .map(row => row.querySelector('dt').textContent.trim() + '=' +
                    row.querySelector('dd').textContent.trim()),
    }));
  };
  const check = (r, name) => r.checks.find(c => c.name.toLowerCase() === name);
  // Same list, but an absence comes back as a value instead of undefined.
  // Reading `.pill` off a check that a regression removed threw a TypeError and
  // killed node, so a mutation sweep read the run as crashed rather than as a
  // failing assertion: forcing every file down the undecodable path removed
  // Square, Resolution and Colour from every result and took the suite with
  // them. `check` deliberately still returns undefined, because the two
  // assertions that test whether a check exists at all use `!!check(...)` and
  // `!check(...)`, and a helper that always returned an object would make both
  // of them vacuously true. Use `must` to read a field, `check` to ask whether
  // there is one.
  const must = (r, name) => check(r, name) || { pill: '(absent)', name, msg: '(absent)' };

  console.log('\n=== cover tool, real files ===');
  // ---- four verdicts nothing could make fail ----
  // Found by mutation: turning each of these branches into a "pass" left the
  // whole browser suite green. readable FAIL is the one that matters, because
  // "stop the cover checker calling unreadable files clear" was a deliberate
  // fix and nothing was holding it in place.
  let cov = await runCover('small_1000.jpg');
  ok(must(cov, 'resolution').pill === 'FAIL',
    `1000px is below the 1400 floor (resolution -> ${must(cov, 'resolution').pill})`);

  cov = await runCover('notanimage.jpg');
  ok(must(cov, 'format').pill === 'FAIL',
    `a file that is not an image has no usable format (format -> ${must(cov, 'format').pill})`);
  ok(must(cov, 'readable').pill === 'FAIL',
    `and it is not readable either (readable -> ${must(cov, 'readable').pill})`);
  ok(!/Ready to ship/.test(cov.verdict),
    `so it is not ready to ship ("${cov.verdict}")`);

  // 17 MB, over the 10 MB ceiling Ditto and DistroKid document.
  cov = await runCover('cmyk_nonsquare.tif');
  ok(must(cov, 'filesize').pill === 'WARN',
    `17 MB is over the documented ceiling (filesize -> ${must(cov, 'filesize').pill})`);

  let r = await runCover('good_3000.jpg');
  ok(must(r, 'resolution').pill === 'PASS', `3000px JPEG -> resolution PASS (${must(r, 'resolution').pill})`);
  ok(must(r, 'format').pill === 'PASS', `3000px JPEG -> format PASS`);
  ok(r.verdict === 'Ready to ship', `3000px JPEG -> verdict "${r.verdict}"`);

  r = await runCover('over_4000.jpg');
  // The ceiling is its own check, independent of the floor chain, so an image
  // can be both under the recommendation and over the ceiling and hear both.
  ok(!!check(r, 'oversize'), `4000px -> a separate oversize check fires`);
  ok(must(r, 'oversize').pill === 'WARN', `4000px -> oversize WARN (the ceiling bug we fixed)`);
  ok(/3000px ceiling/.test(must(r, 'oversize').msg), `4000px -> message names the 3000 ceiling`);

  r = await runCover('cmyk_3000.jpg');
  ok(must(r, 'colour').pill === 'FAIL', `CMYK -> colour FAIL (${must(r, 'colour').pill}: ${must(r, 'colour').msg})`);

  r = await runCover('nonsquare.jpg');
  ok(must(r, 'square').pill === 'FAIL', `1200x1600 -> square FAIL`);
  ok(r.verdict === 'Not ready to upload', `non-square -> verdict "${r.verdict}"`);

  r = await runCover('alpha_3000.png');
  ok(must(r, 'colour').pill === 'WARN', `RGBA PNG -> colour WARN (alpha)`);
  ok(must(r, 'format').pill === 'WARN', `PNG -> format WARN (DistroKid documents JPG only)`);

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

  // ---- a header is not an image ----
  // The guard above was `!w || !h`, which asks whether we have numbers rather
  // than whether anything was measured, and a PNG IHDR supplies numbers for
  // free. A 33-byte file holding a signature and an IHDR and no image data was
  // reported as a 3000 x 3000 cover, "Good to go, with notes", with four
  // checks passing and all seven platform tiles reading Pass.
  //
  // The verdict, the checks list, the spec table and the platform grid all
  // state this, so all four are asserted. Fixing only the headline leaves a
  // page whose first line says nothing was measured over seven tiles saying
  // Pass on a size nobody read.
  for (const [f, claim] of [['png_header_only.png', '3000'], ['png_claims_40000.png', '40000']]) {
    r = await runCover(f);
    ok(/Could not check/.test(r.verdict), `${f} -> verdict "${r.verdict}"`);
    // Read once and default the message, because a mutation that deletes the
    // readable check entirely made `must(r, 'readable').msg` throw, node died,
    // and the sweep harness saw a run with no verdict line rather than a
    // failing assertion. A test that crashes on the regression it exists to
    // catch is not reporting, it is exiting.
    const readable = must(r, 'readable');
    ok(readable.pill === 'FAIL', `${f} -> readable FAIL (${readable.pill})`);
    ok(new RegExp('header claims ' + claim).test(readable.msg),
       `${f} -> the message names the ${claim}px claim as a claim -> "${readable.msg.slice(0, 60)}"`);
    ok(!check(r, 'square') && !check(r, 'resolution'),
       `${f} -> nothing grades a size that was never decoded (square/resolution absent)`);
    ok(r.checks.every(c => c.pill !== 'PASS' || c.name === 'Filesize'),
       `${f} -> the only PASS left is the byte count, which really was measured` +
       ` -> ${r.checks.filter(c => c.pill === 'PASS').map(c => c.name).join(',') || 'none'}`);
    const passing = r.platformVerdicts.filter(v => v === 'Pass');
    ok(r.platformVerdicts.length === 7 && passing.length === 0,
       `${f} -> no platform tile passes an unmeasured file (${passing.length} of ${r.platformVerdicts.length} do)`);
    const dims = r.specs.find(x => x.startsWith('Dimensions='));
    ok(/claimed, not decoded/.test(dims),
       `${f} -> the spec table calls the size a claim -> "${dims}"`);
  }

  // The other half of the same guard: a file this browser really can decode
  // must still be graded. Dropping the header numbers on every undecoded file
  // is only correct while `decoded` is true for the files that decode.
  r = await runCover('good_3000.jpg');
  ok(must(r, 'resolution').pill === 'PASS',
     `a file that does decode is still measured (resolution -> ${must(r, 'resolution').pill})`);
  ok(r.platformVerdicts.filter(v => v === 'Pass').length > 0,
     `and its platform tiles still pass (${r.platformVerdicts.join(',')})`);

  // Greyscale+alpha matched the grayscale branch first and lost the flatten
  // advice an RGBA file gets.
  r = await runCover('gray_alpha_3000.png');
  ok(/[Ff]latten/.test(must(r, 'colour').msg), `grayscale+alpha still says flatten -> "${must(r, 'colour').msg}"`);

  // The verdict used to be computed from the checks alone, so it could call a
  // file ready while a platform tile below it read Fail.
  r = await runCover('good_3000.jpg');
  const anyFail = r.platforms.some(t => /Fail/.test(t));
  ok(!anyFail || /does not meet/.test(r.verdictSub),
     `verdict admits a failing platform when there is one -> "${r.verdictSub}"`);

  // ---- split sheet: a share nobody entered is not a zero share ----
  // splits.html had no functional coverage at all, and it is the document that
  // decides who GEMA and GVL pay. readRow and sum both used
  // parseFloat(x)||0, which turns anything unreadable into a zero and adds it
  // in silently, so three invalid sheets totalled exactly 100 and were badged
  // pass. All three are proved here against the real page.
  console.log('\n=== split sheet totals only count shares it could read ===');
  await page.goto('file://' + path.join(DOCS, 'splits.html'));
  await page.waitForTimeout(200);
  const split = async (vals) => page.evaluate((vals) => {
    const tb = document.getElementById('writers');
    tb.innerHTML = '';
    for (let i = 0; i < vals.length; i++) document.getElementById('addw').click();
    [...tb.querySelectorAll('tr')].forEach((tr, i) => {
      tr.querySelector('.f-name').value = 'Person ' + (i + 1);
      tr.querySelector('.f-pct').value = vals[i];
    });
    tb.querySelector('tr').dispatchEvent(new Event('input', { bubbles: true }));
    const b = document.getElementById('wtotal');
    return {
      pass: b.className.includes('pass'),
      text: b.textContent.trim(),
      issues: document.getElementById('rowissues').textContent.trim(),
    };
  }, vals);

  let sp = await split(['50', '50']);
  ok(sp.pass, `an honest 50/50 still passes (${sp.text})`);
  ok(sp.issues === '', 'a valid sheet reports no row problems');

  sp = await split(['150', '-50']);
  ok(!sp.pass, `150 and -50 does not pass just because it totals 100 (${sp.text})`);
  ok(/negative/i.test(sp.issues), `it names the negative share -> "${sp.issues}"`);

  // Named for the unreadable branch, but that is not what it exercises:
  // input[type=number] sanitises "abc" to "", so this reaches problems() as a
  // missing share. Kept because it is the path a real typo takes, and renamed
  // so it stops claiming coverage it does not have. See the comment on the
  // isFinite branch in splits.html.
  sp = await split(['50', '50', 'abc']);
  ok(!sp.pass, `a share the number input rejected does not pass (${sp.text})`);
  ok(/Person 3/.test(sp.issues), `it names the row -> "${sp.issues}"`);

  sp = await split(['100', '']);
  ok(!sp.pass, `a named person with no share entered does not pass (${sp.text})`);
  ok(/Person 2/.test(sp.issues), `it names the person -> "${sp.issues}"`);

  // Every failing fixture above totals exactly 100, so the term that checks
  // the shares add up was never exercised: a mutation sweep deleted `totals`
  // from `ok=totals&&!probs.length`, and separately forced it true, and both
  // survived a green suite. Telling you the sheet does not add up is the
  // page's whole job.
  sp = await split(['50', '40']);
  ok(!sp.pass, `90% does not pass just because every row is readable (${sp.text})`);
  ok(sp.issues === '', 'a short total is not blamed on a row that is fine');
  ok(/must total 100/.test(sp.text), `the badge says what is wrong -> "${sp.text}"`);

  sp = await split(['60', '60']);
  ok(!sp.pass, `120% does not pass either (${sp.text})`);

  // The helper always filled in a name, so a share with no name against it was
  // never tested. It is the row the exported sheet used to drop while sum()
  // kept counting its share, so the listing did not add up to its own total.
  const noName = await page.evaluate(() => {
    const tb = document.getElementById('writers');
    tb.innerHTML = '';
    ['50', '50'].forEach(() => document.getElementById('addw').click());
    const trs = [...tb.querySelectorAll('tr')];
    trs[0].querySelector('.f-name').value = 'Person 1';
    trs[0].querySelector('.f-pct').value = '50';
    trs[1].querySelector('.f-name').value = '';
    trs[1].querySelector('.f-pct').value = '50';
    trs[0].dispatchEvent(new Event('input', { bubbles: true }));
    const b = document.getElementById('wtotal');
    return { pass: b.className.includes('pass'), text: b.textContent.trim(),
             issues: document.getElementById('rowissues').textContent.trim() };
  });
  ok(!noName.pass, `a share with nobody's name on it does not pass (${noName.text})`);
  ok(/has no name/.test(noName.issues), `it says whose share is unattributed -> "${noName.issues}"`);

  // A blank form is someone starting work, not a mistake to shout about.
  const blank = await page.evaluate(() => {
    const tb = document.getElementById('writers');
    tb.innerHTML = '';
    document.getElementById('addw').click();
    tb.querySelector('tr').dispatchEvent(new Event('input', { bubbles: true }));
    return document.getElementById('rowissues').textContent.trim();
  });
  ok(blank === '', `an untouched empty row raises nothing (got "${blank}")`);

  // ---- a blank share must not become a zero share by being saved ----
  // readRow kept parseFloat(x)||0 after sum() and problems() were fixed for
  // it, and readRow is what feeds save(). A blank box persisted as 0, so a
  // reload turned "nobody entered this" into "this person gets nothing", the
  // badge went fail -> pass, and the warning naming the row disappeared. The
  // badge fix was undone by pressing reload. Proved in Chromium before fixing.
  console.log('\n=== a blank share survives a reload as a blank share ===');
  await page.goto('file://' + path.join(DOCS, 'splits.html'));
  await page.waitForTimeout(200);
  const beforeReload = await page.evaluate(() => {
    const tb = document.getElementById('writers');
    tb.innerHTML = '';
    ['100', ''].forEach(() => document.getElementById('addw').click());
    [...tb.querySelectorAll('tr')].forEach((tr, i) => {
      tr.querySelector('.f-name').value = 'Person ' + (i + 1);
      tr.querySelector('.f-pct').value = ['100', ''][i];
    });
    tb.querySelector('tr').dispatchEvent(new Event('input', { bubbles: true }));
    const b = document.getElementById('wtotal');
    return { shares: [...tb.querySelectorAll('.f-pct')].map(i => i.value),
             pass: b.className.includes('pass') };
  });
  ok(!beforeReload.pass, 'the sheet fails before the reload');
  await page.reload();
  await page.waitForFunction(() => document.querySelectorAll('#writers tr').length > 0);
  await page.waitForTimeout(200);
  const afterReload = await page.evaluate(() => {
    const tb = document.getElementById('writers');
    const b = document.getElementById('wtotal');
    return { shares: [...tb.querySelectorAll('.f-pct')].map(i => i.value),
             pass: b.className.includes('pass'),
             issues: document.getElementById('rowissues').textContent.trim() };
  });
  ok(afterReload.shares[1] === '',
     `the empty share is still empty after a reload -> ${JSON.stringify(afterReload.shares)}`);
  ok(!afterReload.pass, 'and the sheet still fails, rather than passing on an invented zero');
  ok(/Person 2/.test(afterReload.issues),
     `and it still names the person -> "${afterReload.issues}"`);

  // ---- the sheet that leaves the browser says what the page knows ----
  // asText() printed "0%" for a share nobody entered, put a signature line
  // under it and totalled to 100, so the document read complete. It also
  // dropped a row that had a share but no name while sum() still counted that
  // share, so the listing did not add up to its own total. And Copy said only
  // "Copied to the clipboard." where Print had always warned.
  console.log('\n=== the exported split sheet states what the page knows ===');
  {
    const ex = await browser.newPage();
    await ex.addInitScript(() => {
      window.__clip = null;
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: (t) => { window.__clip = t; return Promise.resolve(); } },
        configurable: true,
      });
    });
    await ex.goto('file://' + path.join(DOCS, 'splits.html'));
    await ex.waitForTimeout(200);
    // clipboard.writeText resolves asynchronously, so the status line is still
    // the previous run's when click() returns. Reading it straight away made
    // one assertion pass on the message left by the fixture before it, which
    // is the same read-the-wrong-thing defect the rest of this sweep is
    // about. Clear it, then wait for the page to write a new one.
    const fill = async (vals) => {
      await ex.evaluate((vals) => {
        const tb = document.getElementById('writers');
        tb.innerHTML = '';
        vals.forEach(() => document.getElementById('addw').click());
        [...tb.querySelectorAll('tr')].forEach((tr, i) => {
          tr.querySelector('.f-name').value = vals[i][0];
          tr.querySelector('.f-pct').value = vals[i][1];
        });
        tb.querySelector('tr').dispatchEvent(new Event('input', { bubbles: true }));
        window.__clip = null;
        document.getElementById('live').textContent = '';
        document.getElementById('copy').click();
      }, vals);
      await ex.waitForFunction(() => document.getElementById('live').textContent !== '');
      return ex.evaluate(() => ({
        clip: window.__clip,
        live: document.getElementById('live').textContent.trim(),
      }));
    };

    let e = await fill([['Person 1', '100'], ['Person 2', '']]);
    const line2 = e.clip.split('\n').find(l => /Person 2/.test(l) && /·/.test(l));
    ok(!/0%/.test(line2), `a share nobody entered is not exported as 0% -> "${line2}"`);
    ok(/not filled in/.test(line2), `it says so instead -> "${line2}"`);
    ok(/does not cover the sheet/.test(e.clip),
       'the total discloses that it does not cover every row');

    e = await fill([['Person 1', '50'], ['', '50']]);
    ok(/name missing/.test(e.clip),
       'a row with a share but no name is printed rather than dropped from the sheet');

    // Copy hands out the same document Print does, so it says the same thing.
    ok(/could not be read/.test(e.live),
       `Copy warns like Print does -> "${e.live}"`);
    // A genuinely clean sheet needs both sides filled: the recording table
    // starts with one empty row, so filling only the composition side leaves
    // the GVL half totalling 0 and the warning is right to fire. The first
    // version of this fixture made that mistake and read as a false failure.
    const clean = await ex.evaluate(() => {
      [['writers', 'addw'], ['performers', 'addr']].forEach(([id, add]) => {
        const tb = document.getElementById(id);
        tb.innerHTML = '';
        document.getElementById(add).click();
        document.getElementById(add).click();
        [...tb.querySelectorAll('tr')].forEach((tr, i) => {
          tr.querySelector('.f-name').value = 'Person ' + (i + 1);
          tr.querySelector('.f-pct').value = ['60', '40'][i];
        });
      });
      document.querySelector('#writers tr').dispatchEvent(new Event('input', { bubbles: true }));
      document.getElementById('live').textContent = '';
      document.getElementById('copy').click();
      return null;
    });
    await ex.waitForFunction(() => document.getElementById('live').textContent !== '');
    const cleanLive = await ex.evaluate(() => document.getElementById('live').textContent.trim());
    ok(cleanLive === 'Copied to the clipboard.',
       `and a sheet with both sides at 100 copies without a warning -> "${cleanLive}"`);
    await ex.close();
  }

  // ---- a collaborator's name is attacker-shaped text ----
  // The rule in CLAUDE.md: any page echoing user text escapes the apostrophe
  // too, and a browser test asserts the rendered result carries no handler.
  // splits.html echoes names in two places, the signature block through
  // innerHTML + esc() and the row-problem line through textContent, and had no
  // such test. Proved non-vacuous by trimming esc() back to & alone, the same
  // unsafe trim from an earlier page: that injects a live IMG[onerror] into
  // the signature block and fires a real dialog.
  console.log('\n=== a hostile name cannot execute from the split sheet ===');
  {
    let dialogs = 0;
    const xp = await browser.newPage();
    xp.on('dialog', async d => { dialogs++; await d.dismiss(); });
    await xp.goto('file://' + path.join(DOCS, 'splits.html'));
    await xp.waitForTimeout(200);

    for (const name of [
      `a' onmouseover='alert(1)' x='`,
      `<img src=x onerror="alert(1)">`,
      `"><script>alert(1)</script>`,
    ]) {
      const r = await xp.evaluate((name) => {
        const tb = document.getElementById('writers');
        tb.innerHTML = '';
        document.getElementById('addw').click();
        document.getElementById('addw').click();
        const rows = [...tb.querySelectorAll('tr')];
        rows[0].querySelector('.f-name').value = name;
        rows[0].querySelector('.f-pct').value = '50';
        // a second row with no share, so the row-problem line renders too
        rows[1].querySelector('.f-name').value = name;
        rows[1].querySelector('.f-pct').value = '';
        rows[0].dispatchEvent(new Event('input', { bubbles: true }));
        const handlers = [...document.querySelectorAll('*')]
          .filter(el => [...el.attributes].some(a => /^on/i.test(a.name)));
        return {
          shownAsText: document.getElementById('sigs').textContent.includes(name),
          injected: !!document.querySelector('#sigs img, #sigs script, #rowissues img, #rowissues script'),
          handlers: handlers.length,
        };
      }, name);
      await xp.hover('#sigs').catch(() => {});
      await xp.waitForTimeout(80);
      const label = JSON.stringify(name);
      ok(r.shownAsText, `${label} appears as literal text in the signature block`);
      ok(!r.injected, `${label} creates no element in either echo path`);
      ok(r.handlers === 0, `${label} creates no inline handler (${r.handlers} found)`);
    }
    ok(dialogs === 0, `no hostile name executed anything (${dialogs} dialogs)`);
    await xp.close();
  }

  ok(errs.length === 0, `no uncaught page errors during functional tests${errs.length ? ' -> ' + errs.join(' | ') : ''}`);

  await browser.close();
  console.log(`\n${failures === 0 ? 'ALL CHECKS PASSED' : failures + ' CHECK(S) FAILED'}`);
  process.exit(failures ? 1 : 0);
})();
