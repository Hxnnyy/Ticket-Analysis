import os, subprocess, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(r"c:\Users\Joe\Downloads\Ticket Analysis")
PORT = 8537
env = os.environ.copy()
env['STREAMLIT_SERVER_HEADLESS'] = 'true'
env['STREAMLIT_SERVER_PORT'] = str(PORT)
process = subprocess.Popen([
    'python',
    '-m','streamlit','run','dashboard.py',
    f'--server.port={PORT}',
    '--server.headless=true'
], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
url = f'http://localhost:{PORT}'
start = time.time()
while time.time() - start < 60:
    try:
        urllib.request.urlopen(url)
        break
    except Exception:
        time.sleep(0.5)
else:
    raise RuntimeError('Server start timeout')

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(url, wait_until='networkidle')
    page.wait_for_timeout(3000)
    count = page.evaluate('''() => Array.from(document.querySelectorAll('[role="checkbox"], [role="switch"]')).length''')
    print('checkbox-like count', count)
    if count:
        info = page.evaluate('''() => Array.from(document.querySelectorAll('[role="checkbox"], [role="switch"]')).map(el => ({text: el.innerText, ariaLabel: el.getAttribute('aria-label'), role: el.getAttribute('role')}))''')
        print(info)
    browser.close()

process.terminate()
try:
    process.wait(timeout=10)
except subprocess.TimeoutExpired:
    process.kill()
