import os
import pathlib

repo_root = pathlib.Path(__file__).resolve().parent.parent
html_path = repo_root / 'web' / 'real-estate-demo.html'
robots_path = repo_root / 'web' / 'robots.txt'
api_placeholder = '__UA_HOMES_API__'
public_placeholder = '__UA_HOMES_PUBLIC_URL__'
api = os.environ.get('UA_HOMES_API', '')
public_url = os.environ.get('UA_HOMES_PUBLIC_URL', '').rstrip('/')

if not html_path.exists():
    raise SystemExit(f'Missing file: {html_path}')
if not robots_path.exists():
    raise SystemExit(f'Missing file: {robots_path}')

html = html_path.read_text(encoding='utf-8')
if api:
    html = html.replace(api_placeholder, api)
    print(f'Injected UA_HOMES_API={api}')
else:
    print('UA_HOMES_API not provided; leaving placeholder for local fallback')

if public_url:
    html = html.replace(public_placeholder, public_url)
    robots = robots_path.read_text(encoding='utf-8').replace(public_placeholder, public_url)
    robots_path.write_text(robots, encoding='utf-8')
    print(f'Injected UA_HOMES_PUBLIC_URL={public_url}')
else:
    print('UA_HOMES_PUBLIC_URL not provided; leaving placeholder for runtime fallback')

html_path.write_text(html, encoding='utf-8')
