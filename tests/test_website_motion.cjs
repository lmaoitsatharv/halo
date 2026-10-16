// Browser regression for the Pause motion observer loop and adjacent controls.
// npm install --no-save playwright && npx playwright install chromium
// node tests/test_website_motion.cjs [https://deployment.example]
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');

async function dragAcrossText(page, selector) {
  const element = page.locator(selector);
  // These illustrations keep moving, so scroll without waiting for a static box.
  await element.evaluate(el => el.scrollIntoView({block:'center', behavior:'instant'}));
  await page.waitForTimeout(150);
  await page.evaluate(() => getSelection().removeAllRanges());
  const start = await element.evaluate(el => {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (!node.textContent.trim()) continue;
      const range = document.createRange();
      range.setStart(node, 0);range.setEnd(node, Math.min(3, node.length));
      const rect = range.getBoundingClientRect();
      if (rect.width && rect.height) return {x:rect.x + rect.width / 2, y:rect.y + rect.height / 2};
    }
    throw new Error('No visible text for drag test');
  });
  await page.mouse.move(start.x, start.y);await page.mouse.down();
  await page.mouse.move(start.x + 100, start.y + 12, {steps:12});await page.mouse.up();
  return page.evaluate(() => getSelection().toString());
}

async function main() {
  let server;
  let base = process.argv[2];
  if (!base) {
    const root = path.resolve(process.env.HALO_WEBSITE_DIR || path.join(__dirname, '..', 'website'));
    const types = {'.html':'text/html', '.css':'text/css', '.js':'text/javascript', '.svg':'image/svg+xml', '.png':'image/png', '.glb':'model/gltf-binary'};
    server = http.createServer((req, res) => {
      const name = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
      if (name.startsWith('/_vercel/')) { res.writeHead(204); res.end(); return; }
      const file = path.resolve(root, '.' + (name === '/' ? '/index.html' : name));
      if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
        res.writeHead(404); res.end(); return;
      }
      res.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
      fs.createReadStream(file).pipe(res);
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    base = `http://127.0.0.1:${server.address().port}`;
  }
  const browser = await chromium.launch({headless: true,
    ...(process.env.HALO_BROWSER_CHANNEL ? {channel: process.env.HALO_BROWSER_CHANNEL} : {})});
  // A broken microtask loop can stall the page without producing an exception.
  const watchdog = setTimeout(() => { console.error('Website became unresponsive'); browser.process()?.kill(); process.exit(1); }, 90000);
  const results = [];
  try {
    for (const mode of ['desktop', 'touch', 'reduced', 'webgl-fallback']) {
      const context = await browser.newContext({
        viewport: mode === 'touch' ? {width: 390, height: 844} : {width: 1440, height: 1000},
        hasTouch: mode === 'touch', isMobile: mode === 'touch',
        reducedMotion: mode === 'reduced' ? 'reduce' : 'no-preference',
      });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      if (mode === 'webgl-fallback') await page.addInitScript(() => {
        const getContext = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = function(type, ...args) {
          return /webgl/.test(type) ? null : getContext.call(this, type, ...args);
        };
      });
      await page.goto(base, {waitUntil: 'networkidle', timeout: 30000});
      await page.waitForTimeout(1900);
      const button = page.locator('#motion-toggle');
      if (mode === 'reduced') {
        assert.match(await button.innerText(), /Reduced motion/);
        await button.click();
        assert.equal(await button.getAttribute('aria-pressed'), 'true');
        await page.emulateMedia({reducedMotion: 'no-preference'});
      }
      // Real pointer drags on rendered text must rotate without selecting it.
      const hero = page.locator('#hero-installation');
      await page.evaluate(() => getSelection().removeAllRanges());
      const start = await page.locator('#hero-current').evaluate(el => {
        const node = [...el.childNodes].find(n => n.nodeType === Node.TEXT_NODE && n.textContent.trim());
        const range = document.createRange();
        range.setStart(node, 0);range.setEnd(node, Math.min(3, node.length));
        const rect = range.getBoundingClientRect();
        return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
      });
      if (mode === 'touch') {
        const input = await context.newCDPSession(page);
        await input.send('Input.dispatchTouchEvent', {type:'touchStart', touchPoints:[start]});
        for (let step = 1; step <= 6; step++) {
          await input.send('Input.dispatchTouchEvent', {type:'touchMove', touchPoints:[{x:start.x + step * 12, y:start.y}]});
          await page.waitForTimeout(20);
        }
        await input.send('Input.dispatchTouchEvent', {type:'touchEnd', touchPoints:[]});
        await input.detach();
      } else {
        await page.mouse.move(start.x, start.y);await page.mouse.down();
        await page.mouse.move(start.x + 145, start.y + 30, {steps:12});await page.mouse.up();
        assert.equal(await page.evaluate(() => document.activeElement.id), 'hero-installation');
      }
      assert.equal(await page.evaluate(() => getSelection().toString()), '');
      assert.equal(await hero.getAttribute('data-rotation'), 'custom');
      await hero.focus();await page.keyboard.press('Home');
      assert.equal(await hero.getAttribute('data-rotation'), 'centered');
      await page.keyboard.press('ArrowRight');
      assert.equal(await hero.getAttribute('data-rotation'), 'custom');
      await page.locator('#recenter-installation').click();
      assert.equal(await hero.getAttribute('data-rotation'), 'centered');
      assert.equal(await page.locator('.hero-description').evaluate(el => getComputedStyle(el).userSelect), 'auto');
      await page.locator('#hero-play').focus();await page.keyboard.press('Enter');
      assert.equal(await page.locator('#hero-play').getAttribute('aria-pressed'), 'true');
      await page.keyboard.press('Enter');
      assert.equal(await page.locator('#hero-play').getAttribute('aria-pressed'), 'false');
      await page.evaluate(() => {
        window.__bodyMutations = 0;
        new MutationObserver(records => { window.__bodyMutations += records.length; })
          .observe(document.body, {attributes: true, attributeFilter: ['class']});
      });
      for (let cycle = 0; cycle < 3; cycle++) {
        await (mode === 'touch' ? button.tap() : button.click());
        assert.equal(await button.getAttribute('aria-pressed'), 'true');
        await page.waitForTimeout(150);
        const before = await page.evaluate(() => ({
          frames: document.querySelector('#world-canvas').dataset.frames,
          clock: document.documentElement.style.getPropertyValue('--journey-time'),
          time: document.querySelector('#demo-time').textContent,
        }));
        await page.waitForTimeout(350);
        assert.deepEqual(await page.evaluate(() => ({
          frames: document.querySelector('#world-canvas').dataset.frames,
          clock: document.documentElement.style.getPropertyValue('--journey-time'),
          time: document.querySelector('#demo-time').textContent,
        })), before, 'Pause should freeze page motion and the visual demo');
        // Unrelated body state must not re-enter the paused observer.
        await page.evaluate(() => document.body.classList.toggle('test-unrelated-state'));
        assert.match(await button.innerText(), /Resume motion/);
        await (mode === 'touch' ? button.tap() : button.click());
        assert.equal(await button.getAttribute('aria-pressed'), 'false');
        await page.waitForTimeout(250);
        assert.notEqual(await page.evaluate(() => document.documentElement.style.getPropertyValue('--journey-time')), before.clock);
      }
      const mutationCount = await page.evaluate(() => window.__bodyMutations);
      assert.ok(mutationCount < 80, `Excessive body mutations: ${mutationCount}`);
      // Space/Enter, OS reduced motion changes and the light demo still work.
      await button.focus();
      await page.keyboard.press('Space');
      assert.equal(await button.getAttribute('aria-pressed'), 'true');
      await page.keyboard.press('Enter');
      assert.equal(await button.getAttribute('aria-pressed'), 'false');
      await page.emulateMedia({reducedMotion: 'reduce'});
      await page.waitForTimeout(100);
      assert.match(await button.innerText(), /Reduced motion/);
      await page.emulateMedia({reducedMotion: 'no-preference'});
      await page.locator('[data-effect="pulse"]').click();
      assert.equal(await page.locator('#effect-stage').getAttribute('data-effect'), 'pulse');
      await page.locator('[data-mode="still"]').click();
      assert.equal(await page.locator('.effect-halo').evaluate(el => el.style.animationPlayState), 'paused');
      await page.locator('[data-mode="flow"]').click();
      await page.locator('#effect-stage').scrollIntoViewIfNeeded();
      await page.waitForFunction(() => document.querySelector('.effect-halo').style.animationPlayState === '');
      assert.equal(await page.locator('.effect-halo').evaluate(el => el.style.animationPlayState), '');
      assert.equal(await dragAcrossText(page, '#effect-name'), '', 'Light preview text should not select');
      assert.equal(await dragAcrossText(page, '#lyric-line-current'), '', 'Lyric preview text should not select');
      await page.locator('[data-style="fisheye"]').click();
      assert.equal(await page.locator('#lyric-stage').getAttribute('data-style'), 'fisheye');
      assert.equal(await dragAcrossText(page, '.scene-words>p'), '', 'Immersive preview text should not select');
      await page.locator('[data-scene="cinema"]').click();
      await page.locator('#scene-expand').click();
      assert.equal(await page.locator('#scene-preview').getAttribute('aria-modal'), 'true');
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('#scene-preview').getAttribute('aria-modal'), null);
      assert.equal(await dragAcrossText(page, '.music-polaroid figcaption'), '', 'Music illustration caption should not select');
      const model = page.locator('.music-model-stage');
      if (await model.evaluate(el => el.classList.contains('is-ready'))) {
        const rect = await model.boundingBox();
        await page.mouse.move(rect.x + rect.width / 2, rect.y + rect.height / 2);
        await page.mouse.down();
        await page.mouse.move(rect.x + rect.width / 2 + 70, rect.y + rect.height / 2, {steps:10});
        await page.mouse.up();
        assert.equal(await model.getAttribute('data-rotation'), 'custom');
      }
      assert.notEqual(await dragAcrossText(page, '.hero-description'), '', 'Ordinary page text should remain selectable');
      await page.evaluate(() => getSelection().removeAllRanges());
      assert.equal(await page.locator('.nav-repo').getAttribute('href'), 'https://github.com/lmaoitsatharv/halo');
      for (const download of await page.locator('[data-download]').all()) {
        assert.equal(await download.getAttribute('href'), 'https://github.com/lmaoitsatharv/halo/releases/latest/download/Halo-Windows-x64.zip');
        assert.match(await download.innerText(), /Download Windows ZIP/);
      }
      assert.deepEqual(errors, []);
      results.push({mode, dragWithoutSelection:true, protectedPreviews:5, ordinaryTextSelectable:true, pauseCycles: 3, bodyMutations: mutationCount, pageErrors: errors.length, result: 'passed'});
      if (process.env.HALO_QA_OUTPUT) {
        await page.evaluate(() => scrollTo(0, 0));
        await page.waitForTimeout(300);
        await page.screenshot({path: path.join(process.env.HALO_QA_OUTPUT, `${mode}.png`)});
      }
      await context.close();
    }
    console.log(JSON.stringify({url: base, results}, null, 2));
  } finally {
    clearTimeout(watchdog);
    await browser.close();
    if (server) await new Promise(resolve => server.close(resolve));
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
