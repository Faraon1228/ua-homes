const fs = require('fs');
const path = require('path');

const repoRoot = path.resolve(__dirname, '..');
const htmlPath = path.join(repoRoot, 'web', 'real-estate-demo.html');
const robotsPath = path.join(repoRoot, 'web', 'robots.txt');
const apiPlaceholder = '__UA_HOMES_API__';
const publicPlaceholder = '__UA_HOMES_PUBLIC_URL__';
const api = process.env.UA_HOMES_API || '';
const publicUrl = (process.env.UA_HOMES_PUBLIC_URL || '').replace(/\/$/, '');

if (!fs.existsSync(htmlPath)) {
  console.error(`Missing file: ${htmlPath}`);
  process.exit(1);
}
if (!fs.existsSync(robotsPath)) {
  console.error(`Missing file: ${robotsPath}`);
  process.exit(1);
}

let html = fs.readFileSync(htmlPath, 'utf8');
if (api) {
  html = html.split(apiPlaceholder).join(api);
  console.log(`Injected UA_HOMES_API=${api}`);
} else {
  console.log('UA_HOMES_API not provided; leaving placeholder for local fallback');
}
if (publicUrl) {
  html = html.split(publicPlaceholder).join(publicUrl);
  let robots = fs.readFileSync(robotsPath, 'utf8');
  robots = robots.split(publicPlaceholder).join(publicUrl);
  fs.writeFileSync(robotsPath, robots);
  console.log(`Injected UA_HOMES_PUBLIC_URL=${publicUrl}`);
} else {
  console.log('UA_HOMES_PUBLIC_URL not provided; leaving placeholder for runtime fallback');
}
fs.writeFileSync(htmlPath, html);
