const fs = require('fs');
const path = require('path');

const repoRoot = path.resolve(__dirname, '..');
const htmlPath = path.join(repoRoot, 'web', 'real-estate-demo.html');
const placeholder = '__UA_HOMES_API__';
const api = process.env.UA_HOMES_API || '';

if (!fs.existsSync(htmlPath)) {
  console.error(`Missing file: ${htmlPath}`);
  process.exit(1);
}

let html = fs.readFileSync(htmlPath, 'utf8');
if (api) {
  html = html.replace(placeholder, api);
  console.log(`Injected UA_HOMES_API=${api}`);
} else {
  console.log('UA_HOMES_API not provided; leaving placeholder for local fallback');
}
fs.writeFileSync(htmlPath, html);
