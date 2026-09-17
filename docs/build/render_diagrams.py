"""
docs/build/render_diagrams.py — Extract every ```mermaid block from the repo's Markdown and render
it to PNG (docs/diagrams/) via the public Kroki service. Used to embed diagrams in the Word/PPTX deliverables.

Usage: python docs/build/render_diagrams.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "diagrams"
SOURCES = {
    "architecture": ROOT / "README.md",
    "setup": ROOT / "setup" / "README.md",
    "discovery": ROOT / "discovery" / "README.md",
    "agents": ROOT / "agents" / "README.md",
    "monitoring": ROOT / "monitoring" / "README.md",
    "evaluation": ROOT / "evaluation" / "README.md",
    "orchestration": ROOT / "orchestration" / "README.md",
    "sequence": ROOT / "SOLUTION_DESIGN.md",
}
BLOCK_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
KROKI = "https://kroki.io/mermaid/png"


def render(name: str, source: str) -> Path:
    # Kroki's headless renderer has no colour-emoji font; strip emoji so labels stay clean.
    source = re.sub(r"[\U0001F300-\U0001FAFF⌀-⏿☀-➿⬀-⯿️]", "", source)
    resp = requests.post(KROKI, data=source.encode("utf-8"), headers={"Content-Type": "text/plain"}, timeout=90)
    if resp.status_code != 200:
        raise RuntimeError(f"{name}: Kroki {resp.status_code}: {resp.text[:300]}")
    path = OUT / f"{name}.png"
    path.write_bytes(resp.content)
    flatten(path)
    return path


def flatten(path: Path, background=(11, 14, 20), pad: int = 24) -> None:
    """The dark Mermaid theme is transparent — composite onto a dark page so it prints on white paper."""
    from PIL import Image

    im = Image.open(path).convert("RGBA")
    canvas = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), background + (255,))
    canvas.alpha_composite(im, (pad, pad))
    canvas.convert("RGB").save(path, optimize=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, md in SOURCES.items():
        blocks = BLOCK_RE.findall(md.read_text(encoding="utf-8"))
        if not blocks:
            print(f"[SKIP] {name}: no mermaid block in {md.name}")
            continue
        for i, block in enumerate(blocks):
            suffix = "" if len(blocks) == 1 else f"-{i + 1}"
            path = render(name + suffix, block)
            print(f"[OK] {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.exit(f"[ERROR] {exc}")
