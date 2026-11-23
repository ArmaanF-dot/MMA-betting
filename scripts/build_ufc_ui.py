"""Inject ufc-ui/data.json into ufc-ui/template.html and write ufc-ui/index.html. Re-run `scripts/signal_data.py` then this to refresh the page."""
import json
from pathlib import Path

root = Path("ufc-ui")
data = json.loads((root / "data.json").read_text(encoding="utf-8"))
blob = json.dumps(data, separators=(",", ":")).replace("<", "\\u003c")
html = (root / "template.html").read_text(encoding="utf-8").replace("__DATA__", blob)
(root / "index.html").write_text(html, encoding="utf-8")
print(f"wrote ufc-ui/index.html, {len(html) / 1024:.0f} KB, {len(data['cards'])} cards")
