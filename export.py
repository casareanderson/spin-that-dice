#!/usr/bin/env python3
"""Bake the index into a static site (no server, no API key, nothing to attack).

    python3 export.py            -> ./docs   (GitHub Pages / Cloudflare Pages root)

The page detects the missing /api and rolls from docs/index.json in the browser,
so web/index.html stays the single copy.
"""
import json, os, shutil, sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "docs"

cats = json.loads((DATA / "categories.json").read_text())
merged = {c: {} for c in cats}
for src in ("crate.json", "index.json"):
    p = DATA / src
    if not p.exists():
        continue
    blob = json.loads(p.read_text())
    for cat, val in blob.items():
        if cat not in merged:
            continue
        for t in (val.get("tracks", []) if isinstance(val, dict) else val):
            if t.get("id"):
                merged[cat][t["id"]] = {k: t.get(k, "") for k in ("id", "n", "a", "y")}

out = {c: list(v.values()) for c, v in merged.items()}
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "index.json").write_text(json.dumps(
    {"built": datetime.now(timezone.utc).isoformat(timespec="seconds"), "cats": out},
    ensure_ascii=False, separators=(",", ":")))
shutil.copy(HERE / "web" / "index.html", OUT / "index.html")
for extra in ("manifest.json", "icon-192.png", "icon-512.png"):
    shutil.copy(HERE / "web" / extra, OUT / extra)
if not (OUT / "config.json").exists():          # never clobber a deployed client id
    shutil.copy(HERE / "web" / "config.json", OUT / "config.json")
(OUT / ".nojekyll").write_text("")
if os.environ.get("SPIN_DOMAIN"):
    (OUT / "CNAME").write_text(os.environ["SPIN_DOMAIN"] + "\n")

total = sum(len(v) for v in out.values())
ready = sum(1 for v in out.values() if v)
print(f"{OUT}: {total} tracks, {ready}/{len(cats)} categories populated, "
      f"{(OUT / 'index.json').stat().st_size / 1024:.0f} KB")
