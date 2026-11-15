"""Record the web-UI scenes with Playwright (1920x1080). Usage: ui_scenes.py [warm|record] [base_url]

`warm` runs every scenario once without recording, so model loading and LLM calls are cached and the
recorded run has no idle time. `record` writes build/ui_<scene>.webm.
"""
import shutil, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

MODE = sys.argv[1] if len(sys.argv) > 1 else "record"
BASE = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8765"
OUT = Path(__file__).parent / "build"
OUT.mkdir(exist_ok=True)

CURSOR_JS = """
(() => {
  const d = document.createElement('div');
  d.style.cssText = 'position:fixed;z-index:2147483647;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;' +
    'background:rgba(255,200,0,.35);border:3px solid #ffb300;pointer-events:none;left:-50px;top:-50px;transition:transform .08s';
  addEventListener('DOMContentLoaded', () => { document.body.style.zoom = '1.5'; const st = document.createElement('style'); st.textContent = '.workspace{height:calc(100dvh/1.5 - 44px)!important} dialog{max-height:calc(92dvh/1.5)!important;width:min(920px,calc(92vw/1.5))!important} .modal-body{max-height:calc(92dvh/1.5 - 44px)!important}'; document.head.append(st); document.documentElement.append(d); });  // 1.5x: readable text at 1080p
  addEventListener('mousemove', e => { d.style.left = e.clientX + 'px'; d.style.top = e.clientY + 'px'; }, true);
  addEventListener('mousedown', () => d.style.transform = 'scale(.7)', true);
  addEventListener('mouseup', () => d.style.transform = 'scale(1)', true);
})();
"""

def move_click(page, sel, pause=0.5):
    el = page.locator(sel).first
    el.scroll_into_view_if_needed()
    b = el.bounding_box()
    page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=35)
    time.sleep(pause)
    page.mouse.down(); time.sleep(0.08); page.mouse.up()

def choose(page, preset_id, defence=None):
    page.select_option("#scenario", preset_id)
    if defence:
        page.select_option("#defence", defence)

def run_and_wait(page, hold=2.0, approve=False, timeout=240000):
    move_click(page, "#run")
    if approve:
        page.wait_for_selector("button:has-text('Allow')", timeout=timeout)
        time.sleep(2.5)  # let the viewer read the amber row
        move_click(page, "button:has-text('Allow')")
    page.wait_for_function("() => !document.querySelector('#run').disabled && document.querySelector('#answer').textContent.trim().length > 1", timeout=timeout)
    time.sleep(hold)

# each scene: (name, function(page))
def scene_cite(p):
    choose(p, "french"); time.sleep(1.5)
    run_and_wait(p, hold=1.5)
    cite = ".citation, #answer button, #answer .citation"
    move_click(p, "#answer-sources .citation, #answer .citation")
    p.wait_for_selector("#page-modal[open] img", timeout=20000); time.sleep(3.5)
    move_click(p, "#close-modal")

def scene_trace(p):
    choose(p, "docs"); time.sleep(1.5)
    run_and_wait(p, hold=1.0)
    move_click(p, "#rows >> text=retrieve")
    time.sleep(3)

def scene_approval(p):
    choose(p, "r3"); time.sleep(1.5)
    run_and_wait(p, hold=1.0, approve=True)
    if "Show panel" in p.locator("#toggle-left").inner_text():
        move_click(p, "#toggle-left")  # bring back the left panel: answer and mock outbox
    time.sleep(3.5)

def scene_attack(p):
    choose(p, "egress", "none"); time.sleep(1.2)
    run_and_wait(p, hold=2.0)
    choose(p, "egress", "policy"); time.sleep(1.2)
    run_and_wait(p, hold=3.0)

SCENES = [("cite", scene_cite), ("trace", scene_trace), ("approval", scene_approval), ("attack", scene_attack)]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for name, fn in SCENES:
        kw = dict(viewport={"width": 1920, "height": 1080}, color_scheme="dark")
        if MODE == "record":
            kw["record_video_dir"] = str(OUT / "raw"); kw["record_video_size"] = {"width": 1920, "height": 1080}
        ctx = browser.new_context(**kw)  # fresh context: no bookmarks, extensions or state
        ctx.add_init_script(CURSOR_JS)
        page = ctx.new_page()
        page.goto(BASE); page.wait_for_selector("#run:not([disabled])"); time.sleep(1.5)
        t0 = time.time()
        fn(page)
        print(f"{name}: {time.time()-t0:.1f}s")
        v = page.video
        ctx.close()
        if MODE == "record":
            shutil.move(v.path(), OUT / f"ui_{name}.webm")
    browser.close()
