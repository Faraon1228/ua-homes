import json
import os
import pathlib

repo_root = pathlib.Path(__file__).resolve().parent.parent
html_path = repo_root / 'web' / 'real-estate-demo.html'
js_path   = repo_root / 'web' / 'real-estate-app.js'
monitoring_paths = (repo_root / 'web' / 'monitoring.js', repo_root / 'web' / 'admin' / 'monitoring.js')
robots_path = repo_root / 'web' / 'robots.txt'
api_placeholder = '__UA_HOMES_API__'
public_placeholder = '__UA_HOMES_PUBLIC_URL__'
api = os.environ.get('UA_HOMES_API', '')
public_url = os.environ.get('UA_HOMES_PUBLIC_URL', '').rstrip('/')

for p in (html_path, robots_path):
    if not p.exists():
        raise SystemExit(f'Missing file: {p}')

html = html_path.read_text(encoding='utf-8')
js   = js_path.read_text(encoding='utf-8') if js_path.exists() else ''

if api:
    html = html.replace(api_placeholder, api)
    js   = js.replace(api_placeholder, api)
    print(f'Injected UA_HOMES_API={api}')
else:
    print('UA_HOMES_API not provided; leaving placeholder for local fallback')

if public_url:
    html   = html.replace(public_placeholder, public_url)
    js     = js.replace(public_placeholder, public_url)
    robots = robots_path.read_text(encoding='utf-8').replace(public_placeholder, public_url)
    robots_path.write_text(robots, encoding='utf-8')
    print(f'Injected UA_HOMES_PUBLIC_URL={public_url}')
else:
    print('UA_HOMES_PUBLIC_URL not provided; leaving placeholder for runtime fallback')

html_path.write_text(html, encoding='utf-8')
if js:
    js_path.write_text(js, encoding='utf-8')
monitoring_values = {
    '__UA_HOMES_SENTRY_WEB_DSN__': os.environ.get('UA_HOMES_SENTRY_WEB_DSN', ''),
    '__UA_HOMES_SENTRY_ADMIN_DSN__': os.environ.get('UA_HOMES_SENTRY_ADMIN_DSN', ''),
    '__UA_HOMES_SENTRY_ENVIRONMENT__': os.environ.get('UA_HOMES_SENTRY_ENVIRONMENT', 'production'),
    '__UA_HOMES_SENTRY_RELEASE__': os.environ.get('UA_HOMES_SENTRY_RELEASE') or os.environ.get('GITHUB_SHA', ''),
    '__UA_HOMES_SENTRY_WEB_TRACES_SAMPLE_RATE__': os.environ.get('UA_HOMES_SENTRY_WEB_TRACES_SAMPLE_RATE', '0.01'),
    '__UA_HOMES_SENTRY_ADMIN_TRACES_SAMPLE_RATE__': os.environ.get('UA_HOMES_SENTRY_ADMIN_TRACES_SAMPLE_RATE', '0.01'),
}
for monitoring_path in monitoring_paths:
    if not monitoring_path.exists():
        raise SystemExit(f'Missing file: {monitoring_path}')
    content = monitoring_path.read_text(encoding='utf-8')
    for placeholder, value in monitoring_values.items():
        content = content.replace(json.dumps(placeholder), json.dumps(value))
    monitoring_path.write_text(content, encoding='utf-8')
print('Prepared optional browser monitoring configuration (DSN values not displayed)')
