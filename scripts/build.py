"""Produce a portable static site in dist/. Requires only Python 3."""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist"
OUTPUT.mkdir(exist_ok=True)
shutil.copy2(ROOT / "index.html", OUTPUT / "index.html")
shutil.copytree(ROOT / "assets", OUTPUT / "assets", dirs_exist_ok=True)
(OUTPUT / ".nojekyll").touch()
print("Static site built in dist/.")
