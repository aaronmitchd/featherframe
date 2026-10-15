#!/usr/bin/env python3
"""Show Featherframe on a Pimoroni Inky Impression wired to this Pi.

The Inky is a frame like a tablet on the kiosk page (/view): it says who it
is and how big it is to GET /api/view/state, appears on the webapp as asking
to connect, and shows the waiting plate with its short id until the owner adds
it. Then it shows the picture the owner chose for it on its row (plates or the
collage), and repaints only when that picture changes: a full refresh of the
13.3" Spectra 6 takes about 35 s.

The panel's own resolution comes from the board (inky.auto reads its EEPROM).
The picture is asked for upright, portrait or landscape as the panel hangs, and
turned to the panel's native landscape before it is painted. Pimoroni's driver
dithers it to the panel's six inks.

Usage:
    python scripts/inky_frame.py                      # run until stopped
    python scripts/inky_frame.py --once               # paint the current picture, then exit
    python scripts/inky_frame.py --dry-run out.png    # no panel: write what would be painted
    python scripts/inky_frame.py --orientation landscape
"""
from __future__ import annotations

import argparse
import io
import logging
import re
import socket
import sys
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

import requests
from PIL import Image

log = logging.getLogger("featherframe.inky")

DEFAULT_SERVER = "http://127.0.0.1:8181"
# The 13.3" Inky Impression's native size, used only when no panel is attached
# (--dry-run); with one, the board says its own.
FALLBACK_RESOLUTION = (1600, 1200)
DEFAULT_POLL_S = 20
# Never paint more often than this: the panel is slow and wears with use.
MIN_PAINT_GAP_S = 60
SATURATION = 0.5          # Pimoroni's default for the Spectra 6 palette
TIMEOUT_S = 30


def default_id() -> str:
    """A stable id for this Inky: the host's name, as the server accepts ids."""
    host = re.sub(r"[^0-9A-Za-z._-]", "-", socket.gethostname())
    return f"INKY-{host}"[:40].upper()


def request_size(native: tuple[int, int], orientation: str) -> tuple[int, int]:
    """The upright size to ask the server for: the panel as it hangs."""
    long_side, short_side = max(native), min(native)
    return (short_side, long_side) if orientation == "portrait" else (long_side, short_side)


def to_native(image: Image.Image, native: tuple[int, int], turn: int) -> Image.Image:
    """An upright picture turned to the panel's own landscape. `turn` is the
    clockwise quarter turn (90 or 270) for a portrait panel, or 0/180 for a
    landscape one; a picture that still is not the panel's size is fitted."""
    rotations = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180,
                 270: Image.Transpose.ROTATE_90}
    if turn in rotations:
        image = image.transpose(rotations[turn])
    if image.size != native:
        canvas = Image.new("RGB", native, "white")
        image.thumbnail(native, Image.LANCZOS)
        canvas.paste(image, ((native[0] - image.width) // 2, (native[1] - image.height) // 2))
        image = canvas
    return image


def image_url(state: dict, viewer_id: str) -> Optional[str]:
    """Where the picture to show is, from /api/view/state's answer: the
    picture, or (not added yet) the waiting plate, which the server draws for
    any name under this viewer's path. None: nothing to show yet."""
    if state.get("waiting"):
        return f"/api/viewers/{quote(viewer_id, safe='')}/waiting.png"
    return state.get("image") or None


@dataclass
class Painted:
    url: Optional[str] = None
    etag: Optional[str] = None
    at: float = 0.0


class InkyPanel:
    """The Inky, or None-safe stand-in for --dry-run."""

    def __init__(self, dry_run: Optional[str]) -> None:
        self.dry_run = dry_run
        self.device = None
        if dry_run:
            self.resolution = FALLBACK_RESOLUTION
            return
        from inky.auto import auto   # Pi only: pip install -r requirements-inky.txt
        self.device = auto()
        self.resolution = tuple(self.device.resolution)
        log.info("Inky found: %s, %dx%d", type(self.device).__module__, *self.resolution)

    def paint(self, image: Image.Image) -> None:
        if self.dry_run:
            image.save(self.dry_run)
            log.info("dry run: wrote %s", self.dry_run)
            return
        self.device.set_image(image, saturation=SATURATION)
        self.device.show()   # blocks while the panel refreshes (~35 s on the 13.3")


class Frame:
    def __init__(self, args, panel: InkyPanel) -> None:
        self.server = args.server.rstrip("/")
        self.viewer_id = args.id
        self.orientation = args.orientation
        self.turn = args.turn if args.orientation == "portrait" else (180 if args.flip else 0)
        self.panel = panel
        self.session = requests.Session()
        self.painted = Painted()

    def state(self) -> dict:
        w, h = request_size(self.panel.resolution, self.orientation)
        r = self.session.get(f"{self.server}/api/view/state", timeout=TIMEOUT_S, params={
            "viewer": self.viewer_id, "w": w, "h": h, "device": "Inky Impression"})
        r.raise_for_status()
        return r.json()

    def step(self) -> int:
        """One check: paint if the picture changed. Returns seconds to wait."""
        state = self.state()
        poll = int(state.get("poll") or DEFAULT_POLL_S)
        url = image_url(state, self.viewer_id)
        if url is None:
            return poll
        headers = {}
        if url == self.painted.url and self.painted.etag:
            headers["If-None-Match"] = f'"{self.painted.etag}"'
        r = self.session.get(self.server + url, headers=headers, timeout=TIMEOUT_S)
        if r.status_code == 304:
            return poll
        r.raise_for_status()
        wait = MIN_PAINT_GAP_S - (time.monotonic() - self.painted.at)
        if self.painted.at and wait > 0:
            return int(wait) + 1
        picture = Image.open(io.BytesIO(r.content)).convert("RGB")
        log.info("painting %s", "the waiting plate" if state.get("waiting") else url)
        self.panel.paint(to_native(picture, self.panel.resolution, self.turn))
        self.painted = Painted(url, (r.headers.get("ETag") or "").strip('"') or None,
                               time.monotonic())
        return poll

    def run(self, once: bool) -> int:
        while True:
            try:
                wait = self.step()
                if once and self.painted.at:
                    return 0
            except requests.RequestException as exc:
                log.warning("server not reachable (%s); trying again", exc)
                wait = DEFAULT_POLL_S
            if once and not self.painted.at:
                log.info("nothing to paint yet")
                return 1
            time.sleep(wait)


def main() -> int:
    ap = argparse.ArgumentParser(description="Show Featherframe on an Inky Impression.")
    ap.add_argument("--server", default=DEFAULT_SERVER, help=f"default {DEFAULT_SERVER}")
    ap.add_argument("--id", default=default_id(), help="this frame's id (default INKY-<hostname>)")
    ap.add_argument("--orientation", choices=("portrait", "landscape"), default="portrait",
                    help="how the panel hangs (default portrait)")
    ap.add_argument("--turn", type=int, choices=(90, 270), default=90,
                    help="portrait only: 270 if the picture comes out upside down")
    ap.add_argument("--flip", action="store_true", help="landscape only: turn the picture 180°")
    ap.add_argument("--once", action="store_true", help="paint once, then exit")
    ap.add_argument("--dry-run", metavar="PNG", help="no panel: write the image to this file")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        panel = InkyPanel(args.dry_run)
    except Exception as exc:  # noqa: BLE001 — no library, no board, no SPI
        log.error("no Inky panel (%s). Run scripts/install_inky.sh and reboot.", exc)
        return 2
    log.info("asking %s as %s (%s)", args.server, args.id, args.orientation)
    return Frame(args, panel).run(args.once or bool(args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
