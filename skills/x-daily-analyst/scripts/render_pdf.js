// HTML → PDF renderer for X-daily reports (Playwright / Chromium).
//
// Usage:
//   node render_pdf.js <input.html> <output.pdf>
//
// Playwright module resolution (first match wins):
//   1. env PLAYWRIGHT_MODULE_PATH — absolute path to playwright package dir or its entry
//   2. require('playwright') — project-local or global npm install
//
// Notes:
//   - HTML must use UTF-8 + <meta charset="utf-8">
//   - printBackground:true keeps category header backgrounds

const path = require('path');

function loadPlaywright() {
  const custom = process.env.PLAYWRIGHT_MODULE_PATH;
  if (custom) {
    return require(path.resolve(custom));
  }
  try {
    return require('playwright');
  } catch (err) {
    console.error(
      'FAIL: Cannot load playwright. Run npm install playwright in your project,',
    );
    console.error('     or set PLAYWRIGHT_MODULE_PATH to the playwright package path.');
    console.error(err.message);
    process.exit(1);
  }
}

const { chromium } = loadPlaywright();

(async () => {
  const htmlPath = process.argv[2];
  const pdfPath = process.argv[3];

  if (!htmlPath || !pdfPath) {
    console.error('Usage: node render_pdf.js <input.html> <output.pdf>');
    process.exit(2);
  }

  const url = 'file://' + path.resolve(htmlPath);
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.goto(url, { waitUntil: 'networkidle' });
    await page.pdf({
      path: pdfPath,
      format: 'A4',
      printBackground: true,
      margin: { top: '10mm', right: '10mm', bottom: '10mm', left: '10mm' },
    });
    console.log('OK', pdfPath);
  } catch (e) {
    console.error('FAIL', e.message);
    process.exit(1);
  } finally {
    await browser.close();
  }
})();
