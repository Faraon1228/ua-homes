import os
import pathlib

repo_root = pathlib.Path(__file__).resolve().parent.parent
html_path = repo_root / 'web' / 'real-estate-demo.html'
placeholder = '__UA_HOMES_API__'
api = os.environ.get('UA_HOMES_API', '')

if not html_path.exists():
    raise SystemExit(f'Missing file: {html_path}')

html = html_path.read_text(encoding='utf-8')
if api:
    html = html.replace(placeholder, api)
    print(f'Injected UA_HOMES_API={api}')
else:
    print('UA_HOMES_API not provided; leaving placeholder for local fallback')

html_path.write_text(html, encoding='utf-8')
