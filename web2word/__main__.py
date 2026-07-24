"""CLI: python -m web2word manifest.yml"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .build import Manifest, build


def _load_manifest(path: str) -> Manifest:
    text = Path(path).read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
    except ModuleNotFoundError:
        data = _mini_yaml(text)
    return Manifest(
        base_url=data["base_url"],
        pages=data["pages"],
        output=data.get("output", "output.docx"),
        style_reference=data.get("style_reference"),
        local_dir=data.get("local_dir"),
    )


def _mini_yaml(text: str) -> dict:
    """Tiny YAML subset parser so the tool runs with zero extra deps.

    Supports: `key: value` scalars and a `pages:` block of `- item` lines.
    """
    data: dict = {}
    pages: list[str] = []
    in_pages = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if in_pages and line.lstrip().startswith("- "):
            pages.append(line.split("- ", 1)[1].strip())
            continue
        in_pages = False
        if ":" in line:
            key, _, val = line.partition(":")
            key, val = key.strip(), val.strip()
            if key == "pages" and not val:
                in_pages = True
                data["pages"] = pages
            else:
                data[key] = val
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="web2word", description=__doc__)
    ap.add_argument("manifest", help="path to a manifest .yml")
    ap.add_argument("-o", "--output", help="override output path")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    manifest = _load_manifest(args.manifest)
    if args.output:
        manifest.output = args.output

    print(f"web2word: {len(manifest.pages)} page(s) -> {manifest.output}")
    out = build(manifest, verbose=args.verbose)
    print(f"done: {out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
