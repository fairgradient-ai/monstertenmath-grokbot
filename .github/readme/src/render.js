// node render.js in.html out.png width height
const { chromium } = require('playwright');
(async () => {
  const [inp, out, w, h] = process.argv.slice(2);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: +w, height: +h }, deviceScaleFactor: 2 });
  await p.goto('file://' + require('path').resolve(inp));
  await p.evaluate(() => document.fonts.ready);
  await p.waitForTimeout(400);
  await p.screenshot({ path: out });
  await b.close();
})();
