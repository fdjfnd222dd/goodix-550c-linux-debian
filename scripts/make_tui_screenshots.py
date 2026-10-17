#!/usr/bin/env python3
"""Regenerate docs/img/finger-*.svg from the demo backend (no sensor, no real data).

Run from the repo root:  build/tui-venv/bin/python scripts/make_tui_screenshots.py
"""
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tui"))

from goodix550c_tui.app import FingerApp  # noqa: E402
from goodix550c_tui.demo import FakeBackend  # noqa: E402

OUT = ROOT / "docs" / "img"
SIZE = (126, 38)


async def until(pilot, cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end and not cond():
        await pilot.pause(0.02)


def save(app, name):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"finger-{name}.svg").write_text(app.export_screenshot(title="finger"))
    print("wrote", OUT / f"finger-{name}.svg")


async def main():
    be = FakeBackend(step=0.05, stages=8)
    app = FingerApp(backend=be, score_poll=0.01)
    async with app.run_test(size=SIZE) as pilot:
        await until(pilot, lambda: app.status is not None)
        await pilot.pause(0.3)
        save(app, "home")

        # enroll: right middle finger, stopped at 5 of 8 scans, waiting for the next touch
        be.enroll_script = ["stage"] * 5 + ["wait"]
        await pilot.press("2", "right", "enter")
        page = app.query_one("#page2")
        await until(pilot, lambda: page.stage == 5)
        page._press()                      # skip the 1 s LIFT pause: show the green PRESS state
        await pilot.pause(0.3)
        save(app, "enroll")
        await pilot.press("escape")

        be.verify_script = [["match"]]
        await pilot.press("3", "enter")
        t = app.query_one("#page3")
        await until(pilot, lambda: t.mode == "end")
        await pilot.pause(0.3)
        save(app, "test")


asyncio.run(main())
