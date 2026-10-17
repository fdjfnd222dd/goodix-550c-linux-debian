#!/usr/bin/env python3
"""Render screenshots of every `finger` page from the demo backend (no sensor, no real data).

Run from the repo root:
  build/tui-venv/bin/python scripts/make_tui_screenshots.py                 # README set -> docs/img/
  build/tui-venv/bin/python scripts/make_tui_screenshots.py --all --out DIR # every state, 120x35 + 200x50

The README set is finger-{home,enroll,test,settings}.svg at 160x45. With --png each SVG is also
turned into a PNG with headless Firefox (or ImageMagick when Firefox is missing).
"""
import argparse
import asyncio
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tui"))

from goodix550c_tui.app import FingerApp  # noqa: E402
from goodix550c_tui.demo import FakeBackend  # noqa: E402

README_SIZE = (160, 45)


async def until(pilot, cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end and not cond():
        await pilot.pause(0.02)


def to_png(svg: Path, png: Path, width_px: int) -> None:
    ff = shutil.which("firefox")
    if ff:
        with tempfile.TemporaryDirectory() as prof:
            subprocess.run([ff, "--headless", "--no-remote", "--profile", prof, "--screenshot", str(png),
                            f"--window-size={width_px},{int(width_px * 0.75)}", svg.resolve().as_uri()],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90, check=False)
    elif shutil.which("convert"):
        subprocess.run(["convert", str(svg), str(png)], check=False)
    if png.exists() and shutil.which("convert"):     # drop the white margin round the window
        subprocess.run(["convert", str(png), "-trim", "+repage", str(png)], check=False)


class Shooter:
    def __init__(self, out: Path, png: bool, suffix: str):
        self.out, self.png, self.suffix = out, png, suffix
        out.mkdir(parents=True, exist_ok=True)

    def save(self, app, name):
        for v in app.query("FingerprintView"):
            v.settle()
        app.query_one("#msg").update("")           # no leftover "Stopped." from the previous shot
        svg = self.out / f"finger-{name}{self.suffix}.svg"
        svg.write_text(app.export_screenshot(title="finger"))
        print("wrote", svg)
        if self.png:
            cols = app.size.width
            to_png(svg, svg.with_suffix(".png"), max(1200, cols * 9 + 60))


async def shoot(size, shots: Shooter, everything: bool):
    be = FakeBackend(step=0.05, stages=17)
    app = FingerApp(backend=be, score_poll=0.01)
    async with app.run_test(size=size) as pilot:
        await until(pilot, lambda: app.status is not None)
        await pilot.pause(0.3)
        shots.save(app, "home")

        await pilot.press("2", "right")             # enroll: right middle finger
        await pilot.pause(0.2)
        if everything:
            shots.save(app, "enroll-pick")
        page = app.query_one("#page2")
        view = app.query_one("#enr-view")

        async def enroll_to(stages_done, then=None):
            be.enroll_script = ["stage"] * stages_done + ([then] if then else []) + ["wait"]
            if page.mode != "pick":
                await pilot.press("escape")
            await pilot.press("enter")
            await until(pilot, lambda: page.stage == stages_done and page.mode == "run")
            await pilot.pause(0.15 if then else 0.0)

        await enroll_to(10)                         # ~60 % full, waiting for the next touch
        page._press()
        await pilot.pause(0.1)
        shots.save(app, "enroll")                   # the README picture
        if everything:
            shots.save(app, "enroll-press")
            await enroll_to(4)
            await pilot.pause(0.1)
            view.set("lift", "LIFT", "Good. Lift your finger off the sensor.", next_hint="13 more touches to go.")
            view._state_t = time.monotonic()         # flash on-phase
            shots.save(app, "enroll-lift")
            await enroll_to(7, "retry")
            view._state_t = time.monotonic()
            shots.save(app, "enroll-retry")
            await pilot.press("escape")
            be.enroll_script = None
            be.step = 0.01
            await pilot.press("enter")
            await until(pilot, lambda: page.mode == "end", 15)
            await pilot.pause(0.2)
            shots.save(app, "enroll-done")
            be.step = 0.05
        await pilot.press("escape")
        if page.mode != "pick":
            await pilot.press("escape")

        await pilot.press("3")
        await pilot.pause(0.1)
        if everything:
            shots.save(app, "test-ready")
        be.verify_script = [["match"]]
        await pilot.press("enter")
        t = app.query_one("#page3")
        await until(pilot, lambda: t.mode == "end")
        await pilot.pause(0.3)
        shots.save(app, "test")
        if everything:
            shots.save(app, "test-match")
            be.verify_script = [["no-match"]]
            be._verify_runs = 0
            await pilot.press("enter")
            await until(pilot, lambda: t.mode == "end" and t.result == "no-match")
            await pilot.pause(0.3)
            app.query_one("#tst-view")._state_t = time.monotonic()
            shots.save(app, "test-nomatch")

        await pilot.press("4", "right", "down", "right", "right", "right", "right", "right")
        await pilot.pause(0.1)
        shots.save(app, "settings")
        if everything:
            await pilot.press("5")
            await pilot.pause(0.1)
            shots.save(app, "help")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "img")
    ap.add_argument("--all", action="store_true", help="every state at 120x35 and 200x50 (name-WxH.svg)")
    ap.add_argument("--size", default="", help="only this size, e.g. 250x55 (with --all)")
    ap.add_argument("--png", action="store_true", help="also write PNGs")
    a = ap.parse_args()
    if a.all:
        sizes = [tuple(int(x) for x in a.size.split("x"))] if a.size else [(120, 35), (200, 50)]
        for size in sizes:
            asyncio.run(shoot(size, Shooter(a.out, a.png, f"-{size[0]}x{size[1]}"), True))
    else:
        asyncio.run(shoot(README_SIZE, Shooter(a.out, a.png, ""), False))


if __name__ == "__main__":
    main()
