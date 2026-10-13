"""scripts/missing_plates.py: the species heard that no plate covers."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path

from tests._fixtures import create_birds_db, make_row

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "missing_plates.py"


def _load():
    spec = importlib.util.spec_from_file_location("missing_plates", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_it_lists_what_has_no_plate_most_heard_first(tmp_path, monkeypatch, capsys):
    plates = tmp_path / "plates"
    (plates / "img").mkdir(parents=True)
    (plates / "img" / "jay.jpg").write_bytes(b"x")
    (plates / "index.json").write_text(json.dumps({"species": [
        {"common": "Blue Jay", "scientific": "Cyanocitta cristata", "plate": 102, "image": "jay.jpg"}]}))
    monkeypatch.setenv("FEATHERFRAME_PLATES_DIR", str(plates))
    t = datetime(2026, 10, 1, 8)
    db = create_birds_db(tmp_path / "birds.db", [
        make_row(t, "Blue Jay", "Cyanocitta cristata"),
        make_row(t, "Eurasian Collared-Dove", "Streptopelia decaocto"),
        make_row(t, "Eurasian Collared-Dove", "Streptopelia decaocto"),
        make_row(t, "Carolina Wren", "Thryothorus ludovicianus"),
        make_row(t, "Ghost Bird", "Nullus nullus", confidence=0.3),     # under the floor
    ])
    mp = _load()
    monkeypatch.setattr("sys.argv", ["missing_plates.py", "--db", str(db), "--region", "north-america"])
    assert mp.main() == 0
    out = capsys.readouterr().out
    assert "3 species heard" in out and "2 with no plate" in out
    assert out.index("Streptopelia decaocto") < out.index("Thryothorus ludovicianus")
    assert "server/local/images/Streptopelia decaocto.jpg" in out
    assert "Blue Jay" not in out and "Nullus" not in out
    monkeypatch.setattr("sys.argv", ["missing_plates.py", "--db", str(db), "--all"])
    mp.main()
    assert "havell 102" in capsys.readouterr().out
