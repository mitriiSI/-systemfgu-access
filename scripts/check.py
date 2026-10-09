"""Check the self-contained web assets without third-party dependencies."""
import json
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
failures = []


def reference(source, value):
    if value.startswith(("#", "data:")):
        return
    url = urlsplit(value)
    if url.scheme or url.netloc:
        failures.append(f"{source.relative_to(ROOT)}: unexpected external asset")
        return
    if value.startswith("/"):
        failures.append(f"{source.relative_to(ROOT)}: absolute asset path {value}")
        return
    target = (source.parent / unquote(url.path)).resolve()
    if not target.is_relative_to(ROOT) or not target.is_file():
        failures.append(f"{source.relative_to(ROOT)}: missing asset {value}")


class Assets(HTMLParser):
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "img") and attrs.get("src"):
            reference(ROOT / "index.html", attrs["src"])
        if tag == "link" and attrs.get("href"):
            reference(ROOT / "index.html", attrs["href"])


Assets().feed((ROOT / "index.html").read_text())
for value in re.findall(r"\]\(([^)]+)\)", (ROOT / "README.md").read_text()):
    reference(ROOT / "README.md", value)
for path in (ROOT / "assets/css").glob("*.css"):
    for value in re.findall(r"url\(\s*['\"]?([^)'\"]+)['\"]?\s*\)", path.read_text()):
        reference(path, value.strip())
for path in (ROOT / "assets/js").glob("*.js"):
    result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    if result.returncode:
        failures.append(result.stderr)
for value in re.findall(r"file:\s*'([^']+)'", (ROOT / "assets/js/demo-data.js").read_text()):
    reference(ROOT / "index.html", value)
json.loads((ROOT / "package.json").read_text())
json.loads((ROOT / "docs/design-origin.json").read_text())
if failures:
    raise SystemExit("\n".join(failures))
print("OK: JavaScript syntax, JSON, README links, image paths and downloadable materials.")
