"""scripts/inky_frame.py: the Inky Impression client's sizing and turning."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inky_frame.py"


def _load():
    spec = importlib.util.spec_from_file_location("inky_frame", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod      # its dataclass looks itself up there
    spec.loader.exec_module(mod)
    return mod


def test_it_asks_for_the_panel_as_it_hangs():
    inky = _load()
    assert inky.request_size((1600, 1200), "portrait") == (1200, 1600)
    assert inky.request_size((1600, 1200), "landscape") == (1600, 1200)


def test_an_upright_picture_is_turned_to_the_native_landscape():
    inky = _load()
    portrait = Image.new("RGB", (1200, 1600), "white")
    portrait.putpixel((0, 0), (255, 0, 0))                 # the picture's top left
    cw = inky.to_native(portrait, (1600, 1200), 90)
    assert cw.size == (1600, 1200) and cw.getpixel((1599, 0)) == (255, 0, 0)
    ccw = inky.to_native(portrait, (1600, 1200), 270)
    assert ccw.getpixel((0, 1199)) == (255, 0, 0)
    small = inky.to_native(Image.new("RGB", (800, 600), "black"), (1600, 1200), 0)
    assert small.size == (1600, 1200) and small.getpixel((800, 600)) == (0, 0, 0)


def test_it_shows_the_waiting_plate_until_added():
    inky = _load()
    assert inky.image_url({"waiting": True, "id": "Y-TEST"}, "INKY-TEST") \
        == "/api/viewers/INKY-TEST/waiting.png"
    assert inky.image_url({"image": "/api/viewers/INKY-TEST/abc-1200x1600-color-0.png"},
                          "INKY-TEST").endswith("color-0.png")
    assert inky.image_url({"image": None}, "INKY-TEST") is None
    assert inky.default_id().startswith("INKY-") and len(inky.default_id()) <= 40
