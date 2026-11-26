"""Capture REAL screenshots and the demo GIF with Playwright.

Prerequisites: the pipeline has run, the dashboard is running on port 8540,
and `python -m playwright install chromium` was done.

Usage:
  python scripts/capture_screenshots.py            # dashboard, Excel, profiling, terminal, gif
  python scripts/capture_screenshots.py ci <url>   # GitHub Actions run page (after CI is green)
"""

import html
import shutil
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "docs" / "screenshots"
REPORTS = ROOT / "reports"
DASHBOARD = "http://localhost:8540"
TMP = ROOT / ".tmp"


def open_page(p, width=1440, height=1000, **kwargs):
    browser = p.chromium.launch()
    context = browser.new_context(viewport={"width": width, "height": height}, **kwargs)
    return browser, context, context.new_page()


def wait_streamlit(page, text: str, settle: int = 7000):
    page.wait_for_selector(f"text={text}", timeout=60000)
    page.wait_for_timeout(settle)        # let Vega charts and tables finish rendering


def goto_view(page, label: str, heading: str, settle: int = 7000):
    page.locator("section[data-testid='stSidebar'] label").filter(has_text=label).first.click()
    wait_streamlit(page, heading, settle)


def dashboard_shots(p):
    browser, _, page = open_page(p, height=1150)
    page.goto(DASHBOARD)
    wait_streamlit(page, "Load reconciliation")
    page.screenshot(path=SHOTS / "01-reconciliation.png")
    goto_view(page, "Rejected records", "Rejected records (quarantine)")
    page.screenshot(path=SHOTS / "02-rejections.png")
    browser.close()


def excel_shot(p):
    subprocess.run([sys.executable, str(ROOT / "scripts" / "render_excel.py"), "Summary"], check=True)
    browser, _, page = open_page(p, width=1500, height=760)
    page.goto((REPORTS / "excel_preview.html").as_uri())
    page.screenshot(path=SHOTS / "03-excel-report.png")
    browser.close()


def profiling_shot(p):
    browser, _, page = open_page(p, width=1500, height=1050)
    page.goto((REPORTS / "profiling_report.html").as_uri())
    page.screenshot(path=SHOTS / "04-profiling.png")
    browser.close()


def terminal_shot(p):
    """Render the captured stdout of a real pipeline run (reports/pipeline_run.log)."""
    log = (REPORTS / "pipeline_run.log").read_text(encoding="utf-8")
    page_html = ("<html><body style='margin:0;background:#0c0c0c'>"
                 "<div style='background:#2d2d2d;color:#ccc;font:13px Segoe UI;padding:6px 12px'>"
                 "PowerShell &mdash; D:\\projects\\resume\\migrateright</div>"
                 "<pre style='color:#cccccc;font:14px Consolas,monospace;padding:12px 16px;margin:0'>"
                 f"<span style='color:#16c60c'>PS&gt;</span> python -m src.pipeline\n{html.escape(log)}</pre>"
                 "</body></html>")
    path = TMP / "terminal.html"
    path.write_text(page_html, encoding="utf-8")
    browser, _, page = open_page(p, width=1460, height=470)
    page.goto(path.as_uri())
    page.screenshot(path=SHOTS / "05-terminal-run.png", full_page=True)
    browser.close()


def demo_gif(p):
    """Record the Streamlit flow (~16 s) and convert to an optimised GIF with ffmpeg."""
    video_dir = TMP / "video"
    shutil.rmtree(video_dir, ignore_errors=True)
    browser, context, page = open_page(p, width=1280, height=800, record_video_dir=str(video_dir),
                                       record_video_size={"width": 1280, "height": 800})
    page.goto(DASHBOARD)
    wait_streamlit(page, "Load reconciliation", 3500)
    page.mouse.move(800, 600)
    page.mouse.wheel(0, 450)
    page.wait_for_timeout(1800)
    goto_view(page, "Rejected records", "Rejected records (quarantine)", 3000)
    goto_view(page, "Duplicates merged", "Duplicates merged", 2500)
    goto_view(page, "Data profiling", "Legacy data profiling", 2500)
    goto_view(page, "Sign-off", "Business sign-off", 2000)
    context.close()
    browser.close()
    webm = next(video_dir.glob("*.webm"))
    gif = SHOTS / "demo.gif"
    # skip the blank first second, cap at 19 s, 6 fps, 900 px wide, shared palette
    vf = "fps=6,scale=900:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-t", "19", "-i", str(webm),
                    "-vf", vf, str(gif)], check=True)


def ci_shot(p, url: str):
    browser, _, page = open_page(p, width=1400, height=900)
    page.goto(url, wait_until="networkidle")
    page.wait_for_timeout(3000)
    page.screenshot(path=SHOTS / "06-ci-passing.png")
    browser.close()


if __name__ == "__main__":
    SHOTS.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        if len(sys.argv) > 2 and sys.argv[1] == "ci":
            ci_shot(pw, sys.argv[2])
        else:
            dashboard_shots(pw)
            excel_shot(pw)
            profiling_shot(pw)
            terminal_shot(pw)
            demo_gif(pw)
    for f in sorted(SHOTS.iterdir()):
        print(f"{f.name:<24} {f.stat().st_size / 1024:8.0f} KB")
